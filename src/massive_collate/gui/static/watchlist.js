// Watchlist (right rail, beside the chart): quick access to symbols, as TradingView's. Only your
// watchlists, nothing else (the user, 2026-10-31: "those are only watchlists no other kinds of lists"):
// each keeps the symbols you add in your order (saved in the database, /api/watchlists, each profile
// its own), with its exchange, last price, change and volume. A profile without one starts with an
// empty "Watchlist", saved with its first symbol. A click opens the symbol on the chart.
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const { symbolIcon, esc } = window.MassiveIcons;
  const FIRST = 'Watchlist';  // a profile's list before it has one of its own
  let lists = [];  // [{ name, tickers: [] }]
  let current = prefs.get('watchlist', FIRST);
  let query = '';
  let sort = prefs.get('watchSort', { key: 'symbol', dir: 1 });
  // The list as a table or as a heat map (the user, 2026-10-28: "heat maps for all the exchanges ... as
  // well as watchlist(s) so when i open the symbol picker or watchlist picker, its easier to figure").
  let view = prefs.get('watchView', 'list');
  const MAP_EQUAL = 400;  // a list up to this many: equal tiles; longer: by dollar volume
  const MAP_REDRAW_MS = 15000;  // the map drawn again with the activity polls at most this often
  let mapDrawn = 0;

  const shown = () => document.body.dataset.pane === 'watchlist';

  // The list shown: the one picked, or the first; with none, an empty FIRST (saved with its first symbol).
  function shownList() {
    if (!lists.length) lists.push({ name: FIRST, tickers: [] });
    const mine = lists.find((l) => l.name === current) || lists[0];
    current = mine.name;
    return mine;
  }

  async function load() {
    try {
      lists = (await api('/api/watchlists')).lists || [];
    } catch { lists = []; }
    shownList();
    render();
  }

  // One save at a time, each sending the lists as they are when it goes: two at once could reach the
  // server in either order, the older undoing the newer. The server's copy is taken only from the last
  // save waiting (an earlier answer lacks the changes still to go).
  let saving = Promise.resolve();
  let waiting = 0;
  function save() {
    waiting += 1;
    saving = saving.then(async () => {
      try {
        const res = await apiWrite('PUT', '/api/watchlists', { lists });
        if (waiting === 1) lists = res.lists;
      } catch (err) { showError(err); } finally { waiting -= 1; }
      render();
    });
    return saving;
  }

  // Live price where the symbol is streaming; otherwise the last session's close and change.
  function quote(sym) {
    const close = sym.market?.close ?? null, pct = sym.market?.changePct ?? sym.changePct ?? null;
    let live = null;
    for (const s of Object.values(window.Activity?.data?.liveFeeds?.streams || {})) {
      const p = s.pairs?.[sym.ticker];
      if (s.connected && p?.price != null && (live == null || p.last > live.last)) live = p;
    }
    const isLiveNow = (window.Activity?.data?.liveFeeds?.liveTickers || []).includes(sym.ticker);
    const vol = sym.market?.volume ?? null;  // the last session's (shares)
    if (isLiveNow && live) {
      const prev = close != null && pct != null ? close / (1 + pct / 100) : null;
      return { last: live.price, pct: prev ? (live.price / prev - 1) * 100 : null, vol, live: true };
    }
    return { last: close, pct, vol, live: false };
  }

  const fmtPrice = (v) => (v == null ? '–' : Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: Math.abs(v) < 1 ? 6 : Math.abs(v) < 100 ? 4 : 2 }));
  const fmtPct = (v) => (v == null ? '' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`);
  // the last session's volume, as TradingView's watchlist shows it (the user, 2026-10-31: "lets add volume to the watchlist")
  const fmtVol = (v) => (v == null ? '' : v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M`
    : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : String(Math.round(v)));

  function compare(a, b) {
    const k = sort.key;
    const va = k === 'symbol' ? a.sym.ticker : k === 'last' ? a.q.last : k === 'vol' ? a.q.vol : a.q.pct;
    const vb = k === 'symbol' ? b.sym.ticker : k === 'last' ? b.q.last : k === 'vol' ? b.q.vol : b.q.pct;
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * sort.dir;
  }

  // A row: − at its left, shown while the pointer is on the row (the user, 2026-10-31: "lets keep the
  // minuses under the arrow", "Hidden until hover"), the symbol, its last price, change and volume.
  function row(entry) {
    const { sym, q } = entry;
    const on = sym.ticker === state.ticker;
    return `<tr class="${on ? 'on' : ''}" data-ticker="${esc(sym.ticker)}" title="${esc(sym.name || sym.ticker)}${sym.exchangeName ? ` · ${esc(sym.exchangeName)}` : ''}">
      <td class="w-x"><button type="button" data-remove="${esc(sym.ticker)}" title="Remove ${esc(sym.ticker)} from this list" aria-label="Remove ${esc(sym.ticker)}">−</button></td>
      <td class="w-sym">${symbolIcon(sym, 18)}<span><b>${esc(sym.ticker)}</b>${q.live ? '<span class="w-live" title="Streaming live"></span>' : ''}
        <span class="w-ex">${esc(sym.exchange || sym.asset || '')}</span></span></td>
      <td class="num">${fmtPrice(q.last)}</td>
      <td class="num ${q.pct == null ? '' : q.pct >= 0 ? 'up' : 'down'}">${fmtPct(q.pct)}</td>
      <td class="num w-vol" title="The last session's volume">${fmtVol(q.vol)}</td>
    </tr>`;
  }

  // The map of a list: stocks by sector and industry, the other classes in groups of their own (futures
  // by family and type), each tile coloured by its move (live where it streams, as the table's).
  function mapGroup(sym) {
    const M = window.MarketMap;
    if (sym.asset === 'stock') return [sym.sector || 'Not classified yet', sym.industry || ''];
    if (sym.asset === 'future') return [`Futures · ${M.futuresFamily(sym.futuresType)}`, M.futuresTypeName(sym.futuresType)];
    return [{ index: 'Indices', fx: 'Currencies', crypto: 'Crypto' }[sym.asset] || 'Other', ''];
  }

  function renderMap(box, head, syms, empty) {
    const M = window.MarketMap;
    if (!syms.length) {  // no blank map: why it is empty, and the market's map to pick from
      box.innerHTML = `${head}<div class="w-map-empty p-muted">${esc(empty)}
        <button type="button" id="watchPick" title="The symbol picker's map: every Nasdaq and NYSE company by exchange and sector">Pick from the market map</button></div>`;
      $('watchList').value = current;
      mapDrawn = Date.now();
      return;
    }
    const items = syms.map((sym) => {
      const q = quote(sym), [group, kind] = mapGroup(sym);
      return { ticker: sym.ticker, name: sym.name, icon: sym.icon, asset: sym.asset, sector: group, industry: kind,
        marketCap: sym.marketCap, dollarVolume: sym.market?.dollarVolume ?? null, changePct: q.pct, close: q.last };
    });
    const volumes = items.map((s) => s.dollarVolume).filter((v) => v > 0).sort((a, b) => a - b);
    const median = volumes.length ? volumes[Math.floor(volumes.length / 2)] : 1;
    const size = items.length <= MAP_EQUAL ? () => 1 : (s) => (s.asset === 'stock' ? s.dollarVolume || 0 : median);
    box.innerHTML = `${head}<div id="watchMap" class="market-map watch-map" role="listbox" aria-label="Watchlist map"></div>
      <div class="map-foot"><span class="map-legend">${[-3, -1, 0, 1, 3].map((p) => `<span style="background:${M.changeColor(p)}">${p > 0 ? '+' : ''}${p}%</span>`).join('')}</span>
        <span class="p-muted small">${items.length.toLocaleString()} · ${items.length <= MAP_EQUAL ? 'equal tiles' : 'stocks by dollar volume'} · by sector</span></div>`;
    $('watchList').value = current;
    const el = $('watchMap');
    if (el.clientWidth) M.render(el, items, { current: state.ticker, levels: [(s) => s.sector, (s) => s.industry], size });
    mapDrawn = Date.now();
  }

  let shownHead = null;  // the panel's head (list, sort, filter) as last drawn

  // Adding and removing, TradingView's way (the user, 2026-10-31: "i need away to add and get rid of
  // watchlist items", "lets use the tradingview way", "a plus at the top and minus next to each entry"):
  // + at the top opens a search of the symbols collected here, a click (or Enter) adds one to the list
  // shown, and the search stays open for the next; − on each row takes it off.
  let adding = false;
  let addQuery = '';

  function addHits() {
    const q = addQuery.trim().toUpperCase();
    const syms = state.symbols || [];
    if (!q) return state.ticker ? syms.filter((s) => s.ticker === state.ticker) : [];  // the open symbol first
    const score = (s) => (s.ticker === q ? 0 : s.ticker.startsWith(q) ? 1 : s.ticker.includes(q) ? 2
      : (s.name || '').toUpperCase().includes(q) ? 3 : 9);
    return syms.map((s) => [score(s), s]).filter(([k]) => k < 9)
      .sort((a, b) => a[0] - b[0] || a[1].ticker.localeCompare(b[1].ticker)).slice(0, 30).map(([, s]) => s);
  }

  function fillAdd() {
    const list = document.querySelector('#pWatch .w-addlist');
    if (!list) return;
    const mine = shownList();
    const hits = addHits();
    list.innerHTML = hits.length ? hits.map((s) => {
      const has = mine.tickers.includes(s.ticker);
      return `<button type="button" class="w-add-hit" data-add="${esc(s.ticker)}"${has ? ' disabled' : ''}
          title="${esc(has ? `${s.ticker} is on ${mine.name}` : `Add ${s.ticker} to ${mine.name}`)}">
        ${symbolIcon(s, 16)}<b>${esc(s.ticker)}</b><span class="w-add-name">${esc(s.name || '')}</span>
        <span class="w-ex">${esc(s.exchange || s.asset || '')}</span><span class="w-add-mark">${has ? '✓' : '+'}</span></button>`;
    }).join('') : `<div class="p-muted small w-add-hint">${addQuery.trim() ? 'No symbol collected here matches.' : 'Type a ticker or a company name.'}</div>`;
  }

  function openAdd(focus = true) {
    const input = $('watchAddInput');
    if (!input) return;
    input.value = addQuery;
    fillAdd();
    if (focus) input.focus();
  }

  function addSymbol(ticker) {
    const mine = shownList();
    if (!mine.tickers.includes(ticker)) mine.tickers.push(ticker);
    prefs.set('watchlist', current);
    shownHead = null;  // drawn whole: the search still open
    return save();
  }

  const addHead = (mine) => `<button type="button" id="watchAdd" aria-expanded="${adding}"
      title="${esc(`Add a symbol to ${mine.name}`)}">+</button>`;
  const addBox = () => (adding ? `<div class="w-addbox"><input id="watchAddInput" type="search" placeholder="Add a symbol: ticker or company"
      autocomplete="off" spellcheck="false" aria-label="Add a symbol"><div class="w-addlist" role="listbox"></div></div>` : '');

  function render() {
    if (!shown()) return;
    const box = $('pWatch');
    const bySym = new Map((state.symbols || []).map((s) => [s.ticker, s]));
    const q = query.trim().toUpperCase();
    const match = (s) => !q || s.ticker.includes(q) || (s.name || '').toUpperCase().includes(q) || (s.exchange || '').includes(q);
    const mine = shownList();
    const th = (key, label, cls = '') => `<th class="${cls}" data-sort="${key}">${label}${sort.key === key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`;
    const options = [...lists.map((l) => `<option value="${esc(l.name)}">${esc(l.name)} (${l.tickers.length})</option>`),
      '<option value="__new__">New list…</option>'].join('');
    const toggle = `<button type="button" id="watchView" title="${view === 'map' ? 'Show the list as a table' : 'Show the list as a heat map, by sector'}"
      aria-pressed="${view === 'map'}">${view === 'map' ? 'List' : 'Map'}</button>`;
    const empty = !mine.tickers.length ? 'Empty: press + to add a symbol.'
      : state.symbolsLoaded ? 'Nothing matches.' : 'Loading the symbols…';
    if (view === 'map') {
      const syms = mine.tickers.map((t) => bySym.get(t)).filter(Boolean);
      const head = `<h3 class="w-head">Watchlist <select id="watchList" aria-label="Watchlist">${options}</select>${toggle}
          ${addHead(mine)}</h3>${addBox()}
        <input id="watchFilter" type="search" placeholder="Filter symbols" value="${esc(query)}" autocomplete="off">`;
      shownHead = null;  // the table is drawn whole when it comes back
      // an empty list (the user, 2026-10-29: "even empty watch list"): said as the table says it
      renderMap(box, head, syms.filter(match), empty);
      if (adding) openAdd(false);
      return;
    }
    const entries = mine.tickers.map((t) => bySym.get(t)).filter((s) => s && match(s)).map((sym) => ({ sym, q: quote(sym) }));
    if (sort.key !== 'order') entries.sort(compare);
    const body = entries.length ? `<tbody>${entries.map(row).join('')}</tbody>`
      : `<tbody><tr><td colspan="5" class="p-muted w-empty">${empty}</td></tr></tbody>`;
    const head = `<h3 class="w-head">Watchlist
        <select id="watchList" aria-label="Watchlist">${options}</select>${toggle}
        ${addHead(mine)}<button type="button" id="watchDelete" title="Delete this list">🗑</button></h3>${addBox()}
      <input id="watchFilter" type="search" placeholder="Filter symbols" value="${esc(query)}" autocomplete="off">
      <div class="table-wrap w-wrap"><table class="w-table">
        <thead><tr><th class="w-x"></th>${th('symbol', 'Symbol')}${th('last', 'Last', 'num')}${th('pct', 'Chg%', 'num')}${th('vol', 'Vol', 'num')}</tr></thead>`;
    const table = box.querySelector('.w-table');
    if (table && shownHead === head) {  // the same list, sort and filter: new rows only
      table.querySelectorAll('tbody').forEach((t) => t.remove());
      table.insertAdjacentHTML('beforeend', body);
      return;
    }
    shownHead = head;
    box.innerHTML = `${head}${body}</table></div>`;
    $('watchList').value = mine.name;
    if (adding) openAdd(document.activeElement === document.body || !document.activeElement);
  }

  // A light refresh of prices without losing the filter's focus.
  function refresh() {
    if (!shown()) return;
    if (document.activeElement?.id === 'watchAddInput') return;  // searching to add: the prices wait
    if (view === 'map' && Date.now() - mapDrawn < MAP_REDRAW_MS && document.activeElement?.id !== 'watchFilter') return;
    const focused = document.activeElement?.id === 'watchFilter';
    const at = focused ? $('watchFilter').selectionStart : null;
    const scroll = document.querySelector('#pWatch .w-wrap')?.scrollTop;
    render();
    if (scroll != null) { const w = document.querySelector('#pWatch .w-wrap'); if (w) w.scrollTop = scroll; }
    if (focused) { const f = $('watchFilter'); f.focus(); f.setSelectionRange(at, at); }
  }

  $('pWatch').addEventListener('input', (e) => {
    if (e.target.id === 'watchAddInput') { addQuery = e.target.value; fillAdd(); return; }
    if (e.target.id !== 'watchFilter') return;
    query = e.target.value;
    refresh();
  });
  $('pWatch').addEventListener('change', async (e) => {
    if (e.target.id !== 'watchList') return;
    if (e.target.value === '__new__') {
      const name = (window.prompt('Name of the new list') || '').trim().slice(0, 40);
      if (name && !lists.some((l) => l.name === name)) {
        lists.push({ name, tickers: [] });
        current = name;
        prefs.set('watchlist', current);
        await save();
        return;
      }
      shownHead = null;  // cancelled, or a name in use: drawn whole, the picker back on the list shown
    } else {
      current = e.target.value;
      prefs.set('watchlist', current);
    }
    render();
  });
  $('pWatch').addEventListener('click', async (e) => {
    if (e.target.closest('#watchView')) {
      view = view === 'map' ? 'list' : 'map';
      prefs.set('watchView', view);
      return render();
    }
    const tile = e.target.closest('.map-tile[data-ticker]');
    if (tile) { window.dispatchEvent(new CustomEvent('massive:open-symbol', { detail: tile.dataset.ticker })); return; }
    if (e.target.closest('#watchPick')) {  // the picker on Nasdaq & NYSE's map (app.js)
      state.switcherScope = 'stocks';
      state.switcherView = 'map';
      prefs.set('switcherScope', 'stocks');
      prefs.set('switcherView', 'map');
      return $('symbolBtn').click();
    }
    const sortBy = e.target.closest('th[data-sort]');
    if (sortBy) {
      sort = { key: sortBy.dataset.sort, dir: sort.key === sortBy.dataset.sort ? -sort.dir : 1 };
      prefs.set('watchSort', sort);
      return render();
    }
    const mine = shownList();
    if (e.target.closest('#watchAdd')) {
      adding = !adding;
      addQuery = '';
      shownHead = null;
      render();
      if (adding) openAdd();
      return;
    }
    const hit = e.target.closest('button[data-add]');
    if (hit) return addSymbol(hit.dataset.add);
    if (e.target.closest('#watchDelete') && window.confirm(`Delete the list "${mine.name}"?`)) {
      lists = lists.filter((l) => l !== mine);
      shownList();  // the first left, or an empty Watchlist
      prefs.set('watchlist', current);
      return save();
    }
    const remove = e.target.closest('button[data-remove]');
    if (remove) {
      mine.tickers = mine.tickers.filter((t) => t !== remove.dataset.remove);
      return save();
    }
    const item = e.target.closest('tr[data-ticker]');
    if (item) window.dispatchEvent(new CustomEvent('massive:open-symbol', { detail: item.dataset.ticker }));
  });

  $('pWatch').addEventListener('keydown', (e) => {
    if (e.target.id !== 'watchAddInput') return;
    if (e.key === 'Escape') {
      e.stopPropagation();
      adding = false;
      shownHead = null;
      render();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const first = document.querySelector('#pWatch .w-add-hit:not([disabled])');
      if (first) addSymbol(first.dataset.add);
    }
  });

  window.addEventListener('massive:view', (e) => { if (e.detail?.pane === 'watchlist') render(); });
  window.addEventListener('massive:symbols', refresh);  // the symbols arrived: the list's rows
  window.addEventListener('massive:symbol', refresh);
  window.addEventListener('massive:activity', refresh);  // live prices with every activity poll
  window.Watchlist = { render, load, lists: () => lists };  // the lists: the symbol picker maps them too
  load();
})();

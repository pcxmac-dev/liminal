'use strict';
/* Plugins view (rail icon: a plug): every data provider plugin, a feed or source (gui/plugins.py).
   On the left the plugins, those with keys and the public ones, each with its state and its plan;
   in the middle the one picked: its plan and where that came from (set by you, found by its scan,
   the default), its limits, what it can do on that plan, its live streams and its last capability
   scan with a Rescan; on the right its part in the delivery scheme (the eras it delivers or stands
   by for), its requests today, the symbols it watches, its keys (set or not, never their values),
   its version, the plugin API it was written for and where it came from (built in, or a package).
   Each plugin refreshes its own plan info: a rescan asks the provider what the key really gets;
   while it runs, each plugin it has still to ask says "scanning" in place of its state.
   A plugin with several feeds (Alpaca: alpaca, and its nights on Blue Ocean, alpaca (blue ocean);
   Tiingo: tiingo and tiingo (forex)) lists them, and names the feed on each capability, scan answer
   and era.
   A plan its scan cannot tell (Tiingo's Power from Commercial) is chosen here: each plan variable
   is a choice, saved like the key script saves it (POST /api/plugins/plan); keys stay in the script.
   Below them the publishers (news and publications: publications.py), each an agency's or a
   vendor's plugin: its feeds with their last and next reads, its release schedule, its scrape
   checks, its limits as last verified with a Recheck, and a Pause. A publisher part of a plugin
   (Massive's headlines, Federal's agencies) is no entry of its own: a section of its plugin's page,
   opened in place (the user, 2026-10-31: "massive headlines should not be separate from massive
   same thing with federal agencies and federal").
   Every plugin is set up here (Setup): each variable it reads, a key or a detail of yours it sends
   (GOV_CONTACT), set or not (never its value), typed and saved as your user environment variable
   (POST /api/plugins/key), or removed. What is typed is sent once and the field cleared.
   Asked again every minute while shown, every few seconds while a rescan or recheck runs. */
(() => {
  const box = document.getElementById('viewPlugins');
  const { esc, safeUrl } = window.MassiveIcons;
  let data = null, sel = null, note = '', timer = null;
  const folds = new Map();  // a part's section opened or closed by hand (by its name); else open when alone

  const STATE = { ready: 'ready', scanning: 'scanning…', partly: 'keys not set', 'no key': 'no key', killed: 'killed', paused: 'paused',
                  refused: 'refused', failing: 'failing', waiting: 'waiting', off: 'not set up' };
  const FEED_STATE = { ok: 'read', unchanged: 'unchanged', waiting: 'waiting', failed: 'failed', refused: 'refused',
                       'not asked yet': 'not asked yet' };
  const PUB = 'pub:';  // a publisher's id in the list (its name may be a feed's too)
  const ORIGIN = { you: 'set by you', scan: 'found by its scan', default: 'default' };
  const JOBS = { day: 'daily bars', minute: '1-minute', second: '1-second' };
  const num = (n) => (n == null ? '–' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 1 }));
  const ago = (iso) => {
    if (!iso) return 'never';
    const h = (Date.now() - Date.parse(iso)) / 36e5;
    return h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago`;
  };
  const rate = (r) => {
    if (!r || !r[0]) return 'no limit';
    const [n, s] = r;
    return Math.abs(s - 3600) < 120 ? `${num(n)} an hour` : Math.abs(s - 60) < 5 ? `${num(n)} a minute` : `${num(n)} per ${num(s)} s`;
  };
  const days = (d) => (d < 1 / 24 ? 'under an hour' : d < 1 ? `${(d * 24).toFixed(1)} h` : `${num(d)} days`);
  const chip = (state) => `<span class="ex-state pl-${esc(state.replace(' ', '-'))}">${esc(STATE[state] || state)}</span>`;
  const tile = (title, big, small) => `<div class="tile"><h5>${title}</h5><div class="big">${big}</div><small>${small}</small></div>`;
  const plugin = () => data?.plugins.find((p) => p.name === sel) || null;
  const publisher = () => (sel?.startsWith(PUB) ? data?.publishers?.find((p) => PUB + p.name === sel && !parentOf(p)) || null : null);
  const pubNamed = (name) => (data?.publishers || []).find((q) => q.name === name) || null;
  // a plugin's parts: a feed plugin's publishers (Massive's headlines), a publisher's (Federal's agencies)
  const partsOf = (p) => (p.parts || p.publishers || []).map(pubNamed).filter(Boolean);
  const etTime = (iso) => new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' });
  const etDay = (iso) => new Date(iso).toLocaleDateString('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric' });
  const until = (iso) => {
    if (!iso) return '–';
    const m = (Date.parse(iso) - Date.now()) / 6e4;
    return m <= 1 ? 'now' : m < 90 ? `in ${Math.round(m)} min` : m < 48 * 60 ? `in ${(m / 60).toFixed(1)} h` : `in ${Math.round(m / 1440)} days`;
  };
  const every = (m) => (m >= 60 ? `${num(m / 60)} h` : `${num(m)} min`);
  const tierOf = (p) => p.plan.vars.find((v) => v.choices.length) || null;
  // a plugin's version, the plugin API it was written for and where it came from
  const release = (p) => `<div class="p-muted small pl-release">Version ${esc(p.version || 'unversioned')} · plugin API ${esc(p.api)} · ${esc(p.origin)}</div>`;
  // a publisher that puts out datasets only (Ken French's library, Datahub's mirrors; the CFTC)
  const setsOnly = (p) => !p.feeds.length && !p.parts.length && p.datasets.length > 0;
  const SOURCE = { research: "a researcher's own datasets", mirror: 'datasets mirrored from their sources', official: "an agency's datasets" };
  const pubKind = (p) => (p.kind === 'vendor' ? `a vendor's headlines, on ${p.account}'s key`
    : setsOnly(p) ? SOURCE[p.kind] || `${p.kind} datasets` : 'official feeds');
  // what a publisher reads: a plugin of several (Federal) its agencies, a vendor's on its feed's key, its feeds, its datasets
  const pubCount = (p) => (p.parts.length ? `${p.parts.length} agencies`
    : p.kind === 'vendor' ? `on ${p.account}'s key · every ${every(Math.min(...p.feeds.map((f) => f.every)))}`
      : p.feeds.length ? `${p.feeds.length} feed${p.feeds.length === 1 ? '' : 's'} · every ${every(Math.min(...p.feeds.map((f) => f.every)))}`
        : p.datasets.length ? `${p.datasets.length} dataset${p.datasets.length === 1 ? '' : 's'}` : 'nothing to read');

  async function load() {
    clearTimeout(timer);
    if (document.body.dataset.view !== 'plugins' || document.hidden) return;
    try {
      data = await api('/api/plugins');
      const part = sel?.startsWith(PUB) ? pubNamed(sel.slice(PUB.length)) : null;
      const up = part && parentOf(part);  // a part picked: its plugin's page, its section open
      if (up) { folds.set(part.name, true); sel = up.id; }
      if (!sel || !(data.plugins.some((p) => p.name === sel) || publisher())) sel = data.plugins[0]?.name || null;
    } catch (err) { showError(err); }
    render();
    timer = setTimeout(load, data?.running || data?.rechecking ? 4_000 : 60_000);
  }

  async function rescan(name) {
    note = '';
    try {
      const q = name ? `?name=${encodeURIComponent(name)}` : '';
      const res = await fetch(`/api/plugins/rescan${q}`, { method: 'POST', headers: { 'X-Massive-Charts': '1' } });
      const out = await res.json().catch(() => ({}));
      note = res.ok ? `Rescan started: ${name ? plugin()?.title || name : 'every plugin set up here'} (a few requests each).`
        : out.error || res.statusText;
    } catch (err) { note = String(err.message || err); }
    render();
    setTimeout(load, 1_000);
  }

  async function choosePlan(select) {
    const p = data.plugins.find((x) => x.name === select.dataset.planPlugin);
    const variable = select.dataset.var, value = select.value || null;
    const ask = value
      ? `Use ${variable}=${value}? ${p.title} will keep to that plan's limits, in the app and the sync: choose only the plan you pay for.`
      : `Let ${p.title}'s scan or its default decide ${variable} again?`;
    if (!window.confirm(ask)) { render(); return; }
    note = '';
    try {
      const res = await fetch('/api/plugins/plan', { method: 'POST', headers: WRITE_HEADERS,
        body: JSON.stringify({ plugin: p.name, variable, value }) });
      const out = await res.json().catch(() => ({}));
      note = res.ok ? `${variable} ${value ? `set to ${value}` : 'left to its scan or default'}: the app uses it now, the sync from its next run.`
        : out.error || res.statusText;
    } catch (err) { note = String(err.message || err); }
    await load();
  }

  async function post(path, done) {
    note = '';
    try {
      const res = await fetch(path, { method: 'POST', headers: WRITE_HEADERS, body: '{}' });
      const out = await res.json().catch(() => ({}));
      note = res.ok ? done : out.error || res.statusText;
    } catch (err) { note = String(err.message || err); }
    render();
    setTimeout(load, 1_000);
  }

  async function saveKey(owner, variable, value) {
    note = '';
    try {
      const res = await fetch('/api/plugins/key', { method: 'POST', headers: WRITE_HEADERS,
        body: JSON.stringify({ plugin: owner, variable, value }) });
      const out = await res.json().catch(() => ({}));
      const scans = data.plugins.find((x) => x.name === owner)?.scan.has;
      note = res.ok ? (value == null ? `${variable} removed from your user environment variables.`
        : `${variable} saved in your user environment variables: the app uses it now, the sync from its next run${
          scans ? '; Rescan to see what it gets' : ''}.`) : out.error || res.statusText;
    } catch (err) { note = String(err.message || err); }
    await load();
  }

  // -- setup: what each plugin reads that you set ------------------------------------------------
  // each variable set or not (never its value); a key typed hidden, a detail of yours in the open
  function setupHtml(owner, keys, account) {
    const off = data.offline ? ' disabled title="This offline copy of the app saves no settings"' : '';
    const rows = keys.map((k) => `<tr data-key-row="${esc(k.name)}">
        <td><code>${esc(k.name)}</code><div class="p-muted small">${esc(k.label)}</div></td>
        <td>${k.set ? '<span class="up">set</span>' : '<span class="down">not set</span>'}</td>
        <td><input class="pl-key" type="${k.secret ? 'password' : 'text'}" data-var="${esc(k.name)}" autocomplete="off" spellcheck="false"
          maxlength="512" placeholder="${esc(k.hint || (k.set ? 'type a new one to replace it' : `your ${k.label}`))}"${off}></td>
        <td class="pl-key-btns"><button type="button" data-save-key="${esc(k.name)}" data-owner="${esc(owner)}"${off}>${k.set ? 'Replace' : 'Save'}</button>
          ${k.set ? `<button type="button" data-remove-key="${esc(k.name)}" data-owner="${esc(owner)}"${off}>Remove</button>` : ''}</td></tr>`).join('');
    const where = account ? `It reads on ${esc(account.title)}'s key: <button type="button" class="pl-link" data-plugin="${esc(account.id)}">set it up there</button>.` : '';
    if (!rows) return `<h4>Setup</h4><div class="p-muted small">${where || 'Nothing to set: it needs no key and nothing of yours.'}</div>`;
    return `<h4>Setup</h4><table class="act-table ex-mini pl-setup"><tbody>${rows}</tbody></table>
      <div class="p-muted small">Saved as your user environment variables, where the key script saves them: the app uses them at once,
        the sync from its next run. A value is never shown back, only whether it is set.${where ? ` ${where}` : ''}</div>`;
  }

  // -- left: the plugins ---------------------------------------------------------------------
  function listHtml() {
    // each plugin once: its parts (Massive's headlines, Federal's agencies) are sections of its page
    const pubButton = (p) => `<button type="button" class="ex-venue${PUB + p.name === sel ? ' active' : ''}" data-plugin="${esc(PUB + p.name)}" title="${esc(p.about)}">
          <span class="ex-name">${esc(p.title)}</span>${chip(p.state)}
          <span class="ex-count">${esc(pubCount(p))}</span></button>`;
    const groups = data.groups.map((g) => {
      const ps = data.plugins.filter((p) => p.group === g);
      if (!ps.length) return '';
      return `<h4 class="ex-group">${esc(g)}</h4>` + ps.map((p) => {
        const t = tierOf(p);
        const plan = t ? `${t.value} · ${ORIGIN[t.origin]}` : p.plan.tier;
        const parts = partsOf(p);
        const also = parts.length ? ` · ${parts.every((q) => q.kind === 'vendor') ? 'headlines' : `${parts.length} publishers`}` : '';
        return `<button type="button" class="ex-venue${p.name === sel ? ' active' : ''}" data-plugin="${esc(p.name)}" title="${esc(p.about)}">
          <span class="ex-name">${esc(p.title)}</span>${chip(p.state)}
          <span class="ex-count">${esc(plan)}${p.feeds.length > 1 ? ` · ${p.feeds.length} feeds` : ''}${esc(also)}</span></button>`;
      }).join('');
    }).join('');
    const top = (data.publishers || []).filter((p) => !parentOf(p));
    const pubs = top.filter((p) => !setsOnly(p)).map(pubButton).join('');
    const sets = top.filter(setsOnly).map(pubButton).join('');
    const news = (pubs ? `<h4 class="ex-group">News and publications</h4>${pubs}` : '')
      + (sets ? `<h4 class="ex-group">Datasets</h4>${sets}` : '');
    const left = data.errors.length ? `<h4 class="ex-group">Left out</h4>${data.errors.map((e) => `
      <div class="pl-error"><b>${esc(e.where)}</b><div class="p-muted small">${esc(e.why)}</div></div>`).join('')}` : '';
    return groups + news + left;
  }

  // -- middle: the plugin picked -------------------------------------------------------------
  // a plan variable with choices is a choice: "automatic" leaves it to the scan or the default
  function planCell(p, v) {
    if (!v.choices.length) return `<b>${esc(v.value ?? '–')}</b>`;
    const found = p.plan.found?.[v.name];
    const auto = `automatic: ${found || v.choices[0]} (${found ? 'its scan' : 'the default'})`;
    const mine = v.origin === 'you';
    return `<select class="pl-choose" data-plan-plugin="${esc(p.name)}" data-var="${esc(v.name)}"${data.offline
      ? ' disabled title="This offline copy of the app saves no settings"' : ''}>
        <option value=""${mine ? '' : ' selected'}>${esc(auto)}</option>
        ${v.choices.map((c) => `<option value="${esc(c)}"${mine && v.value === c ? ' selected' : ''}>${esc(c)}</option>`).join('')}
      </select>`;
  }

  function planHtml(p) {
    const name = p.name;
    const rows = p.plan.vars.map((v) => `<tr><td><code>${esc(v.name)}</code></td><td>${planCell(p, v)}</td>
        <td class="pl-origin pl-${esc(v.origin)}">${esc(ORIGIN[v.origin])}</td></tr>`).join('');
    const differs = p.plan.differs.map((d) => `<div class="pl-warn">Your <code>${esc(d.name)}</code> is <b>${esc(d.yours)}</b>,
        but its scan found <b>${esc(d.found)}</b>. Yours is used; change it if the scan is right.</div>`).join('');
    const found = Object.entries(p.plan.found || {});
    return `<h4>Plan</h4>
      ${rows ? `<table class="act-table ex-mini pl-plan"><thead><tr><th>Variable</th><th>Plan</th><th>From</th></tr></thead><tbody>${rows}</tbody></table>`
        : `<div class="p-muted small">One fixed plan: ${esc(p.plan.tier)}.</div>`}
      ${found.length ? `<div class="p-muted small">Its last scan found ${found.map(([k, v]) => `<code>${esc(k)}=${esc(v)}</code>${
        p.plan.alike?.[k]?.length ? ` (or ${p.plan.alike[k].map(esc).join(', ')}: their answers are the same, so the lower limits are used)` : ''}`).join(', ')}:
        used wherever you have not set it yourself.</div>` : ''}
      ${differs}
      ${p.plan.note ? `<div class="pl-note">${esc(p.plan.note)}.</div>` : ''}
      ${rows ? `<div class="p-muted small">Choose a plan above: it is saved as your user environment variable. Keys are set
        in Setup, or with the key script: <code>${esc(data.keyScript)} ${esc(name)}</code></div>` : ''}`;
  }

  function limitsHtml(p) {
    const l = p.limits;
    if (l.requests_a_day == null) return `<h4>Limits</h4><div class="p-muted small">${esc(l.published || 'Not set up here.')}</div>`;
    return `<h4>Limits</h4><div class="tiles ex-tiles pl-tiles">
        ${tile('Requests a day', num(l.requests_a_day), l.per_day ? `cap ${num(l.per_day)}` : 'its rate allows')}
        ${tile('Rate kept', rate(l.rate), 'a little inside its server\'s')}
        ${tile('A run', num(l.per_run), 'requests at most')}
        ${tile('Symbols a month', l.symbols_a_month ? num(l.symbols_a_month) : 'any', l.symbols_a_month ? 'different symbols' : 'no monthly cap')}
      </div>${l.published ? `<div class="p-muted small">Its server publishes: ${esc(l.published)}</div>` : ''}`;
  }

  // a plugin with several feeds (alpaca, and alpaca (blue ocean) on its keys): each listed by the
  // plugin's name, with its state ("the source isn't blue ocean its alpaca w/ blue ocean")
  const several = (p) => p.feeds.length > 1;
  function feedsHtml(p) {
    if (!several(p)) return '';
    return `<h4>Feeds</h4><table class="act-table ex-mini pl-feedlist"><tbody>${p.feeds.map((f) => `<tr>
        <td><b>${esc(f.label)}</b><div class="p-muted small">${esc(f.about)}</div></td>
        <td>${chip(f.state)}</td></tr>`).join('')}</tbody></table>
      <div class="p-muted small">Each a feed of its own (its own bars, symbols and requests), on this plugin's keys and limits.</div>`;
  }

  // the publishers in a feed plugin (Massive's headlines): sections of its page
  function publishersHtml(p) {
    const pubs = partsOf(p);
    if (!pubs.length) return '';
    return `<h4>${pubs.every((q) => q.kind === 'vendor') ? 'Headlines' : 'Publishers'}</h4>${pubs.map((q) => partHtml(q, pubs.length === 1)).join('')}
      <div class="p-muted small">On this plugin's key and limits; each keeps its own scrape checks, pause and recheck.</div>`;
  }

  function capabilitiesHtml(p) {
    if (!p.capabilities.length) return '';
    const feed = (c) => (several(p) ? `<td>${esc(c.feed)}</td>` : '');
    return `<h4>What it can do on this plan</h4><table class="act-table ex-mini"><thead><tr>${several(p) ? '<th>Feed</th>' : ''}<th>Asset</th><th>Bars</th>
        <th>Market</th><th>From</th><th>Fresh</th><th class="num">A request</th></tr></thead><tbody>
      ${p.capabilities.map((c) => `<tr>${feed(c)}<td>${esc(c.asset)}</td><td>${esc(JOBS[c.resolution] || c.resolution)}</td><td>${esc(c.market)}</td>
        <td>${esc(c.since)}</td><td>${esc(c.fresh)}</td><td class="num">${c.perRequest == null ? 'whole history' : `${num(c.perRequest)} bars`}</td></tr>`).join('')}
      </tbody></table>
      ${p.streams.length ? `<h4>Live</h4>${p.streams.map((s) => `<div class="small"><b>${esc(s.asset)}</b> ${esc(s.what)}</div>`).join('')}` : ''}`;
  }

  function scanHtml(p) {
    if (!p.scan.has) return `<h4>Capability scan</h4><div class="p-muted small">${esc(p.title)} has none: a public feed with one fixed plan.</div>`;
    const can = p.configured && p.state !== 'no key' && !data.offline && !data.running;
    const why = data.offline ? 'This offline copy of the app sends no requests' : !p.configured || p.state === 'no key'
      ? 'Its keys are not set' : data.running ? 'A rescan is running' : 'Ask the provider again what the key gets (a few requests)';
    const rows = p.scan.results.map((r, i) => `${several(p) && r.feed !== p.scan.results[i - 1]?.feed
        ? `<tr class="pl-feedrow"><th colspan="3">${esc(r.feed)}</th></tr>` : ''}<tr><td>${esc(r.what)}</td>
        <td>${r.available ? '<span class="up">yes</span>' : '<span class="down">no</span>'}</td><td class="p-muted">${esc(r.detail)}</td></tr>`).join('');
    return `<h4 class="pl-scan-head"><span>Capability scan</span>
        <button type="button" data-rescan="${esc(p.name)}"${can ? '' : ' disabled'} title="${esc(why)}">${p.scan.running ? 'Scanning…' : 'Rescan'}</button></h4>
      <div class="p-muted small">${p.scan.at ? `Last asked ${ago(p.scan.at)}` : 'Not scanned yet'}: on each start of the app, weekly in the sync, and here${
        several(p) ? ` (its ${p.feeds.length} feeds together)` : ''}.</div>
      ${rows ? `<table class="act-table ex-mini"><tbody>${rows}</tbody></table>` : ''}`;
  }

  // -- a publisher (news and publications) ------------------------------------------------------
  // a plugin of several publishers (Federal): its agencies, sections of its page
  function partsHtml(p) {
    return `<h4>Agencies</h4>${partsOf(p).map((q) => partHtml(q, false)).join('')}
      <div class="p-muted small">Each agency keeps its own scrape checks, limits, pause and recheck: open it for them. Pausing ${esc(p.title)} pauses them all.</div>`;
  }

  // a publisher part of a plugin (Massive's headlines, Federal's agencies): a section of that plugin's
  // page, never an entry of its own; its summary says what it reads and when, opened its feeds,
  // checks, limits, pause and terms (open when it is its plugin's only part, or as you left it)
  function partHtml(q, alone) {
    const last = q.feeds.map((f) => f.at).filter(Boolean).sort().pop();
    const next = q.feeds.map((f) => f.next).filter(Boolean).sort()[0];
    const when = q.feeds.length ? ` · ${last ? `read ${ago(last)}` : 'never read'}${q.state !== 'paused' && next ? ` · next ${until(next)}` : ''}`
      + ` · ${num(q.requestsToday)} requests today` : '';
    const open = folds.has(q.name) ? folds.get(q.name) : alone;
    return `<details class="pl-part" data-part="${esc(q.name)}"${open ? ' open' : ''}>
      <summary><span class="ex-name">${esc(q.title)}</span>${chip(q.state)}<span class="p-muted small">${esc(pubCount(q) + when)}</span></summary>
      <div class="p-muted small">${esc(q.about)}</div>${stopHtml(q)}
      <div class="pl-part-pause">${pauseHtml(q)}</div>
      ${q.feeds.length ? readsHtml(q) : datasetsHtml(q)}${termsHtml(q)}</details>`;
  }

  // the datasets a publisher puts out (the CFTC's Commitments of Traders), as the Datasets view has them
  function datasetsHtml(p) {
    const rows = p.datasetRows || [];
    if (!p.datasets.length) return '';
    return `<h4>Datasets</h4><table class="act-table ex-mini"><thead><tr><th>Dataset</th><th class="num">Values</th><th>Fetched</th><th>Files due</th></tr></thead><tbody>
      ${p.datasets.map((n) => rows.find((r) => r.name === n) || { name: n, title: n }).map((d) => `<tr><td><b>${esc(d.title)}</b><div class="p-muted small">${esc(d.licence || '')}</div></td>
        <td class="num">${d.values != null ? num(d.values) : '–'}</td><td>${d.fetched ? ago(d.fetched) : 'not yet'}</td><td>${d.due != null ? num(d.due) : '–'}</td></tr>`).join('')}</tbody></table>
      <div class="p-muted small">Fetched with the datasets (<code>datasets fetch</code>, then on their own cadence) and shown in the Datasets view;
        their files only from ${p.policy.hosts.map((h) => `<code>${esc(h)}</code>`).join(', ') || 'its hosts'}, over HTTPS.</div>`;
  }

  // the plugin a publisher is part of, as the registry lists it: a publisher (Federal) or a feed
  // plugin (Massive): {id, title}; null for a plugin of its own
  function parentOf(p) {
    if (!p.partOf) return null;
    const pub = (data?.publishers || []).find((q) => (q.parts || []).includes(p.name));
    if (pub) return { id: PUB + pub.name, title: pub.title };
    const feed = (data?.plugins || []).find((q) => (q.publishers || []).includes(p.name));
    return feed ? { id: feed.name, title: feed.title } : null;
  }

  // a publisher's setup: what it reads that you set (its parts' too); a vendor's points at its feed's keys
  function pubSetupHtml(p) {
    const acct = p.kind === 'vendor' ? data.plugins.find((q) => q.name === p.account || q.feeds.some((f) => f.name === p.account)) : null;
    return setupHtml(p.name, p.keys || [], acct ? { id: acct.name, title: acct.title } : null);
  }

  function pubMainHtml(p) {
    if (p.parts.length) return `${(p.keys || []).length ? pubSetupHtml(p) : ''}${partsHtml(p)}`;
    if (!p.feeds.length) {
      return `${datasetsHtml(p)}${p.policy.terms ? `<h4>Terms</h4><div class="small">${esc(p.policy.terms)}</div>` : ''}`;
    }
    return `${pubSetupHtml(p)}${readsHtml(p)}`;
  }

  // what a publisher reads: its feeds with their last and next reads, its schedule, its scrape
  // checks and its limits as last verified with a Recheck (its page, or its section in its plugin's)
  function readsHtml(p) {
    const feeds = p.feeds.map((f) => `<tr><td><b>${esc(f.title)}</b><div class="p-muted small">${esc(f.host || f.agency)}</div></td>
        <td>${esc(every(f.every))}</td><td><span class="pl-fstate pl-f-${esc(f.state.replace(/ /g, '-'))}">${esc(FEED_STATE[f.state] || f.state)}</span></td>
        <td>${f.at ? ago(f.at) : 'never'}</td><td>${p.state === 'paused' ? 'paused' : f.next ? until(f.next) : '–'}</td>
        <td class="p-muted pl-msg">${esc(f.message || '')}</td></tr>`).join('');
    const moments = p.moments.length ? `<div class="small">Today's release reads (ET): ${p.moments.map((m) => esc(etTime(m))).join(' · ')}</div>` : '';
    const cal = p.calendar.length ? `<table class="act-table ex-mini"><tbody>${p.calendar.map((c) => `<tr><td>${esc(etDay(c.when))}</td>
        <td>${esc(etTime(c.when))} ET</td><td>${esc(c.what)}</td></tr>`).join('')}</tbody></table>` : '';
    const pol = p.policy;
    const robots = p.robots.map((r) => `<div class="small"><code>${esc(r.host)}</code> robots.txt: ${r.status == null ? 'not read yet'
      : r.status === 200 ? `read ${ago(r.at)}${r.delayMinutes ? `, asks ${num(r.delayMinutes)} min between requests` : ''}`
      : r.answered ? `none published to this reader (HTTP ${r.status}), read as allowing all · ${ago(r.at)}`
      : `did not answer (${r.status ? `HTTP ${r.status}` : 'no answer'}) ${ago(r.at)}: nothing read from the host until it does`}${r.allows === false ? ' · <span class="down">disallows a feed: not read</span>' : ''}</div>`).join('');
    const checks = [
      pol.hosts.length ? `Only ${pol.hosts.map((h) => `<code>${esc(h)}</code>`).join(', ')}, over HTTPS; a redirect elsewhere is not followed` : `Through ${esc(p.account)}'s client: its rate window, daily cap and kills`,
      `Never these sites, whose terms bar programs: ${pol.blocked.map(esc).join(', ')}`,
      'Feeds and APIs only: an answer that is not XML or JSON is refused, never read as a page',
      `A feed at most every ${esc(every(p.floorMinutes))}${p.floorMinutes > pol.minMinutes ? ` (its hosts ask for that; its own is ${esc(every(pol.minMinutes))})` : ''}, whatever its schedule asks`,
      `At most ${num(pol.perDay)} requests a day, robots.txt included: ${num(p.requestsToday)} today`,
      'Conditional requests (an unchanged feed sends nothing back); a refusal (401, 403, 429) holds the whole publisher off 6 h, or the Retry-After if longer; a Retry-After on any answer is honoured',
      'A crawl-delay its robots.txt asks for is kept between any two requests to that host; a feed that keeps failing is asked less and less often, never more than its schedule',
      pol.contact ? (pol.contactSet ? 'Your GOV_CONTACT goes in its User-Agent, as it asks (to it only)' : 'It asks automated readers to identify: waiting for GOV_CONTACT (your name and email)')
        : 'No contact sent: it does not ask for one',
    ].map((c) => `<li>${c}</li>`).join('');
    const rc = p.recheck;
    const seen = rc?.limitsSeen ? Object.entries(rc.limitsSeen) : [];
    const acct = rc?.account ? `<div class="small">${esc(rc.account.title)}'s limits: ${esc(rate(rc.account.rate))}, ${num(rc.account.perDay)} a day${rc.account.published ? ` (its server: ${esc(rc.account.published)})` : ''}</div>` : '';
    const busy = data.rechecking?.name === p.name;
    const waitingContact = p.policy.contact && !p.policy.contactSet;
    const can = !data.offline && !data.rechecking && !['off', 'paused', 'refused'].includes(p.state) && !p.held && !waitingContact;
    const why = data.offline ? 'This offline copy of the app sends no requests'
      : waitingContact ? 'Nothing is sent to it until GOV_CONTACT is set'
      : p.state === 'paused' || p.state === 'refused' || p.held ? 'Nothing is sent to it while it is paused, stopped or held'
      : 'Read its robots.txt again (unless read within the hour) and ask each feed once (never within its floor, refused or held), keeping the rate-limit headers its servers send; pressed again within 15 min it sends nothing';
    const err = p.error ? `<div class="pl-warn">Its plugin failed here: ${esc(p.error)}</div>` : '';
    return `${err}<h4>Feeds</h4><table class="act-table ex-mini pl-feeds"><thead><tr><th>Feed</th><th>Every</th><th>State</th><th>Last read</th><th>Next</th><th></th></tr></thead>
        <tbody>${feeds}</tbody></table>
      ${moments || cal ? `<h4>Schedule</h4>${moments}${cal}` : ''}
      <h4>Scrape checks</h4><ul class="pl-checks small">${checks}</ul>${robots}
      <h4 class="pl-scan-head"><span>Limits, verified</span>
        <button type="button" data-recheck="${esc(p.name)}"${can ? '' : ' disabled'} title="${esc(why)}">${busy ? 'Rechecking…' : 'Recheck'}</button></h4>
      <div class="p-muted small">${rc ? `Last verified ${ago(rc.at)}` : 'Not verified yet'}: weekly, and here.</div>
      ${acct}${(rc?.notes || []).map((n) => `<div class="small">${esc(n)}</div>`).join('')}
      ${seen.length ? `<table class="act-table ex-mini"><tbody>${seen.map(([k, h]) => `<tr><td>${esc(k)}</td><td class="p-muted">${
        esc(Object.entries(h).filter(([n]) => n !== 'at').map(([n, v]) => `${n}: ${v}`).join(' · '))}</td></tr>`).join('')}</tbody></table>` : ''}`;
  }

  // why nothing is sent for a publisher now: its own pause or kill, its plugin's (Federal's, for an
  // agency), its account's (a vendor's feed refused), fetching paused; or held off after a refusal
  function stopHtml(p) {
    const whose = p.kill?.whose;
    const plugin = parentOf(p);  // Federal, for its agencies; Massive, for its headlines
    const at = (iso) => esc(String(iso || '').slice(0, 16).replace('T', ' '));
    const stop = !p.kill ? ''
      : p.state === 'paused' && whose === 'own' ? 'Paused by you'
      : whose === 'plugin' ? `${p.kill.by === 'user' ? 'Paused' : 'Stopped'} with ${esc(plugin?.title || p.partOf)}: ${p.kill.by === 'user' ? 'Resume all resumes it' : esc(p.kill.why)}`
      : whose === 'fetching' ? `${esc(p.kill.why)}: resume fetching there`
      : whose === 'account' ? `Stopped with ${esc(p.account)}'s account until ${at(p.kill.until)} UTC: ${esc(p.kill.why)}`
      : `Stopped until ${at(p.kill.until)} UTC: ${esc(p.kill.why)}`;
    return `${stop ? `<div class="pl-warn">${stop}</div>` : ''}${p.held ? `<div class="pl-warn">Nothing sent until ${at(p.held.until)} UTC: ${esc(p.held.why)}</div>` : ''}`;
  }

  // its Pause: a plugin of several (Federal) pauses every part; a part (an agency, the headlines) itself
  function pauseHtml(p) {
    const paused = p.state === 'paused' && p.kill?.whose === 'own';  // its own pause: Resume undoes it here
    const all = p.parts.length > 0;
    const sets = setsOnly(p);
    return `<button type="button" data-pause="${esc(p.name)}" data-on="${paused ? '0' : '1'}"${data.offline || (p.kill && !paused) ? ' disabled' : ''}>${paused ? (all ? 'Resume all' : 'Resume') : (all ? 'Pause all' : 'Pause')}</button>
      <div class="p-muted small">${paused ? `Nothing is ${sets ? 'fetched' : 'read'} until you resume it.` : all ? 'Pausing it stops every agency in it until you resume it.'
        : sets ? 'Pausing stops its datasets being fetched until you resume it.' : 'Pausing stops its reads until you resume it.'}</div>`;
  }

  const termsHtml = (p) => `${p.policy.terms ? `<h4>Terms</h4><div class="small">${esc(p.policy.terms)}</div>` : ''}
      ${safeUrl(p.policy.termsUrl) ? `<div class="p-muted small"><a href="${esc(safeUrl(p.policy.termsUrl))}" target="_blank" rel="noopener noreferrer">${esc(p.policy.termsUrl.replace(/^https:\/\//, ''))}</a></div>` : ''}`;

  function pubSideHtml(p) {
    const used = p.policy.perDay ? Math.min(100, (p.requestsToday / p.policy.perDay) * 100) : 0;
    const all = p.parts.length > 0;  // a plugin of several: its pause is theirs too
    const sets = setsOnly(p) ? (p.datasetRows || []) : null;  // a library of datasets: what it holds here
    const fetched = sets && sets.map((d) => d.fetched).filter(Boolean).sort().pop();
    const tiles = sets ? `${tile('Datasets', num(p.datasets.length), 'fetched with datasets fetch')}
        ${tile('Values', num(sets.reduce((n, d) => n + (d.values || 0), 0)), 'kept here')}
        ${tile('Fetched', fetched ? ago(fetched) : 'not yet', 'then on their own cadence')}`
      : `${tile('Requests today', num(p.requestsToday), all ? 'its agencies together' : `of ${num(p.policy.perDay)} a day`)}
        ${all ? tile('Agencies', num(p.parts.length), 'each a part of it') : tile('Floor', every(p.floorMinutes), 'between reads of a feed')}
        ${tile('Feeds', num(all ? partsOf(p).reduce((n, q) => n + q.feeds.length, 0) : p.feeds.length),
          p.kind === 'vendor' ? `on ${esc(p.account)}'s key` : 'official, keyless')}
        ${all ? '' : tile('Verified', p.recheck ? ago(p.recheck.at) : 'never', 'its limits')}`;
    return `<h3>${esc(p.title)} ${chip(p.state)}</h3>
      <div class="p-muted small">${esc(p.about)}</div>${release(p)}
      ${stopHtml(p)}
      <div class="tiles ex-tiles">
        ${tiles}
      </div>
      ${all || sets ? '' : `<div class="pl-usage" title="${num(p.requestsToday)} of ${num(p.policy.perDay)} requests today"><i style="width:${used.toFixed(1)}%"></i></div>`}
      <h4>${sets ? 'Fetching' : 'Reading'}</h4>
      ${pauseHtml(p)}
      ${termsHtml(p)}`;
  }

  function mainHtml() {
    const pub = publisher();
    if (pub) return pubMainHtml(pub);
    const p = plugin();
    if (!p) return '<div class="empty">No plugin found.</div>';
    return `${setupHtml(p.name, p.keys)}${feedsHtml(p)}${planHtml(p)}${limitsHtml(p)}${capabilitiesHtml(p)}${scanHtml(p)}
      ${p.notes.length ? `<h4>Notes</h4>${p.notes.map((n) => `<div class="small">${esc(n)}</div>`).join('')}` : ''}${publishersHtml(p)}`;
  }

  // -- right: its part in the delivery scheme, its usage, its keys ---------------------------
  function sideHtml() {
    const pub = publisher();
    if (pub) return pubSideHtml(pub);
    const p = plugin();
    if (!p) return '';
    const u = p.usage;
    const used = u.perDay ? Math.min(100, (u.today / u.perDay) * 100) : 0;
    const first = p.delivery.filter((e) => e.first), standby = p.delivery.filter((e) => !e.first);
    const era = (e) => `<tr><td>${esc(JOBS[e.job] || e.job)}</td><td>${esc(e.asset)}${several(p) ? `<div class="p-muted">${esc(e.feed)}</div>` : ''}</td><td>${esc(e.start)} → ${esc(e.end || 'now')}</td>
        <td class="p-muted">${e.unique ? 'only source' : e.first ? `then ${esc(e.others.join(', '))}` : `after ${esc(e.others[0] || '')}`}</td></tr>`;
    const keys = p.keys.length ? p.keys.map((k) => `<div class="small"><code>${esc(k.name)}</code> ${k.set ? '<span class="up">set</span>' : '<span class="down">not set</span>'}</div>`).join('')
      + '<div class="p-muted small">Set in Setup.</div>' : '<div class="p-muted small">Needs no key.</div>';
    return `<h3>${esc(p.title)} ${chip(p.state)}</h3>
      <div class="p-muted small">${esc(p.about)}</div>${release(p)}
      ${p.kill ? `<div class="pl-warn">Killed until ${esc(p.kill.until?.slice(0, 16).replace('T', ' '))} UTC: ${esc(p.kill.why)}</div>` : ''}
      <div class="tiles ex-tiles">
        ${tile('Requests today', num(u.today), `of ${num(u.perDay)} a day`)}
        ${tile('Symbols', num(p.watched), 'watched on it')}
        ${tile('Its load', days(p.load), 'of its limits for what it delivers')}
        ${tile('Delivers', num(first.length), `eras first · ${num(standby.length)} standing by`)}
      </div>
      <div class="pl-usage" title="${num(u.today)} of ${num(u.perDay)} requests today"><i style="width:${used.toFixed(1)}%"></i></div>
      ${first.length ? `<h4>What it delivers</h4><table class="act-table ex-mini"><tbody>${first.map(era).join('')}</tbody></table>` : ''}
      ${standby.length ? `<h4>Standing by for</h4><table class="act-table ex-mini"><tbody>${standby.map(era).join('')}</tbody></table>` : ''}
      <h4>Keys</h4>${keys}
      ${p.signup ? `<div class="p-muted small">From ${esc(p.signup)}</div>` : ''}`;
  }

  function render() {
    if (!data) { box.innerHTML = '<div class="empty">Loading the plugins…</div>'; return; }
    const p = plugin(), pub = publisher();
    const scrolled = box.querySelector('.ex-list')?.scrollTop || 0;
    // what is being typed in Setup survives the view's refreshes (every minute, every few seconds in a rescan)
    const typed = [...box.querySelectorAll('input.pl-key')].filter((i) => i.value).map((i) => [i.dataset.var, i.value]);
    const focused = document.activeElement?.matches?.('input.pl-key') ? document.activeElement.dataset.var : null;
    const setUp = data.plugins.filter((x) => x.configured && x.state !== 'no key').length;
    const pubPlugins = (data.publishers || []).filter((q) => !parentOf(q)).length;  // its parts in it
    const head = pub ? `publisher · ${pubKind(pub)} · ${pubCount(pub)}`
      : p ? `${p.archive ? 'closed archive' : 'feed'} · ${p.kind} data · ${p.assets.join(', ')}` : '';
    box.innerHTML = `
      <div class="ex-venues"><div class="view-head"><div><h2>Plugins</h2>
        <div class="p-muted small">${num(data.plugins.length + pubPlugins)} plugins · ${num(setUp)} of ${num(data.plugins.length)} feeds set up · plugin API ${esc(data.api)}</div></div></div>
        <button type="button" class="pl-all" data-rescan="*"${data.offline || data.running ? ' disabled' : ''}
          title="${data.offline ? 'This offline copy of the app sends no requests' : 'Every plugin set up here asks its provider again (a few requests each)'}">${data.running ? 'Scanning…' : 'Rescan all'}</button>
        ${note ? `<div class="p-muted small pl-note-line">${esc(note)}</div>` : ''}
        ${listHtml()}</div>
      <div class="ex-list"><div class="view-head"><div><h2>${esc(pub?.title || p?.title || '')}</h2>
        <div class="p-muted small">${esc(head)}</div></div></div>${mainHtml()}</div>
      <aside class="ex-side">${sideHtml()}</aside>`;
    box.querySelector('.ex-list').scrollTop = scrolled;
    for (const [v, value] of typed) {
      const input = box.querySelector(`input.pl-key[data-var="${CSS.escape(v)}"]`);
      if (input) input.value = value;
    }
    if (focused) box.querySelector(`input.pl-key[data-var="${CSS.escape(focused)}"]`)?.focus();
  }

  box.addEventListener('keydown', (e) => {  // Enter in a Setup field saves it
    if (e.key === 'Enter' && e.target.matches('input.pl-key')) {
      e.target.closest('tr')?.querySelector('[data-save-key]')?.click();
    }
  });
  box.addEventListener('change', (e) => {
    if (e.target.matches('select.pl-choose')) choosePlan(e.target);
  });
  box.addEventListener('toggle', (e) => {  // a part's section opened or closed: kept through the refreshes
    if (e.target.matches?.('details.pl-part')) folds.set(e.target.dataset.part, e.target.open);
  }, true);
  box.addEventListener('click', (e) => {
    const t = e.target.closest('[data-plugin],[data-rescan],[data-recheck],[data-pause],[data-save-key],[data-remove-key]');
    if (!t || t.disabled) return;
    if (t.dataset.saveKey) {
      const input = box.querySelector(`input.pl-key[data-var="${CSS.escape(t.dataset.saveKey)}"]`);
      const value = input?.value.trim();
      if (!value) { note = `Type ${t.dataset.saveKey} first.`; render(); return; }
      input.value = '';  // sent once; never kept in the page
      saveKey(t.dataset.owner, t.dataset.saveKey, value);
    } else if (t.dataset.removeKey) {
      if (window.confirm(`Remove ${t.dataset.removeKey} from your user environment variables? What reads it stops until you set it again.`)) {
        saveKey(t.dataset.owner, t.dataset.removeKey, null);
      }
    } else if (t.dataset.plugin && t.dataset.plugin !== sel) {
      sel = t.dataset.plugin; render();
    } else if (t.dataset.rescan) {
      rescan(t.dataset.rescan === '*' ? null : t.dataset.rescan);
    } else if (t.dataset.recheck) {
      post(`/api/plugins/recheck?name=${encodeURIComponent(t.dataset.recheck)}`, `Recheck started: ${pubNamed(t.dataset.recheck)?.title || t.dataset.recheck}.`);
    } else if (t.dataset.pause) {
      const on = t.dataset.on === '1';
      post(`/api/plugins/pause?name=${encodeURIComponent(t.dataset.pause)}&on=${on ? 1 : 0}`, on ? 'Paused.' : 'Resumed.');
    }
  });
  window.addEventListener('massive:view', (e) => { if (e.detail.view === 'plugins') load(); else clearTimeout(timer); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  if (document.body.dataset.view === 'plugins') load();  // the page opened on this view (before this script listened)
})();

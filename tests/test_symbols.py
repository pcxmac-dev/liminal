import pytest

from liminal_lib.symbols import resolve


@pytest.mark.parametrize("text, ticker, asset, source, invert, rank, exch", [
    ("SPCX::NASDAQ", "SPCX", "stock", "SPCX", False, 1, "XNAS"),
    ("nasdaq:spcx", "SPCX", "stock", "SPCX", False, 1, "XNAS"),
    ("spcx", "SPCX", "stock", "SPCX", False, 1, None),
    ("BRK.B", "BRK.B", "stock", "BRK.B", False, 1, None),  # a share class, not a listing abroad
    ("7203.T", "7203.T", "stock", "7203.T", False, 1, "XTKS"),  # a listing abroad: TICKER.SUFFIX, its exchange
    ("TSE:7203", "7203.T", "stock", "7203.T", False, 1, "XTKS"),
    ("2330::XTAI", "2330.TW", "stock", "2330.TW", False, 1, "XTAI"),
    ("petr4.sa", "PETR4.SA", "stock", "PETR4.SA", False, 1, "BVMF"),
    ("IXIC", "IXIC", "index", "I:COMP", False, 1, None),
    ("SPX", "SPX", "index", "I:SPX", False, 1, None),
    ("RUT", "RUT", "index", "I:RUT", False, 1, None),
    ("DJI", "DJI", "index", "I:DJI", False, 1, None),
    ("^GSPC", "SPX", "index", "I:SPX", False, 1, None),
    ("I:COMP", "COMP", "index", "I:COMP", False, 1, None),
    ("EURUSD", "EURUSD", "fx", "C:EURUSD", False, 1, None),
    ("USDEUR", "USDEUR", "fx", "C:EURUSD", True, 1, None),
    ("eur/usd", "EURUSD", "fx", "C:EURUSD", False, 1, None),
    ("FX:USDJPY", "USDJPY", "fx", "C:USDJPY", False, 1, None),
    ("JPYUSD", "JPYUSD", "fx", "C:USDJPY", True, 1, None),
    ("NQ1!", "NQ1!", "future", "NQ", False, 1, None),
    ("CL1!", "CL1!", "future", "CL", False, 1, None),
    ("ng1!", "NG1!", "future", "NG", False, 1, None),
    ("NQ2!", "NQ2!", "future", "NQ", False, 2, None),
    ("6E1!", "6E1!", "future", "6E", False, 1, None),
])
def test_resolve(text, ticker, asset, source, invert, rank, exch):
    s = resolve(text)
    assert (s.ticker, s.asset, s.source_ticker, s.invert, s.rank, s.exchange) == (ticker, asset, source, invert, rank, exch)


def test_crypto_pairs():
    for text in ("BTCUSD", "btc/usd", "BTC-USD", "X:BTCUSD", "COINBASE:BTCUSD", "BTCUSD::KRAKEN"):
        spec = resolve(text)
        assert (spec.ticker, spec.asset, spec.source_ticker) == ("BTCUSD", "crypto", "X:BTCUSD"), text
    assert resolve("ETH/BTC").source_ticker == "X:ETHBTC"
    assert resolve("BTC").asset == "stock"  # the Grayscale Bitcoin Mini Trust, a listed fund
    assert resolve("NASDAQ:COIN").asset == "stock"  # an exchange prefix that is not a crypto venue
    assert resolve("EURUSD").asset == "fx"

"""A symbol's exchange is named by the exchange, not by a tape sharing its MIC (the user, 2026-10-31,
of MCD shown as "Consolidated Tape Association": "is this the right corp name ?")."""
import pandas as pd

from liminal_lib.storage.markets import mic_names


def test_an_exchange_names_its_mic_before_a_tape_of_it():
    rows = pd.DataFrame([  # as store.exchanges() gives them: by source, then id
        ("alpaca", 78, "New York Stock Exchange", "N", "XNYS", "exchange", "US"),
        ("alpaca", 81, "NASDAQ OMX", "Q", "XNAS", "exchange", "US"),
        ("massive", 5, "Unlisted Trading Privileges", None, "XNAS", "SIP", "US"),
        ("massive", 10, "New York Stock Exchange", None, "XNYS", "exchange", "US"),
        ("massive", 12, "Nasdaq", None, "XNAS", "exchange", "US"),
        ("massive", 13, "Consolidated Tape Association", None, "XNYS", "SIP", "US"),
        ("massive", 99, "A TRF only", None, "XTRF", "TRF", "US"),
    ], columns=["source", "id", "name", "acronym", "mic", "type", "country"])
    names = mic_names(rows)
    assert names["XNYS"] == "New York Stock Exchange"
    assert names["XNAS"] == "NASDAQ OMX"  # an exchange's own, the first source's
    assert names["XTRF"] == "A TRF only"  # no exchange of that MIC: what there is

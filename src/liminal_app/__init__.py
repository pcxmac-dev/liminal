"""liminal-app, the chart app: its front and pages, the data API and the command line (`liminal`),
on liminal-lib (the library: the stores, the plugin contract, the collector and the scheme), with
the fetcher in liminal-integrator. The user, 2026-11-02: "lets rename the app to liminal-app", "not
liminal", "refactor": the app's own modules are cli, deps, gui and trading; everything else is the
library's, imported as liminal_lib (the alias package `liminal` is gone)."""

import os
from pathlib import Path

import liminal_lib

__version__ = "0.2.0"
liminal_lib.limit_threads()  # before numpy loads (and again on a reload of this package)
# The GitHub-hosted datasets' git submodules stay in this repository (data/github): the library reads
# them from here unless LIMINAL_DATA_REPOS says where else.
_repos = Path(__file__).resolve().parents[2] / "data" / "github"
if _repos.is_dir():
    os.environ.setdefault("LIMINAL_DATA_REPOS", str(_repos))

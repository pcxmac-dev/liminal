"""Liminal, the chart app: its front and pages, the data API and the command line, on liminal-lib
(the library: the stores, the plugin contract, the collector and the scheme). The library's modules
answer here under their old names, liminal.<module>, until every import points to liminal_lib (the
user, 2026-11-01: "all lib calls will point to liminal-lib"): a finder maps each to the one module."""

import importlib
import importlib.abc
import importlib.util
import os
import sys
from pathlib import Path

import liminal_lib

__version__ = "0.1.0"
liminal_lib.limit_threads()  # before numpy loads (and again on a reload of this package)
OWN = {"cli", "gui", "deps", "__main__"}  # the app's own modules; every other liminal.<name> is the library's
# The GitHub-hosted datasets' git submodules stay in this repository (data/github): the library reads
# them from here unless LIMINAL_DATA_REPOS says where else.
_repos = Path(__file__).resolve().parents[2] / "data" / "github"
if _repos.is_dir():
    os.environ.setdefault("LIMINAL_DATA_REPOS", str(_repos))


class _Alias(importlib.abc.Loader):
    """Loads a library module under its old name here: the same module object, its own spec kept."""

    def __init__(self, module):
        self.module, self.spec = module, module.__spec__

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        module.__spec__ = self.spec


class _LibFinder(importlib.abc.MetaPathFinder):
    """liminal.<name> -> liminal_lib.<name>, for every module of the library (first in sys.meta_path:
    the path finder would otherwise make a second module of the library's file under this name)."""

    def find_spec(self, name, path=None, target=None):
        if not name.startswith("liminal."):
            return None
        rest = name[len("liminal."):]
        if rest.split(".", 1)[0] in OWN:
            return None
        wanted = "liminal_lib." + rest
        try:
            module = importlib.import_module(wanted)
        except ModuleNotFoundError as e:
            if e.name and (e.name == wanted or wanted.startswith(e.name + ".")):
                return None  # not a module of the library either
            raise
        spec = importlib.util.spec_from_loader(name, _Alias(module), is_package=hasattr(module, "__path__"))
        if hasattr(module, "__path__"):
            spec.submodule_search_locations = list(module.__path__)
        return spec


if not any(isinstance(f, _LibFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _LibFinder())

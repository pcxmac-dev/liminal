"""A plugin's own settings (plugin API 1.11) that fail to build: a ConfigError, a value of yours it
refuses, stops the app as any setting's does; anything else is the plugin's own failure, which leaves
it out and reports it (sources/registry.py: errors), never fatal: the app runs on the other plugins."""
from __future__ import annotations

from dataclasses import replace

import pytest

from liminal.config import ConfigError, load_settings
from liminal.sources import providers, registry

from .test_plugin_databases import installed  # noqa: F401 - the fixture: these plugins, installed
from .test_plugins import ACME


def test_a_plugin_whose_settings_fail_is_left_out_and_reported(installed):  # noqa: F811
    def broken(variables):
        raise KeyError("ACME_PLAN")

    installed(replace(ACME, settings=broken), replace(ACME, name="acme2", title="Acme Two"))
    s = load_settings(env={}, env_file=None)
    assert "acme" not in providers() and "acme2" in providers()  # left out, the other kept
    assert s.plugin("acme") is None and s.for_source("acme2").tier.name == "acme-free"
    assert [why for _, why in registry.errors() if why.startswith("acme:")] == \
        ["acme: its settings failed (KeyError: 'ACME_PLAN')"]


def test_a_value_a_plugin_refuses_stops_the_app_as_any_setting_does(installed):  # noqa: F811
    def refuse(variables):
        raise ConfigError("Unknown ACME_PLAN 'gold'; choose one of free")

    installed(replace(ACME, settings=refuse))
    with pytest.raises(ConfigError, match="ACME_PLAN"):
        load_settings(env={}, env_file=None)
    assert "acme" in providers()  # not the plugin's failure: it stays, the setting is yours to fix

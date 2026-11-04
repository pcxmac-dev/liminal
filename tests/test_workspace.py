"""The workspace (liminal_libs.layout; the user, 2026-11-02): common/ the library, app/ the chart
app, store/ the integrator with the databases in store/data/, plugins/ a checkout per plugin,
loaded from there (the plugin directory the fetcher assigns)."""
from __future__ import annotations

from pathlib import Path

from liminal_libs import config, layout
from liminal_libs.sources import provider, providers
from liminal_libs.sources import registry

from .test_plugins import installed  # noqa: F401  (a test's fake entry points)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "liminal"
    for name in layout.FOLDERS:
        (root / name).mkdir(parents=True)
    return root


def test_the_workspace_puts_the_databases_in_the_store_and_the_plugins_in_plugins(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    monkeypatch.setenv(layout.HOME_VAR, str(root))
    monkeypatch.delenv(layout.PLUGINS_VAR, raising=False)
    assert layout.home() == root and layout.data_dir() == root / "store" / "data" and layout.plugins_dir() == root / "plugins"
    settings = config.load_settings(env={}, env_file=None)
    assert settings.db_path == config.DEFAULT_DB_PATH  # the default, as the process found it at its start
    monkeypatch.setenv(layout.PLUGINS_VAR, str(tmp_path / "elsewhere"))
    assert layout.plugins_dir() == tmp_path / "elsewhere"
    # not laid out so: the data folder of old, the plugins as installed packages
    monkeypatch.delenv(layout.HOME_VAR)
    monkeypatch.delenv(layout.PLUGINS_VAR)
    monkeypatch.setattr(layout, "FOLDERS", ("no-such-folder",))
    assert layout.home() is None and layout.data_dir() == Path.home() / "LiminalData" and layout.plugins_dir() is None


def _checkout(folder: Path, name: str, module: str, version: str = "9.9.9") -> None:
    """A plugin's checkout as its repository holds it: pyproject.toml with the entry point, src/."""
    sub = folder / name
    (sub / "src" / module).mkdir(parents=True)
    (sub / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n\n[project.entry-points."liminal.providers"]\n'
        f'{module.removeprefix("plugin_integrator_")} = "{module}:PLUGIN"\n', encoding="utf-8")
    (sub / "src" / module / "__init__.py").write_text(  # a plugin of the class form (plugin API 2.0)
        "from liminal_libs.sources.registry import FeedPlugin\n\n\n"
        f"class Plugin(FeedPlugin):\n    name = {module.removeprefix('plugin_integrator_')!r}\n    title = 'A test plugin'\n"
        "    assets = frozenset({'crypto'})\n\n    def build(self, settings, budget):\n        return None\n\n\n"
        "PLUGIN = Plugin()\n", encoding="utf-8")


def test_the_plugins_in_the_plugin_directory_are_loaded_from_there(tmp_path, monkeypatch, installed):
    folder = tmp_path / "plugins"
    _checkout(folder, "plugin-integrator-acmetest", "plugin_integrator_acmetest")
    (folder / "not-a-plugin").mkdir()  # a folder without a pyproject: nothing
    (folder / "plugin-integrator-other" ).mkdir()
    (folder / "plugin-integrator-other" / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")  # no entry point
    found = registry.plugin_checkouts(folder)
    assert found == [("plugin-integrator-acmetest", folder / "plugin-integrator-acmetest" / "src", "plugin_integrator_acmetest:PLUGIN", "9.9.9")]
    assert registry.plugin_checkouts(tmp_path / "nowhere") == []
    monkeypatch.setenv(layout.PLUGINS_VAR, str(folder))
    # loaded from its folder, with its version; a package of the same plugin installed besides is not loaded twice
    import liminal_libs.sources.registry as reg

    installed(("acmetest", "plugin_integrator_acmetest:PLUGIN", lambda: __import__("plugin_integrator_acmetest").PLUGIN))
    assert "acmetest" in providers()
    p = provider("acmetest")
    assert p.origin == "plugins/plugin-integrator-acmetest (plugin_integrator_acmetest:PLUGIN)" and p.version == "9.9.9"
    assert not any("a second provider named 'acmetest'" in why for _, why in reg.discover()[1])
    monkeypatch.delenv(layout.PLUGINS_VAR)
    monkeypatch.setattr(layout, "home", lambda: None)
    installed(("acmetest", "plugin_integrator_acmetest:PLUGIN", lambda: __import__("plugin_integrator_acmetest").PLUGIN))
    assert provider("acmetest").origin == "package: plugin_integrator_acmetest:PLUGIN"  # no directory: the package's entry point

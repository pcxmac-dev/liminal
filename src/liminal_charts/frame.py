"""The charts app as an app of the frame (liminal_libs.apps.App; the user, 2026-11-04: every app has one
master icon, the charts app's the symbol icon, the disk at the top of the rail; 2026-11-06: "the app itself
(either chart or integrator) has plugin ABC as well"; "the plugin ABC will enumerate attached plugins and
their API"): what holds the plugins the charts app runs with and its login, the one authorization
interface they read their keys through (`self.login.key(self.name)`). The page and the data API are still
gui/server.py's (ChartApp) and the front gui/front.py's; the App base takes the server over at 0.3.0.
Alone (gui --alone) the charts app holds every plugin the registry loaded, as the super app; behind the
front, the integrator holds the stock-data plugins in its own process (liminal_integrator.app)."""
from __future__ import annotations

from liminal_libs.apps import App, EnvironmentLogin, Login, attach_registry


class ChartsApp(App):
    NAME = "charts"
    TITLE = "Liminal Charts"
    ICON = "disk"  # the symbol's disk at the top of the rail (icons.js)
    PORT = 8765
    PORT_VAR = "LIMINAL_CHARTS_PORT"

    def __init__(self, log=print, login: Login | None = None):
        # The user environment variables stand in for a login session until the app holds one of its own
        # (the front asks the login app of the charts namespace who is signed in; a key furnished per
        # signed-in user is the design to come).
        super().__init__(log=log, login=login if login is not None else EnvironmentLogin())

    def attach_plugins(self, only: str | None = None) -> list[str]:
        """Every plugin the registry loaded (one system with `only`: "integrator", "platform"), attached
        here with this app's login; the names attached (a plugin another app holds is left alone)."""
        return attach_registry(self, only=only)

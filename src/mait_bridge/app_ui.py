from pathlib import Path

from pydoover import ui


class MaitBridgeUI(ui.UI, hidden=True):
    """No panel on the device page.

    The bridge's status and activity are shown by MAIT Bridge Cloud; this app
    only publishes tags. The UI is declared empty and hidden so the published
    schema replaces any earlier panel.
    """


def export():
    MaitBridgeUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "mait_bridge"
    )

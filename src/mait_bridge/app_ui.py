from pathlib import Path

from pydoover import ui

from .app_tags import MaitBridgeTags


class MaitBridgeUI(ui.UI):
    status = ui.TextVariable("Status", value=MaitBridgeTags.status, position=1)
    port = ui.TextVariable("Serial Port", value=MaitBridgeTags.port, position=2)
    modules_heard = ui.NumericVariable(
        "Modules Heard", value=MaitBridgeTags.modules_heard, precision=0, position=3
    )
    last_uplink = ui.Timestamp(
        "Last Uplink", value=MaitBridgeTags.last_uplink, position=4
    )
    downlink = ui.Submodule(
        "Downlink",
        children=[
            ui.NumericVariable(
                "Received", value=MaitBridgeTags.downlinks_received, precision=0
            ),
            ui.Timestamp("Last Received", value=MaitBridgeTags.last_downlink),
            ui.TextVariable("Last Message", value=MaitBridgeTags.last_downlink_text),
        ],
        position=5,
    )


def export():
    MaitBridgeUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "mait_bridge"
    )

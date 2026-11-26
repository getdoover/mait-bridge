"""The bridge's page on the Doovit: status, uplink and downlink activity, and
the mapping page (a widget) where modules are mapped to devices' app inputs and
each module's last-heard time is shown."""

from pathlib import Path

from pydoover import ui

from .app_tags import MaitBridgeCloudTags


class MaitBridgeCloudUI(ui.UI):
    async def setup(self):
        self.add_element(
            ui.WarningIndicator(
                MaitBridgeCloudTags.errors_text,
                name="errors",
                hidden=MaitBridgeCloudTags.errors_hidden,
                can_cancel=False,
                position=1,
            )
        )
        self.add_element(
            ui.TextVariable(
                "Bridge Status",
                name="bridge_status",
                value=MaitBridgeCloudTags.bridge_status,
                position=2,
            )
        )
        self.add_element(
            ui.Timestamp(
                "Last Uplink",
                name="last_uplink",
                value=MaitBridgeCloudTags.last_uplink,
                position=3,
            )
        )
        self.add_element(
            ui.TextVariable(
                "Modules",
                name="modules_text",
                value=MaitBridgeCloudTags.modules_text,
                position=4,
            )
        )
        self.add_element(
            ui.NumericVariable(
                "Devices Mapped",
                name="devices_mapped",
                value=MaitBridgeCloudTags.devices_mapped,
                precision=0,
                position=5,
            )
        )
        self.add_element(
            ui.Timestamp(
                "Last Downlink",
                name="last_downlink",
                value=MaitBridgeCloudTags.last_downlink,
                position=6,
            )
        )
        self.add_element(
            ui.TextVariable(
                "Last Downlink Forwarded",
                name="last_downlink_text",
                value=MaitBridgeCloudTags.last_downlink_text,
                position=7,
            )
        )

        self.add_element(
            ui.TextVariable(
                "Map From",
                name="map_source",
                value=MaitBridgeCloudTags.map_source,
                position=8,
            )
        )
        # The mapping page: modules and channels to devices' app inputs, and
        # when each module was last heard.
        self.add_element(
            ui.RemoteComponent(
                name="MaitMap",
                display_name="Module Mapping",
                component_url="$config.app().dv_widget_url",
                scope="MaitMapWidget",
                module="./MaitMapWidget",
                app_key="$config.app().APP_KEY",
                position=10,
            )
        )


def export():
    MaitBridgeCloudUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "mait_bridge_cloud",
    )

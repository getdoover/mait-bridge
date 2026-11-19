"""The bridge's page on the Doovit: status, uplink and downlink activity, and
when each mapped module was last heard. Built from config at deployment; every
value is bound to a tag."""

from pathlib import Path

from pydoover import ui

from .app_tags import MaitBridgeCloudTags, module_heard_key
from .app_config import plain
from .bridge import mapped_modules, module_label, parse_module_map


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

        raw = None
        if self.config is not None:
            raw = plain(self.config.modules)
        mappings, _ = parse_module_map(raw)
        if mappings:
            # One row per module, even when it is split across several devices.
            children = []
            for index, module in enumerate(sorted(mapped_modules(mappings))):
                label = module_label(mappings, module)
                children.append(
                    ui.Timestamp(
                        f"{module} · {label}" if label else f"Module {module}",
                        name=f"m{module}_heard",
                        value=ui.tag_ref(module_heard_key(module), "number", None),
                        position=index + 1,
                    )
                )
            self.add_element(
                ui.Submodule(
                    "Modules Last Heard",
                    name="modules_heard",
                    status=MaitBridgeCloudTags.modules_text,
                    children=children,
                    position=10,
                )
            )


def export():
    MaitBridgeCloudUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json",
        "mait_bridge_cloud",
    )

from pathlib import Path

from pydoover import config
from pydoover.processor import (
    ExtendedPermissionsConfig,
    ManySubscriptionConfig,
    ScheduleConfig,
)

from .bridge import CONVERSION_NONE, CONVERSIONS


class ChannelMappingConfig(config.Object):
    channel = config.Integer(
        "Channel",
        name="channel",
        description="Radio module channel number, e.g. 3 for the module's channel 3.",
        minimum=1,
        maximum=32,
        position=1,
    )
    field = config.String(
        "Field",
        name="field",
        description=(
            "Field written to the device's state channel, e.g. 'tank_level'. "
            "Apps on the device read it as '$io_state.<field>'. Commands for an "
            "output use this name as their target."
        ),
        position=2,
    )
    multiplier = config.Number(
        "Multiplier",
        name="multiplier",
        description="The published value is raw × multiplier + offset.",
        default=1.0,
        position=3,
    )
    offset = config.Number(
        "Offset",
        name="offset",
        description="Added after the multiplier.",
        default=0.0,
        position=4,
    )
    conversion = config.Enum(
        "Conversion",
        name="conversion",
        choices=list(CONVERSIONS),
        default=CONVERSION_NONE,
        description=(
            "Optional conversion of the raw value. 'UTC hhmmss to epoch ms' turns "
            "a GPS time of day such as 195945 into a timestamp."
        ),
        position=5,
    )


class ModuleMapConfig(config.Object):
    module = config.Integer(
        "Module Number",
        name="module",
        description="The radio module's number on the network, e.g. 10.",
        minimum=1,
        maximum=65535,
        position=1,
    )
    name = config.String(
        "Label",
        name="name",
        description="Optional label for the bridge page, e.g. 'Eastern Pivot tracker'.",
        default="",
        required=False,
        position=2,
    )
    device = config.Device(
        "Target Device",
        name="device",
        description=(
            "Device that receives this entry's channels. Several modules may "
            "feed the same device, and one module may be split across several "
            "devices by giving it one entry per device."
        ),
        position=3,
    )
    channels = config.Array(
        "Channel Mappings",
        name="channels",
        element=ChannelMappingConfig("Channel Mapping"),
        description="Which module channels are published, and under which field names.",
        default=[],
        position=4,
    )
    include_link = config.Boolean(
        "Publish Link Fields",
        name="include_link",
        description=(
            "Also publish link_success_pct, retries, route and last_heard for "
            "this module. Turn off on an entry that only lends a device a few "
            "channels; only entries with link fields mark their device online."
        ),
        default=True,
        position=5,
    )
    link_prefix = config.String(
        "Link Field Prefix",
        name="link_prefix",
        description=(
            "Prefix for this module's link fields, for a second module on the same "
            "device, e.g. 'tracker_' gives tracker_route. Leave blank for the "
            "device's main module."
        ),
        default="",
        required=False,
        position=6,
    )


class MaitBridgeCloudConfig(config.Schema):
    modules = config.Array(
        "Module Map",
        name="modules",
        element=ModuleMapConfig("Module"),
        description="Every radio module the bridge publishes, and where its readings go.",
        default=[],
        position=1,
    )

    mark_online = config.Boolean(
        "Show Devices Online",
        name="mark_online",
        description=(
            "Refresh each target device's connection status when its module is "
            "heard, so it shows as online."
        ),
        default=True,
        position=2,
    )
    expected_interval_min = config.Number(
        "Expected Report Interval (min)",
        name="expected_interval_min",
        description="How often a module is expected to be heard. Shown as 'Back in …' on the device.",
        default=15.0,
        minimum=1.0,
        position=3,
    )
    offline_after_min = config.Number(
        "Offline After (min)",
        name="offline_after_min",
        description="A device shows offline when its module has not been heard for this long.",
        default=90.0,
        minimum=1.0,
        position=4,
    )
    module_stale_min = config.Number(
        "Module Stale After (min)",
        name="module_stale_min",
        description="A module is counted stale on the bridge page after this long unheard.",
        default=120.0,
        minimum=1.0,
        position=5,
    )
    uplink_timeout_min = config.Number(
        "Uplink Timeout (min)",
        name="uplink_timeout_min",
        description="The bridge status shows a warning when no uplink arrives for this long.",
        default=30.0,
        minimum=1.0,
        position=6,
    )

    # -- Channels -------------------------------------------------------------
    uplink_channel = config.String(
        "Uplink Channel",
        name="uplink_channel",
        description="Channel on this device where the bridge publishes module reports.",
        default="mait_uplink",
        advanced=True,
        position=20,
    )
    downlink_channel = config.String(
        "Downlink Channel",
        name="downlink_channel",
        description="Channel on this device where commands and settings are forwarded to the bridge.",
        default="mait_downlink",
        advanced=True,
        position=21,
    )
    state_channel = config.String(
        "State Channel",
        name="state_channel",
        description="Channel on each target device that receives readings.",
        default="io_state",
        advanced=True,
        position=22,
    )
    command_channel = config.String(
        "Command Channel",
        name="command_channel",
        description="Channel on each target device that carries commands from its apps.",
        default="io_commands",
        advanced=True,
        position=23,
    )
    settings_channel = config.String(
        "Settings Channel",
        name="settings_channel",
        description="Channel on each target device whose aggregate carries settings the edge enforces.",
        default="control_settings",
        advanced=True,
        position=24,
    )

    subscription = ManySubscriptionConfig(
        default=["mait_uplink"],
        description=(
            "Channels that invoke this app: the Uplink Channel, plus, for every "
            "target device, '<device id>-io_commands' and "
            "'<device id>-control_settings' so commands and settings reach the "
            "bridge as soon as they change."
        ),
        advanced=True,
        position=25,
    )
    schedule = ScheduleConfig(
        default="rate(5 minutes)",
        description="Periodic refresh: bridge status, stale modules, and a settings re-check on every target device.",
        advanced=True,
        position=26,
    )
    extended_permissions = ExtendedPermissionsConfig(
        default_device_group=True,
        extra_fields=["id", "name", "display_name"],
        default={
            "devices": [],
            "groups": [],
            "apps_installed": [],
            "all_devices": False,
        },
        required=False,
        position=27,
    )

    position = config.ApplicationPosition(position=28)


def plain(element):
    """A config element's value as plain JSON types (arrays and objects nested)."""
    if element is None:
        return None
    if isinstance(element, config.Array):
        return [plain(child) for child in element.elements]
    if isinstance(element, config.Object):
        return {
            getattr(child, "name", None) or key: plain(child)
            for key, child in element._elements.items()
        }
    return getattr(element, "value", None)


def export():
    MaitBridgeCloudConfig.export(
        Path(__file__).parents[2] / "doover_config.json",
        "mait_bridge_cloud",
    )

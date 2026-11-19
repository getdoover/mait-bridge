from pathlib import Path

from pydoover import config


class MaitBridgeConfig(config.Schema):
    serial_port = config.String(
        "Serial Port",
        name="serial_port",
        description="Serial device of the MAIT base radio, mapped into the container.",
        default="/dev/ttyAMA0",
        position=1,
    )
    baud_rate = config.Integer(
        "Baud Rate",
        name="baud_rate",
        description="Serial speed of the base radio (8N1, no flow control).",
        default=9600,
        position=2,
    )
    network_id = config.Integer(
        "Network ID",
        name="network_id",
        description="Radio network id in every frame header; frames from other networks are ignored.",
        default=2647,
        minimum=0,
        maximum=65535,
        position=3,
    )
    snapshot_interval_s = config.Integer(
        "Snapshot Poll Interval (s)",
        name="snapshot_interval_s",
        description="How often each module's live values are expected (snapshot polls).",
        default=300,
        minimum=10,
        position=4,
    )
    status_interval_s = config.Integer(
        "Status Poll Interval (s)",
        name="status_interval_s",
        description="How often each module's status and logged records are expected.",
        default=3600,
        minimum=60,
        position=5,
    )
    publish_interval_s = config.Integer(
        "Uplink Publish Interval (s)",
        name="publish_interval_s",
        description="How often heard module reports are batched into one uplink message.",
        default=60,
        minimum=5,
        position=6,
    )
    uplink_channel = config.String(
        "Uplink Channel",
        name="uplink_channel",
        description="Channel the bridge publishes module reports to (read by MAIT Bridge Cloud).",
        default="mait_uplink",
        advanced=True,
        position=10,
    )
    downlink_channel = config.String(
        "Downlink Channel",
        name="downlink_channel",
        description="Channel the bridge receives commands and settings on (written by MAIT Bridge Cloud).",
        default="mait_downlink",
        advanced=True,
        position=11,
    )


def export():
    MaitBridgeConfig.export(
        Path(__file__).parents[2] / "doover_config.json",
        "mait_bridge",
    )

import time
from types import SimpleNamespace

from pydoover.models import ConnectionDetermination, ConnectionStatus, ConnectionType
from pydoover.tags.manager import TagsManagerProcessor

from mait_bridge_cloud.app_config import MaitBridgeCloudConfig
from mait_bridge_cloud.app_tags import MaitBridgeCloudTags
from mait_bridge_cloud.application import MaitBridgeCloudApplication

DOOVIT = 249020530978490113
TANK = "248969125739677702"
PIVOT = "248969157800937480"
LOCKED = "248969136409987084"
NOW = int(time.time() * 1000)

CONFIG = {
    "modules": [
        {
            "module": 10,
            "name": "Existing Tank 1",
            "device": TANK,
            "channels": [
                {"channel": 1, "field": "flood_gate_1"},
                {"channel": 3, "field": "tank_level"},
                {"channel": 17, "field": "battery_v"},
            ],
        },
        {
            "module": 20,
            "device": LOCKED,
            "channels": [{"channel": 3, "field": "tank_level"}],
        },
        {
            "module": 60,
            "device": PIVOT,
            "channels": [
                {"channel": 2, "field": "run"},
                {"channel": 17, "field": "battery_v"},
            ],
        },
        {
            "module": 80,
            "device": PIVOT,
            "link_prefix": "tracker_",
            "channels": [
                {"channel": 3, "field": "latitude"},
                {"channel": 17, "field": "tracker_battery_v"},
            ],
        },
    ],
    "expected_interval_min": 15,
    "offline_after_min": 90,
}


class Forbidden(Exception):
    pass


class FakeApi:
    def __init__(self, aggregates=None, forbidden=()):
        self.messages = []
        self.aggregate_updates = []
        self.pings = []
        self.connection_configs = []
        self.aggregates = aggregates or {}
        self.forbidden = set(forbidden)
        self.lookup_ip = True

    def _check(self, agent_id):
        if agent_id is not None and str(agent_id) in self.forbidden:
            raise Forbidden("403 Forbidden")

    async def create_message(self, channel, data, agent_id=None, **kwargs):
        self._check(agent_id)
        self.messages.append((str(agent_id) if agent_id else None, channel, data))

    async def update_channel_aggregate(self, channel, data, agent_id=None, **kwargs):
        self._check(agent_id)
        self.aggregate_updates.append(
            (str(agent_id) if agent_id else None, channel, data, kwargs)
        )

    async def fetch_channel_aggregate(self, channel, agent_id=None, **kwargs):
        self._check(agent_id)
        key = (str(agent_id) if agent_id else None, channel)
        if key not in self.aggregates:
            raise LookupError("404")
        return SimpleNamespace(data=self.aggregates[key])

    async def update_connection_config(self, config, agent_id=None, **kwargs):
        self._check(agent_id)
        self.connection_configs.append((str(agent_id), config))

    async def ping_connection_at(
        self, online_at, connection_status, determination, agent_id=None, **kwargs
    ):
        self._check(agent_id)
        self.pings.append((str(agent_id), online_at, connection_status, determination))


async def make_app(config=None, api=None, tag_values=None):
    app = object.__new__(MaitBridgeCloudApplication)
    app.config = MaitBridgeCloudConfig()
    app.config._inject_deployment_config(config or CONFIG)
    app.app_key = "mait_bridge_cloud_1"
    app.agent_id = DOOVIT
    app.api = api or FakeApi()
    app.tag_manager = TagsManagerProcessor(
        "mait_bridge_cloud_1", app.api, DOOVIT, tag_values or {}
    )
    app.tags = MaitBridgeCloudTags("mait_bridge_cloud_1", app.tag_manager, app.config)
    app.received_deployment_config = {
        "DEVICE_MAP": {
            TANK: {"name": "t1", "display_name": "Existing Tank 1"},
            LOCKED: {"name": "t2", "display_name": "Existing Tank 2"},
            PIVOT: {"name": "p", "display_name": "Eastern Pivot"},
        }
    }
    await app.setup()
    return app


def event(agent_id, channel, data):
    return SimpleNamespace(
        channel=SimpleNamespace(agent_id=int(agent_id), name=channel),
        message=SimpleNamespace(data=data),
    )


UPLINK = {
    "ts": NOW,
    "modules": [
        {
            "module": 10,
            "channels": {"1": 0, "3": 9.004, "17": 12.8},
            "link": {"success_pct": 96.8, "retries": 0.03, "route": []},
            "heard_ts": NOW - 5000,
        },
        {
            "module": 60,
            "channels": {"2": 0, "17": 12.9},
            "link": {"success_pct": 48.0, "retries": 1.08, "route": [300, 50]},
            "heard_ts": NOW - 4000,
        },
        {
            "module": 80,
            "channels": {"3": -22.5, "17": 12.9},
            "link": {"success_pct": 43.5, "retries": 1.29, "route": [300, 50, 60]},
            "heard_ts": NOW - 3000,
        },
        {"module": 170, "channels": {"1": 1}, "heard_ts": NOW},
    ],
}


async def test_uplink_fans_out_to_devices():
    api = FakeApi(aggregates={(PIVOT, "io_state"): {"run": 1}})
    app = await make_app(api=api)
    await app.on_message_create(event(DOOVIT, "mait_uplink", UPLINK))

    states = [(a, d) for a, c, d in api.messages if c == "io_state"]
    assert len(states) == 3
    tank = next(d for a, d in states if a == TANK)
    assert tank["tank_level"] == 9.004 and tank["battery_v"] == 12.8
    assert tank["route"] == "Base → 10" and tank["last_heard"] == NOW - 5000
    tracker = [d for a, d in states if a == PIVOT and "latitude" in d][0]
    assert "battery_v" not in tracker and tracker["tracker_battery_v"] == 12.9

    # Aggregates: the tank had none (seeded whole), the pivot merged both modules.
    aggs = {a: (d, kw) for a, c, d, kw in api.aggregate_updates if c == "io_state"}
    assert aggs[TANK][1].get("replace_data") is True
    assert aggs[PIVOT][1].get("replace_data") is not True
    assert aggs[PIVOT][0]["battery_v"] == 12.9 and aggs[PIVOT][0]["latitude"] == -22.5

    # Online: one ping per device at the latest heard time, config sent once.
    pings = {a: (t, s, d) for a, t, s, d in api.pings}
    assert set(pings) == {TANK, PIVOT}
    assert int(pings[PIVOT][0].timestamp() * 1000) == NOW - 3000
    assert pings[TANK][1] == ConnectionStatus.periodic_unknown
    assert pings[TANK][2] == ConnectionDetermination.online
    cfg = api.connection_configs[0][1]
    assert cfg.connection_type == ConnectionType.periodic
    assert (cfg.expected_interval, cfg.offline_after) == (900, 5400)
    assert api.lookup_ip is False

    assert app.get_tag("m10_heard") == NOW - 5000
    assert app.get_tag("last_uplink") is not None
    assert "Module 170 is not in the module map" in app.get_tag("errors_text")
    assert app.get_tag("errors_hidden") is False
    assert app.get_tag("modules_text").startswith("3 of 4 heard")

    # A second uplink doesn't resend the connection config.
    await app.on_message_create(event(DOOVIT, "mait_uplink", UPLINK))
    assert len(api.connection_configs) == 2


async def test_uplink_permission_failure_reported():
    api = FakeApi(forbidden={LOCKED})
    app = await make_app(api=api)
    uplink = {
        "ts": NOW,
        "modules": [{"module": 20, "channels": {"3": 7.7}, "heard_ts": NOW}],
    }
    await app.on_message_create(event(DOOVIT, "mait_uplink", uplink))
    assert "Existing Tank 2: permission denied" in app.get_tag("errors_text")


async def test_old_report_marks_offline():
    api = FakeApi()
    app = await make_app(api=api)
    uplink = {
        "ts": NOW,
        "modules": [{"module": 10, "channels": {"3": 9}, "heard_ts": 1}],
    }
    await app.handle_uplink(uplink, NOW)
    assert api.pings[0][3] == ConnectionDetermination.offline


async def test_uplink_on_other_agent_ignored():
    api = FakeApi()
    app = await make_app(api=api)
    await app.on_message_create(event(TANK, "mait_uplink", UPLINK))
    assert api.messages == []


async def test_command_forwarded_to_downlink():
    api = FakeApi()
    app = await make_app(api=api)
    cmd = {
        "command": "open",
        "target": "flood_gate_1",
        "duration_s": 1800,
        "request_id": "r1",
        "app_key": "valve_control_1",
        "app": "valve_control",
        "ts": NOW,
    }
    await app.on_message_create(event(TANK, "io_commands", cmd))
    ((agent, channel, data),) = api.messages
    assert agent is None and channel == "mait_downlink"
    assert data["type"] == "command" and data["device_id"] == TANK
    assert (data["module"], data["channel"]) == (10, 1)
    assert data["payload"] == cmd
    assert "open flood_gate_1 → module 10 ch 1 (Existing Tank 1)" == app.get_tag(
        "last_downlink_text"
    )

    # Replies and unmapped devices are not forwarded; unmapped targets are reported.
    await app.on_message_create(
        event(TANK, "io_commands", {"request_id": "r1", "ok": True})
    )
    await app.on_message_create(event("1234", "io_commands", cmd))
    await app.on_message_create(
        event(TANK, "io_commands", {"command": "open", "target": "zzz"})
    )
    assert len(api.messages) == 1
    assert "zzz" in app.get_tag("errors_text")


async def test_settings_forwarded_once_per_change():
    api = FakeApi()
    app = await make_app(api=api)
    settings = {
        "valve_control_1": {
            "app": "valve_control",
            "schema": 1,
            "valves": [{"target": "flood_gate_1"}],
        }
    }
    agg_event = SimpleNamespace(
        channel=SimpleNamespace(agent_id=int(TANK), name="control_settings"),
        aggregate=SimpleNamespace(data=settings),
    )
    await app.on_aggregate_update(agg_event)
    await app.on_aggregate_update(agg_event)
    downlinks = [d for a, c, d in api.messages if c == "mait_downlink"]
    assert len(downlinks) == 1
    assert downlinks[0]["type"] == "settings"
    assert downlinks[0]["targets"]["flood_gate_1"] == {"module": 10, "channel": 1}

    # The schedule's re-check finds nothing new for the tank, but forwards the pivot's.
    api.aggregates[(TANK, "control_settings")] = settings
    api.aggregates[(PIVOT, "control_settings")] = {
        "pivot_control_1": {"app": "pivot_control"}
    }
    await app.on_schedule(None)
    downlinks = [d for a, c, d in api.messages if c == "mait_downlink"]
    assert [d["device_id"] for d in downlinks] == [TANK, PIVOT]


async def test_empty_config_is_quiet():
    api = FakeApi()
    app = await make_app(config={"modules": []}, api=api)
    await app.on_deployment(None)
    await app.on_schedule(None)
    await app.on_message_create(event(DOOVIT, "mait_uplink", UPLINK))
    assert app.get_tag("modules_text") == "No modules mapped"
    assert app.get_tag("bridge_status") == "Receiving"


EAST = "248969693098968836"
WEST = "248969694634084110"
CHANNEL = "248969691194754817"

SPLIT_CONFIG = {
    "modules": [
        {
            "module": 120,
            "device": EAST,
            "include_link": False,
            "channels": [{"channel": 1, "field": "pump_start"}],
        },
        {
            "module": 130,
            "device": EAST,
            "channels": [{"channel": 1, "field": "pressure_1"}],
        },
        {
            "module": 120,
            "device": WEST,
            "include_link": False,
            "channels": [{"channel": 3, "field": "pump_start"}],
        },
        {
            "module": 120,
            "name": "Pump Channel",
            "device": CHANNEL,
            "channels": [{"channel": 9, "field": "channel_level"}],
        },
    ],
}


async def test_split_module_fans_out_to_every_entry():
    api = FakeApi()
    app = await make_app(config=SPLIT_CONFIG, api=api)
    uplink = {
        "ts": NOW,
        "modules": [
            {
                "module": 120,
                "channels": {"1": 1, "3": 0, "9": 4.2},
                "link": {"success_pct": 80, "retries": 0, "route": []},
                "heard_ts": NOW - 2000,
            }
        ],
    }
    await app.on_message_create(event(DOOVIT, "mait_uplink", uplink))
    states = {a: d for a, c, d in api.messages if c == "io_state"}
    assert states[EAST] == {"pump_start": 1}
    assert states[WEST] == {"pump_start": 0}
    assert states[CHANNEL]["channel_level"] == 4.2
    assert states[CHANNEL]["route"] == "Base → 120"

    # Module 120 only lends the pumps a channel: it marks the channel device
    # (and the western pump, whose only module it is) online, not the eastern pump
    # whose own module 130 was not heard.
    assert {a for a, *_ in api.pings} == {WEST, CHANNEL}
    assert app.get_tag("m120_heard") == NOW - 2000
    assert app.get_tag("modules_text") == "1 of 2 heard"
    assert app.get_tag("errors_hidden") is True


async def test_split_module_commands_resolve_per_device():
    api = FakeApi()
    app = await make_app(config=SPLIT_CONFIG, api=api)
    for device in (EAST, WEST):
        await app.on_message_create(
            event(device, "io_commands", {"command": "start", "target": "pump_start"})
        )
    downlinks = [d for a, c, d in api.messages if c == "mait_downlink"]
    assert [(d["device_id"], d["module"], d["channel"]) for d in downlinks] == [
        (EAST, 120, 1),
        (WEST, 120, 3),
    ]

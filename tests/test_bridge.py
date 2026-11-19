from datetime import datetime, timezone

from mait_bridge_cloud import bridge

TANK = "248969125739677702"
PIVOT = "248969157800937480"

RAW_MAP = [
    {
        "module": 10,
        "name": "Existing Tank 1",
        "device": TANK,
        "channels": [
            {"channel": 1, "field": "flood_gate_1"},
            {"channel": 3, "field": "tank_level"},
            {"channel": 14, "field": "flow_volume"},
            {"channel": 15, "field": "flow_rate"},
            {"channel": 17, "field": "battery_v"},
        ],
    },
    {
        "module": 60,
        "device": PIVOT,
        "channels": [
            {"channel": 2, "field": "run"},
            {"channel": 3, "field": "forward"},
            {"channel": 5, "field": "reverse"},
            {"channel": 9, "field": "safety"},
            {"channel": 17, "field": "battery_v"},
        ],
    },
    {
        "module": 80,
        "device": PIVOT,
        "link_prefix": "tracker_",
        "channels": [
            {"channel": 3, "field": "latitude"},
            {"channel": 4, "field": "longitude"},
            {
                "channel": 6,
                "field": "gps_time",
                "conversion": bridge.CONVERSION_UTC_HHMMSS,
            },
            {"channel": 10, "field": "water_pressure"},
            {"channel": 17, "field": "tracker_battery_v"},
        ],
    },
]


def mappings():
    m, problems = bridge.parse_module_map(RAW_MAP)
    assert problems == []
    return m


def test_parse_defaults_and_problems():
    m, problems = bridge.parse_module_map(
        RAW_MAP
        + [
            {"module": 10, "device": TANK},
            {"module": 99},
            {"device": TANK},
            "junk",
        ]
    )
    # A repeated module number is a further entry for it, not a problem.
    assert [x.module for x in m] == [10, 60, 80, 10]
    assert m[0].channels[1].multiplier == 1.0 and m[0].channels[1].offset == 0.0
    assert m[2].link_prefix == "tracker_"
    assert len(problems) == 2
    assert bridge.parse_module_map(None) == ([], [])


def test_mapped_devices_dedupes():
    assert bridge.mapped_devices(mappings()) == [TANK, PIVOT]


def test_format_route():
    assert bridge.format_route([], 10) == "Base → 10"
    assert bridge.format_route([300, 50], 60) == "Base → 300 → 50 → 60"
    assert bridge.format_route(None, 300) == "Base → 300"


def test_build_io_state_tank():
    report = {
        "module": 10,
        "channels": {"1": 0, "3": 9.004, "14": 0, "15": 0, "17": 12.8, "22": 5},
        "link": {"success_pct": 96.84, "retries": 0.03, "route": []},
        "heard_ts": 1795050000000,
    }
    data = bridge.build_io_state(mappings()[0], report, 1795050001000)
    assert data == {
        "flood_gate_1": 0,
        "tank_level": 9.004,
        "flow_volume": 0,
        "flow_rate": 0,
        "battery_v": 12.8,
        "link_success_pct": 96.8,
        "retries": 0.03,
        "route": "Base → 10",
        "last_heard": 1795050000000,
    }


def test_build_io_state_tracker_prefix_and_gps_time():
    heard = int(datetime(2026, 11, 19, 20, 5, tzinfo=timezone.utc).timestamp() * 1000)
    report = {
        "module": 80,
        "channels": {
            "3": -22.548249,
            "4": 149.057173,
            "6": 195945,
            "10": 3.957,
            "17": 12.9,
        },
        "link": {"success_pct": 43.5, "retries": 1.29, "route": [300, 50, 60]},
        "heard_ts": heard,
    }
    data = bridge.build_io_state(mappings()[2], report, heard)
    assert data["latitude"] == -22.548249
    assert data["tracker_battery_v"] == 12.9
    assert "battery_v" not in data and "route" not in data
    assert data["tracker_route"] == "Base → 300 → 50 → 60 → 80"
    assert data["gps_time"] == int(
        datetime(2026, 11, 19, 19, 59, 45, tzinfo=timezone.utc).timestamp() * 1000
    )


def test_gps_time_after_heard_is_previous_day():
    heard = int(datetime(2026, 11, 19, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
    ms = bridge.utc_hhmmss_to_ms(235958, heard)
    assert ms == int(
        datetime(2026, 11, 18, 23, 59, 58, tzinfo=timezone.utc).timestamp() * 1000
    )
    assert bridge.utc_hhmmss_to_ms(256000, heard) is None


def test_multiplier_offset_and_missing_channels():
    m, _ = bridge.parse_module_map(
        [
            {
                "module": 1,
                "device": TANK,
                "include_link": False,
                "channels": [
                    {"channel": 3, "field": "x", "multiplier": 2, "offset": -1},
                    {"channel": 4, "field": "y"},
                ],
            }
        ]
    )
    data = bridge.build_io_state(m[0], {"module": 1, "channels": {"3": 5.5}}, 1)
    assert data == {"x": 10}


def test_uplink_reports_tolerant():
    assert bridge.uplink_reports(None) == []
    assert bridge.uplink_reports({"modules": "x"}) == []
    assert bridge.uplink_reports({"modules": [{"module": "10"}, {"nope": 1}, 3]}) == [
        {"module": "10"}
    ]


def test_command_downlink():
    cmd = {
        "command": "open",
        "target": "flood_gate_1",
        "duration_s": 1800,
        "request_id": "r1",
    }
    msg, problem = bridge.command_downlink(mappings(), TANK, cmd, 5)
    assert problem is None
    assert msg == {
        "type": "command",
        "device_id": TANK,
        "module": 10,
        "channel": 1,
        "payload": cmd,
        "ts": 5,
    }
    msg, problem = bridge.command_downlink(
        mappings(), PIVOT, {"command": "start", "target": "forward"}, 5
    )
    assert (msg["module"], msg["channel"]) == (60, 3)
    msg, problem = bridge.command_downlink(
        mappings(), TANK, {"command": "open", "target": "nope"}, 5
    )
    assert msg is None and "nope" in problem


def test_is_command_skips_replies():
    assert bridge.is_command({"command": "open"})
    assert not bridge.is_command({"request_id": "r1", "ok": True})
    assert not bridge.is_command(None)


def test_settings_downlink_and_fingerprint():
    data = {"pump_control_1": {"app": "pump_control", "start_level": 60}}
    msg = bridge.settings_downlink(mappings(), PIVOT, data, 7)
    assert msg["type"] == "settings" and msg["modules"] == [60, 80]
    assert msg["targets"]["run"] == {"module": 60, "channel": 2}
    assert msg["targets"]["latitude"] == {"module": 80, "channel": 3}
    assert bridge.settings_fingerprint(data) == bridge.settings_fingerprint(
        {"pump_control_1": {"start_level": 60, "app": "pump_control"}}
    )
    assert bridge.settings_fingerprint(data) != bridge.settings_fingerprint({})


def test_status_texts():
    assert bridge.bridge_status(None, 10, 30) == "Waiting for the first uplink"
    assert bridge.bridge_status(0, 31 * 60_000, 30) == "Waiting for the first uplink"
    assert bridge.bridge_status(1, 60_000, 30) == "Receiving"
    assert bridge.bridge_status(1, 45 * 60_000, 30).startswith("No uplink for 45")
    m = mappings()
    text, fresh, expected = bridge.modules_summary(
        m, {"10": 200 * 60_000, "60": 1}, 200 * 60_000, 120
    )
    assert (text, fresh, expected) == ("2 of 3 heard (1 stale)", 1, 3)


# -- one module split across several devices ----------------------------------

EAST = "248969693098968836"
WEST = "248969694634084110"
CHANNEL = "248969691194754817"

SPLIT_MAP = [
    {
        "module": 120,
        "name": "Eastern Diesel Pump start",
        "device": EAST,
        "include_link": False,
        "channels": [{"channel": 1, "field": "pump_start"}],
    },
    {
        "module": 130,
        "name": "Eastern Diesel Pump",
        "device": EAST,
        "channels": [
            {"channel": 1, "field": "pressure_1"},
            {"channel": 17, "field": "battery_v"},
        ],
    },
    {
        "module": 120,
        "name": "Western Diesel Pump start",
        "device": WEST,
        "include_link": False,
        "channels": [{"channel": 3, "field": "pump_start"}],
    },
    {
        "module": 140,
        "device": WEST,
        "channels": [
            {"channel": 1, "field": "pressure_1"},
            {"channel": 17, "field": "battery_v"},
        ],
    },
    {
        "module": 120,
        "name": "Pump Channel",
        "device": CHANNEL,
        "channels": [
            {"channel": 9, "field": "channel_level"},
            {"channel": 17, "field": "battery_v"},
        ],
    },
]


def split_mappings():
    m, problems = bridge.parse_module_map(SPLIT_MAP)
    assert problems == []
    return m


def test_split_module_parsed_and_indexed():
    m = split_mappings()
    index = bridge.by_module(m)
    assert [e.device_id for e in index[120]] == [EAST, WEST, CHANNEL]
    assert [e.device_id for e in index[130]] == [EAST]
    assert bridge.mapped_modules(m) == [120, 130, 140]
    assert bridge.mapped_devices(m) == [EAST, WEST, CHANNEL]
    assert bridge.module_label(m, 120) == (
        "Eastern Diesel Pump start / Western Diesel Pump start / Pump Channel"
    )
    assert bridge.module_label(m, 140) == ""


def test_split_module_io_state_per_entry():
    report = {
        "module": 120,
        "channels": {"1": 1, "3": 0, "9": 7.5, "17": 12.6},
        "link": {"success_pct": 90, "retries": 0, "route": []},
        "heard_ts": 1000,
    }
    east, west, channel = bridge.by_module(split_mappings())[120]
    assert bridge.build_io_state(east, report, 2000) == {"pump_start": 1}
    assert bridge.build_io_state(west, report, 2000) == {"pump_start": 0}
    assert bridge.build_io_state(channel, report, 2000) == {
        "channel_level": 7.5,
        "battery_v": 12.6,
        "link_success_pct": 90.0,
        "retries": 0,
        "route": "Base → 120",
        "last_heard": 1000,
    }


def test_split_module_downlink_reverse_map():
    m = split_mappings()
    cmd = {"command": "start", "target": "pump_start"}
    east, _ = bridge.command_downlink(m, EAST, cmd, 1)
    west, _ = bridge.command_downlink(m, WEST, cmd, 1)
    assert (east["module"], east["channel"]) == (120, 1)
    assert (west["module"], west["channel"]) == (120, 3)
    # Same field name on two modules of one device: each resolves to its own.
    pressure, _ = bridge.command_downlink(
        m, EAST, {"command": "x", "target": "pressure_1"}, 1
    )
    assert (pressure["module"], pressure["channel"]) == (130, 1)
    level, _ = bridge.command_downlink(
        m, CHANNEL, {"command": "x", "target": "channel_level"}, 1
    )
    assert (level["module"], level["channel"]) == (120, 9)
    # A field of the module that belongs to another device is not this device's.
    none, problem = bridge.command_downlink(
        m, EAST, {"command": "x", "target": "channel_level"}, 1
    )
    assert none is None and "channel_level" in problem

    settings = bridge.settings_downlink(m, EAST, {}, 1)
    assert settings["modules"] == [120, 130]
    assert settings["targets"] == {
        "pump_start": {"module": 120, "channel": 1},
        "pressure_1": {"module": 130, "channel": 1},
        "battery_v": {"module": 130, "channel": 17},
    }


def test_split_module_counts_once_and_online_modules():
    m = split_mappings()
    text, fresh, expected = bridge.modules_summary(
        m, {"120": 100, "130": 100}, 100, 120
    )
    assert (text, fresh, expected) == ("2 of 3 heard", 2, 3)
    assert bridge.online_modules(m, EAST) == {130}
    assert bridge.online_modules(m, CHANNEL) == {120}
    lent_only = [x for x in m if x.module == 120 and not x.include_link]
    assert bridge.online_modules(lent_only, EAST) == {120}

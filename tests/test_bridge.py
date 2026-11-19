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
    assert [x.module for x in m] == [10, 60, 80]
    assert m[0].channels[1].multiplier == 1.0 and m[0].channels[1].offset == 0.0
    assert m[2].link_prefix == "tracker_"
    assert len(problems) == 3
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

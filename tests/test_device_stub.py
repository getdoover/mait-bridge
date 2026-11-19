from mait_bridge import messages, protocol


def test_crc_matches_live_frame():
    # Snapshot request to module 10 captured on 17 Nov 2026 (CRC bytes 3B 3D).
    frame = bytes.fromhex("B2210E570A010A0000000000F0F02C")
    assert protocol.crc16_modbus(frame).to_bytes(2, "little") == bytes.fromhex("3B3D")
    assert protocol.network_id_bytes(2647) == b"\x57\x0a"


def test_uplink_shape():
    report = messages.module_report(50, {1: 0, "5": 6.45}, 1000, 76.06, 0.31, [300])
    assert report == {
        "module": 50,
        "channels": {"1": 0, "5": 6.45},
        "link": {"route": [300], "success_pct": 76.1, "retries": 0.31},
        "heard_ts": 1000,
    }
    assert messages.uplink([report], 2000) == {"ts": 2000, "modules": [report]}


def test_parse_downlink():
    assert messages.parse_downlink({"type": "command"}) == {"type": "command"}
    assert messages.parse_downlink({"type": "other"}) is None
    assert messages.parse_downlink(None) is None

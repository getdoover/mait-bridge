"""The channel messages the bridge exchanges with its cloud half.

Uplink (published on the uplink channel, default ``mait_uplink``)::

    {"ts": <ms>, "modules": [
        {"module": 10, "channels": {"1": 0, "3": 9.007, "17": 13.0},
         "link": {"success_pct": 98.5, "retries": 0, "route": [300]},
         "heard_ts": <ms>}]}

Channel values are as the radio reports them (iNTELLiNet's "Raw Value": the
wire integer ÷ 1000, so 4-20 mA inputs read in mA and digital points 0/1;
battery in volts). ``route`` lists the repeaters between the base and the
module (empty when heard direct).

Downlink (consumed from the downlink channel, default ``mait_downlink``)::

    {"type": "command", "device_id": "...", "module": 10, "channel": 1,
     "payload": {<the io_commands message>}, "ts": <ms>}
    {"type": "settings", "device_id": "...", "modules": [50],
     "targets": {"valve_1": {"module": 50, "channel": 1}},
     "payload": {<the control_settings aggregate>}, "ts": <ms>}
"""

from typing import Any


def module_report(
    module: int,
    channels: dict[int | str, Any],
    heard_ms: int,
    success_pct: float | None = None,
    retries: float | None = None,
    route: list[int] | None = None,
) -> dict:
    link: dict[str, Any] = {"route": list(route or [])}
    if success_pct is not None:
        link["success_pct"] = round(float(success_pct), 1)
    if retries is not None:
        link["retries"] = retries
    return {
        "module": int(module),
        "channels": {str(k): v for k, v in channels.items()},
        "link": link,
        "heard_ts": int(heard_ms),
    }


def uplink(reports: list[dict], ts_ms: int) -> dict:
    return {"ts": int(ts_ms), "modules": list(reports)}


def parse_downlink(data: Any) -> dict | None:
    """A downlink message if it has a known type, else None."""
    if isinstance(data, dict) and data.get("type") in ("command", "settings"):
        return data
    return None

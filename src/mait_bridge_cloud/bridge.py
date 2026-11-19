"""Pure logic of the cloud half of the bridge: no I/O, no clock reads.

Uplink: one module report (from the Doovit's uplink channel) becomes one
``io_state`` message for every device the module is mapped to. A module may be
split across several devices (each map entry takes its own subset of channels),
and several modules may feed one device.

Downlink: a command or a settings change on a mapped device becomes one message
for the Doovit's downlink channel, with the generic output ids (``target``)
translated back to radio module and channel numbers.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

CONVERSION_NONE = "None"
CONVERSION_UTC_HHMMSS = "UTC hhmmss to epoch ms"
CONVERSIONS = (CONVERSION_NONE, CONVERSION_UTC_HHMMSS)

# Link fields written alongside the mapped channels (before any prefix).
LINK_SUCCESS = "link_success_pct"
RETRIES = "retries"
ROUTE = "route"
LAST_HEARD = "last_heard"


@dataclass(frozen=True)
class ChannelMapping:
    channel: int
    field: str
    multiplier: float = 1.0
    offset: float = 0.0
    conversion: str = CONVERSION_NONE


@dataclass(frozen=True)
class ModuleMapping:
    module: int
    device_id: str
    name: str = ""
    link_prefix: str = ""
    include_link: bool = True
    channels: tuple[ChannelMapping, ...] = field(default_factory=tuple)


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != int(number):
        return None
    return int(number)


def _float(value: Any, default: float) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_module_map(raw: Any) -> tuple[list[ModuleMapping], list[str]]:
    """The module map from install config, plus a list of problems found.

    Entries without a module number or a device are dropped with a problem.
    A module number may appear in several entries, each sending its own
    channels to its own device.
    """
    mappings: list[ModuleMapping] = []
    problems: list[str] = []
    if not isinstance(raw, list):
        return mappings, problems

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        module = _int(entry.get("module"))
        device = entry.get("device")
        device_id = str(device).strip() if device not in (None, "") else ""
        if module is None:
            problems.append(f"Module map entry {index + 1} has no module number")
            continue
        if not device_id.isdigit():
            problems.append(f"Module {module} has no target device")
            continue
        channels: list[ChannelMapping] = []
        used_fields: set[str] = set()
        for ch in entry.get("channels") or []:
            if not isinstance(ch, dict):
                continue
            number = _int(ch.get("channel"))
            name = str(ch.get("field") or "").strip()
            if number is None or not name:
                problems.append(
                    f"Module {module}: a channel mapping needs a channel and a field"
                )
                continue
            if name in used_fields:
                problems.append(f"Module {module}: field {name!r} is mapped twice")
                continue
            used_fields.add(name)
            conversion = ch.get("conversion") or CONVERSION_NONE
            if conversion not in CONVERSIONS:
                conversion = CONVERSION_NONE
            channels.append(
                ChannelMapping(
                    channel=number,
                    field=name,
                    multiplier=_float(ch.get("multiplier"), 1.0),
                    offset=_float(ch.get("offset"), 0.0),
                    conversion=conversion,
                )
            )

        include_link = entry.get("include_link")
        mappings.append(
            ModuleMapping(
                module=module,
                device_id=device_id,
                name=str(entry.get("name") or "").strip(),
                link_prefix=str(entry.get("link_prefix") or "").strip(),
                include_link=True if include_link is None else bool(include_link),
                channels=tuple(channels),
            )
        )
    return mappings, problems


def by_module(mappings: list[ModuleMapping]) -> dict[int, list[ModuleMapping]]:
    """module -> every map entry for it, in map order."""
    out: dict[int, list[ModuleMapping]] = {}
    for m in mappings:
        out.setdefault(m.module, []).append(m)
    return out


def mapped_modules(mappings: list[ModuleMapping]) -> list[int]:
    """Module numbers, in first-mapped order, without repeats."""
    out: list[int] = []
    for m in mappings:
        if m.module not in out:
            out.append(m.module)
    return out


def module_label(mappings: list[ModuleMapping], module: int) -> str:
    """The labels of a module's entries, joined: 'Diesel Pumps / Eastern Diesel Pump'."""
    names: list[str] = []
    for m in mappings:
        if m.module == module and m.name and m.name not in names:
            names.append(m.name)
    return " / ".join(names)


def online_modules(mappings: list[ModuleMapping], device_id: str) -> set[int]:
    """The modules whose being heard marks a device online: those publishing
    link fields to it, or, when none does, every module that feeds it."""
    feeding = [m for m in mappings if m.device_id == str(device_id)]
    with_link = {m.module for m in feeding if m.include_link}
    return with_link or {m.module for m in feeding}


def mapped_devices(mappings: list[ModuleMapping]) -> list[str]:
    """Target device ids, in first-mapped order, without repeats."""
    out: list[str] = []
    for m in mappings:
        if m.device_id not in out:
            out.append(m.device_id)
    return out


# -- uplink ------------------------------------------------------------------


def format_route(route: Any, module: int) -> str:
    """'Base → 300 → 50 → 60' from the relay hops ``[300, 50]`` of module 60.

    ``route`` lists the repeaters between the base and the module; an empty or
    missing route means the module is heard direct.
    """
    hops: list[str] = []
    if isinstance(route, (list, tuple)):
        hops = [str(h) for h in route if h is not None and str(h).strip()]
    elif isinstance(route, str) and route.strip():
        hops = [route.strip()]
    if not hops or hops[-1] != str(module):
        hops.append(str(module))
    return " → ".join(["Base", *hops])


def utc_hhmmss_to_ms(value: Any, heard_ms: int) -> int | None:
    """Epoch ms for a UTC time of day given as hhmmss (e.g. 195945), on the UTC
    date it was heard. A time later than the heard time belongs to the day before."""
    number = _int(value)
    if number is None or number < 0:
        return None
    hh, rest = divmod(number, 10000)
    mm, ss = divmod(rest, 100)
    if hh > 23 or mm > 59 or ss > 59:
        return None
    heard = datetime.fromtimestamp(heard_ms / 1000, tz=timezone.utc)
    stamp = heard.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    ms = int(stamp.timestamp() * 1000)
    if ms > heard_ms + 60_000:
        ms -= 86_400_000
    return ms


def convert(mapping: ChannelMapping, raw: Any, heard_ms: int) -> Any:
    if mapping.conversion == CONVERSION_UTC_HHMMSS:
        return utc_hhmmss_to_ms(raw, heard_ms)
    if raw is None or isinstance(raw, bool):
        return raw
    try:
        value = float(raw) * mapping.multiplier + mapping.offset
    except (TypeError, ValueError):
        return None
    value = round(value, 6)
    if value == int(value) and abs(value) < 2**53:
        return int(value)
    return value


def _channels(report: dict) -> dict[int, Any]:
    raw = report.get("channels")
    out: dict[int, Any] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            number = _int(key)
            if number is not None:
                out[number] = value
    return out


def build_io_state(mapping: ModuleMapping, report: dict, received_ms: int) -> dict:
    """The ``io_state`` message for one module report.

    Mapped channels the report does not carry are left out, so a partial report
    never clears a reading another module wrote to the same device.
    """
    heard_ms = _int(report.get("heard_ts")) or received_ms
    channels = _channels(report)
    data: dict[str, Any] = {}
    for ch in mapping.channels:
        if ch.channel not in channels:
            continue
        value = convert(ch, channels[ch.channel], heard_ms)
        if value is not None:
            data[ch.field] = value

    if mapping.include_link:
        link = report.get("link") if isinstance(report.get("link"), dict) else {}
        p = mapping.link_prefix
        success = link.get("success_pct")
        if isinstance(success, (int, float)) and not isinstance(success, bool):
            data[p + LINK_SUCCESS] = round(float(success), 1)
        retries = link.get("retries")
        if isinstance(retries, (int, float)) and not isinstance(retries, bool):
            data[p + RETRIES] = retries
        data[p + ROUTE] = format_route(link.get("route"), mapping.module)
        data[p + LAST_HEARD] = heard_ms
    return data


def uplink_reports(message: Any) -> list[dict]:
    """The module reports in an uplink message (tolerant of junk)."""
    if not isinstance(message, dict):
        return []
    modules = message.get("modules")
    if not isinstance(modules, list):
        return []
    return [
        m for m in modules if isinstance(m, dict) and _int(m.get("module")) is not None
    ]


# -- downlink ----------------------------------------------------------------


def device_targets(mappings: list[ModuleMapping], device_id: str) -> dict[str, dict]:
    """field -> {"module", "channel"} for every mapped output of a device.

    A field written by two modules of the same device keeps the first one.
    """
    out: dict[str, dict] = {}
    for m in mappings:
        if m.device_id != str(device_id):
            continue
        for ch in m.channels:
            out.setdefault(ch.field, {"module": m.module, "channel": ch.channel})
    return out


def device_modules(mappings: list[ModuleMapping], device_id: str) -> list[int]:
    return mapped_modules([m for m in mappings if m.device_id == str(device_id)])


def is_command(data: Any) -> bool:
    """A command message, as opposed to the edge's reply on the same channel."""
    return isinstance(data, dict) and bool(data.get("command"))


def command_downlink(
    mappings: list[ModuleMapping], device_id: str, data: dict, now_ms: int
) -> tuple[dict | None, str | None]:
    """The downlink message for one command, or ``(None, problem)``."""
    target = str(data.get("target") or "").strip()
    resolved = device_targets(mappings, device_id).get(target)
    if resolved is None:
        return None, f"Command {data.get('command')!r} for unmapped target {target!r}"
    return (
        {
            "type": "command",
            "device_id": str(device_id),
            "module": resolved["module"],
            "channel": resolved["channel"],
            "payload": data,
            "ts": now_ms,
        },
        None,
    )


def settings_fingerprint(data: Any) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def settings_downlink(
    mappings: list[ModuleMapping], device_id: str, data: dict, now_ms: int
) -> dict:
    """The downlink message for a device's settings aggregate. ``targets`` lets
    the edge translate every output id inside the settings to module/channel."""
    return {
        "type": "settings",
        "device_id": str(device_id),
        "modules": device_modules(mappings, device_id),
        "targets": device_targets(mappings, device_id),
        "payload": data,
        "ts": now_ms,
    }


# -- status ------------------------------------------------------------------


def bridge_status(last_uplink_ms: int | None, now_ms: int, timeout_min: float) -> str:
    if not last_uplink_ms:
        return "Waiting for the first uplink"
    age_min = (now_ms - last_uplink_ms) / 60_000
    if age_min > timeout_min:
        return f"No uplink for {age_min:.0f} min"
    return "Receiving"


def modules_summary(
    mappings: list[ModuleMapping], heard: dict[str, int], now_ms: int, stale_min: float
) -> tuple[str, int, int]:
    """'N of M heard (K stale)' plus the fresh count and the expected count.
    A module split across several devices counts once."""
    modules = mapped_modules(mappings)
    expected = len(modules)
    fresh = stale = 0
    for module in modules:
        ts = heard.get(str(module))
        if not ts:
            continue
        if (now_ms - ts) / 60_000 > stale_min:
            stale += 1
        else:
            fresh += 1
    text = f"{fresh + stale} of {expected} heard"
    if stale:
        text += f" ({stale} stale)"
    return text, fresh, expected

"""Pure logic of the cloud half of the bridge: no I/O, no clock reads.

The map comes from one of two places:

- the **mapping page** on the Doovit, saved in the Doovit's ``mait_map``
  channel: one row per module channel, each pointing at one input of one app on
  one device (``io_state.<app key>.<point>``, the app's automatic address), or
  at a plain field for an app that reads an explicit path;
- the older **Module Map** in install config (fields by name), used only while
  the mapping page has never been saved.

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

# Link fields written alongside the mapped channels (before any prefix), by
# the older config map.
LINK_SUCCESS = "link_success_pct"
RETRIES = "retries"
ROUTE = "route"
LAST_HEARD = "last_heard"

# A module's link statistics, and the point ids of an app that takes all four
# (Link Health) under the mapping page's "radio link" rows.
LINK_STATS = ("success_pct", "retries", "route", "last_heard")
LINK_POINTS = {
    "success_pct": "link_success",
    "retries": "retries",
    "route": "route",
    "last_heard": "last_heard",
}
LEGACY_LINK_FIELDS = {
    "success_pct": LINK_SUCCESS,
    "retries": RETRIES,
    "route": ROUTE,
    "last_heard": LAST_HEARD,
}

Path = tuple[str, ...]


@dataclass(frozen=True)
class ChannelMapping:
    channel: int
    path: Path
    multiplier: float = 1.0
    offset: float = 0.0
    conversion: str = CONVERSION_NONE
    # Who reads it: the app install and its point id. An output's point id is
    # the target its commands carry. Empty app_key = a plain field (old map).
    app_key: str = ""
    point: str = ""

    @property
    def field(self) -> str:
        return ".".join(self.path)


@dataclass(frozen=True)
class ModuleMapping:
    module: int
    device_id: str
    name: str = ""
    channels: tuple[ChannelMapping, ...] = field(default_factory=tuple)
    # Where the module's link statistics go: ((stat, path), ...), stat from
    # LINK_STATS. Empty = this entry publishes no link fields.
    link_paths: tuple[tuple[str, Path], ...] = field(default_factory=tuple)

    @property
    def include_link(self) -> bool:
        return bool(self.link_paths)


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
            channels.append(
                ChannelMapping(
                    channel=number,
                    path=(name,),
                    point=name,
                    **_scaling(ch),
                )
            )

        include_link = entry.get("include_link")
        prefix = str(entry.get("link_prefix") or "").strip()
        link_paths: tuple[tuple[str, Path], ...] = ()
        if include_link is None or bool(include_link):
            link_paths = tuple(
                (stat, (prefix + LEGACY_LINK_FIELDS[stat],)) for stat in LINK_STATS
            )
        mappings.append(
            ModuleMapping(
                module=module,
                device_id=device_id,
                name=str(entry.get("name") or "").strip(),
                channels=tuple(channels),
                link_paths=link_paths,
            )
        )
    return mappings, problems


def _scaling(row: dict) -> dict:
    conversion = row.get("conversion") or CONVERSION_NONE
    if conversion not in CONVERSIONS:
        conversion = CONVERSION_NONE
    return {
        "multiplier": _float(row.get("multiplier"), 1.0),
        "offset": _float(row.get("offset"), 0.0),
        "conversion": conversion,
    }


def parse_path(value: Any, state_channel: str = "io_state") -> Path | None:
    """``('pump_control_1', 'pump_1')`` from ``'$io_state.pump_control_1.pump_1'``.

    None for anything that is not a path into the state channel.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("$"):
        return None
    body = text[1:]
    channel, sep, rest = body.replace(":", ".", 1).partition(".")
    if not sep or channel.strip() != state_channel:
        return None
    parts = tuple(p.strip() for p in rest.split(".") if p.strip())
    return parts or None


def map_has_rows(raw: Any) -> bool:
    """Whether the mapping page has ever been saved (an empty saved map counts)."""
    return isinstance(raw, dict) and isinstance(raw.get("rows"), list)


def parse_map(
    raw: Any,
    state_channel: str = "io_state",
    device_names: dict[str, str] | None = None,
) -> tuple[list[ModuleMapping], list[str]]:
    """The map saved by the mapping page (the Doovit's ``mait_map`` aggregate).

    ``{"version": 1, "rows": [...]}`` with two kinds of row:

    - a channel row ``{"module", "channel", "device", "app_key", "point",
      "path", "multiplier", "offset", "conversion"}``: the module channel's
      value goes to ``path`` on the device;
    - a radio-link row ``{"module", "link": true, "device", "app_key",
      "paths": {"success_pct", "retries", "route", "last_heard"}}``: the
      module's link statistics go to those paths. At most one per module (a
      module has one radio); one with no device and no app is skipped.

    Rows are grouped into one ModuleMapping per (module, device), in row order.
    """
    names = device_names or {}
    problems: list[str] = []
    if not map_has_rows(raw):
        return [], problems

    groups: dict[tuple[int, str], dict] = {}
    seen_channels: set[tuple[int, int, str]] = set()
    linked: set[int] = set()
    seen_paths: dict[tuple[str, Path], str] = {}

    def group(module: int, device_id: str) -> dict:
        key = (module, device_id)
        if key not in groups:
            groups[key] = {"channels": [], "link": ()}
        return groups[key]

    for index, row in enumerate(raw["rows"]):
        if not isinstance(row, dict):
            continue
        module = _int(row.get("module"))
        device = row.get("device")
        device_id = str(device).strip() if device not in (None, "") else ""
        where = f"Module {module}" if module is not None else f"Row {index + 1}"
        if module is None:
            problems.append(f"Row {index + 1} has no module number")
            continue
        app_key = str(row.get("app_key") or "").strip()
        if row.get("link") and not device_id and not app_key:
            continue  # the module's radio link isn't shown anywhere
        if not device_id.isdigit():
            problems.append(f"{where} has a row with no device")
            continue

        if row.get("link"):
            # A module has one radio, so one radio link row.
            if module in linked:
                problems.append(f"{where}: more than one radio link row")
                continue
            linked.add(module)
            paths = row.get("paths") if isinstance(row.get("paths"), dict) else {}
            link: list[tuple[str, Path]] = []
            for stat in LINK_STATS:
                path = parse_path(paths.get(stat), state_channel)
                if path is not None:
                    link.append((stat, path))
            if not link:
                problems.append(f"{where}: its radio link row has nowhere to go")
                continue
            group(module, device_id)["link"] = tuple(link)
            continue

        number = _int(row.get("channel"))
        if number is None:
            problems.append(f"{where}: a row has no channel")
            continue
        path = parse_path(row.get("path"), state_channel)
        if path is None:
            problems.append(f"{where} channel {number}: no input chosen")
            continue
        label = f"{module}.{number}"
        if (module, number, device_id) in seen_channels:
            problems.append(f"Channel {label} is mapped twice to one device")
            continue
        if (device_id, path) in seen_paths:
            problems.append(
                f"Channels {seen_paths[(device_id, path)]} and {label} both feed "
                f"the same input on {names.get(device_id) or 'device ' + device_id}"
            )
            continue
        seen_channels.add((module, number, device_id))
        seen_paths[(device_id, path)] = label
        group(module, device_id)["channels"].append(
            ChannelMapping(
                channel=number,
                path=path,
                app_key=app_key,
                point=str(row.get("point") or path[-1]).strip(),
                **_scaling(row),
            )
        )

    mappings = [
        ModuleMapping(
            module=module,
            device_id=device_id,
            name=names.get(device_id, ""),
            channels=tuple(g["channels"]),
            link_paths=g["link"],
        )
        for (module, device_id), g in groups.items()
    ]
    return mappings, problems


def deep_merge(into: dict, other: dict) -> dict:
    """Merge ``other`` into ``into`` (nested dicts merged, other values replaced)."""
    for key, value in other.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            deep_merge(into[key], value)
        else:
            into[key] = value
    return into


def _put(data: dict, path: Path, value: Any) -> None:
    node = data
    for part in path[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = node[part] = {}
        node = nxt
    node[path[-1]] = value


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
            _put(data, ch.path, value)

    if mapping.link_paths:
        link = report.get("link") if isinstance(report.get("link"), dict) else {}
        values: dict[str, Any] = {}
        success = link.get("success_pct")
        if isinstance(success, (int, float)) and not isinstance(success, bool):
            values["success_pct"] = round(float(success), 1)
        retries = link.get("retries")
        if isinstance(retries, (int, float)) and not isinstance(retries, bool):
            values["retries"] = retries
        values["route"] = format_route(link.get("route"), mapping.module)
        values["last_heard"] = heard_ms
        for stat, path in mapping.link_paths:
            if stat in values:
                _put(data, path, values[stat])
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


def device_targets(
    mappings: list[ModuleMapping], device_id: str
) -> dict[tuple[str, str], dict]:
    """(app key, point) -> {"module", "channel"} for every mapped channel of a
    device. A plain field (old map) has an empty app key.

    A point written by two modules of the same device keeps the first one.
    """
    out: dict[tuple[str, str], dict] = {}
    for m in mappings:
        if m.device_id != str(device_id):
            continue
        for ch in m.channels:
            out.setdefault(
                (ch.app_key, ch.point), {"module": m.module, "channel": ch.channel}
            )
    return out


def resolve_target(
    mappings: list[ModuleMapping], device_id: str, app_key: str, target: str
) -> dict | None:
    """The module channel a command for ``target`` from ``app_key`` goes to.

    The app's own point first, then a plain field of that name (old map), then
    any app's point of that name on the device when exactly one matches."""
    targets = device_targets(mappings, device_id)
    found = targets.get((app_key, target)) or targets.get(("", target))
    if found is not None:
        return found
    matches = [v for (k, p), v in targets.items() if p == target]
    return matches[0] if len(matches) == 1 else None


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
    app_key = str(data.get("app_key") or "").strip()
    resolved = resolve_target(mappings, device_id, app_key, target)
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
    the edge translate every output id inside the settings (under each app's
    key) to module/channel."""
    return {
        "type": "settings",
        "device_id": str(device_id),
        "modules": device_modules(mappings, device_id),
        "targets": [
            {"app_key": app_key, "target": point, **where}
            for (app_key, point), where in device_targets(mappings, device_id).items()
        ],
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

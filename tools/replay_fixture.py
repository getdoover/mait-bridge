"""Play a recorded fixture into a Doovit's uplink channel, as MAIT Bridge does.

The fixture holds a few samples per radio module (raw values as the radio
reports them). Each sample index becomes one live uplink round with current
timestamps, published a fixed interval apart, so the cloud half and every app
downstream of it see an ordinary, live-looking day.

Fixture shape::

    {"modules": [{"module": 10, "route": [], "link_success_pct": 96.8,
                  "retries_avg": 0.03,
                  "samples": [{"offset_min": 0, "channels": {"3": 9.004, ...}}, ...]}]}

Usage::

    uv run python tools/replay_fixture.py FIXTURE --agent 249020530978490113 \
        --profile dv2 [--rounds 6] [--interval 120] [--utc-time-channel 80:6] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mait_bridge.messages import module_report, uplink  # noqa: E402


def build_rounds(fixture: dict, rounds: int | None) -> list[list[dict]]:
    """Per round, the (module, sample) pairs to send: sample i of every module."""
    modules = [m for m in fixture.get("modules", []) if m.get("samples")]
    depth = max((len(m["samples"]) for m in modules), default=0)
    if rounds is not None:
        depth = min(depth, rounds)
    out = []
    for i in range(depth):
        out.append(
            [
                {"module": m, "sample": m["samples"][i]}
                for m in modules
                if i < len(m["samples"])
            ]
        )
    return out


def utc_hhmmss(ms: int) -> int:
    t = time.gmtime(ms / 1000)
    return t.tm_hour * 10000 + t.tm_min * 100 + t.tm_sec


def round_message(
    entries: list[dict], now_ms: int, time_channels: set[tuple[int, str]] = frozenset()
) -> dict:
    reports = []
    for n, entry in enumerate(entries):
        m = entry["module"]
        # Spread the heard times over the last minute, like a real poll cycle.
        heard = now_ms - (len(entries) - n) * 2000
        channels = dict(entry["sample"].get("channels") or {})
        for ch in channels:
            if (int(m["module"]), str(ch)) in time_channels:
                # A recorded time of day moves to the replay's time, like every
                # other timestamp in the round.
                channels[ch] = utc_hhmmss(heard)
        reports.append(
            module_report(
                m["module"],
                channels,
                heard,
                success_pct=m.get("link_success_pct"),
                retries=m.get("retries_avg"),
                route=m.get("route") or [],
            )
        )
    return uplink(reports, now_ms)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--agent", required=True, help="Doovit agent id")
    parser.add_argument("--profile", default="dv2", help="Doover CLI profile")
    parser.add_argument("--channel", default="mait_uplink")
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument(
        "--interval", type=float, default=120.0, help="seconds between rounds"
    )
    parser.add_argument(
        "--utc-time-channel",
        action="append",
        default=[],
        metavar="MODULE:CH",
        help="a channel holding a UTC time of day (hhmmss), re-stamped to the "
        "replay time, e.g. 80:6 for a GPS tracker; repeatable",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    time_channels = set()
    for item in args.utc_time_channel:
        module, _, ch = item.partition(":")
        time_channels.add((int(module), ch))

    fixture = json.loads(args.fixture.read_text())
    rounds = build_rounds(fixture, args.rounds)
    if not rounds:
        print("Fixture has no samples.", file=sys.stderr)
        return 1

    client = None
    if not args.dry_run:
        from pydoover.api.data import DataClient

        client = DataClient(profile=args.profile)

    for index, entries in enumerate(rounds):
        if index:
            time.sleep(args.interval)
        now_ms = int(time.time() * 1000)
        message = round_message(entries, now_ms, time_channels)
        if client is None:
            print(json.dumps(message)[:400], "…")
            continue
        result = client.create_message(int(args.agent), args.channel, message)
        print(
            f"round {index + 1}/{len(rounds)}: {len(entries)} modules → "
            f"{args.channel} message {getattr(result, 'id', result)}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# MAIT Bridge

Connects a MAIT iNTELLiNet radio network to Doover. Two apps live in this repo:

| App | Type | Runs on | Does |
|---|---|---|---|
| **MAIT Bridge** (`mait_bridge`) | Device (docker) | The Doovit wired to the MAIT base radio | Listens to the radio network and publishes every module's readings on the Doovit's `mait_uplink` channel; receives commands and settings on `mait_downlink` |
| **MAIT Bridge Cloud** (`mait_bridge_cloud`) | Processor | The same Doovit, in the cloud | Fans each module's readings out to the Doover device that represents it, keeps those devices online, and forwards their commands and settings back to the bridge |

The Doover devices the readings land on carry ordinary, hardware-neutral apps (level, flow, valve, pump,
pivot, GPS, link health) that read `$io_state.<field>` and command outputs through `io_commands`. Everything
MAIT-specific stays in these two apps.

```
MAIT base radio ──serial──► Doovit: MAIT Bridge ──mait_uplink──► MAIT Bridge Cloud ──io_state──► module devices
                                    ▲                                    │
                                    └──────────── mait_downlink ◄────────┘◄── io_commands / control_settings
```

The device app is currently a stub: it has its configuration, status page and message shapes, and logs
downlink messages, but does not yet open the serial port. See [docs/mait_bridge.md](docs/mait_bridge.md).

## Message contract

### Uplink: `mait_uplink` on the Doovit (MAIT Bridge → MAIT Bridge Cloud)

One message per publish interval, holding every module heard since the last one:

```json
{
  "ts": 1795050000000,
  "modules": [
    {
      "module": 10,
      "channels": {"1": 0, "3": 9.007, "14": 0, "15": 0, "17": 13.0},
      "link": {"success_pct": 98.5, "retries": 0, "route": [300]},
      "heard_ts": 1795049990000
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `ts` | When the message was published, epoch ms |
| `modules[].module` | Radio module number |
| `modules[].channels` | Channel number (as a string) → value as the radio reports it: the wire integer ÷ 1000, so 4–20 mA inputs read in mA and digital points 0 or 1. Channel 17 is the battery in volts. Only channels the module reported are present |
| `modules[].link.success_pct` | Replies heard ÷ requests sent to this module, % |
| `modules[].link.retries` | Average extra transmissions per request |
| `modules[].link.route` | Repeaters between the base and the module, e.g. `[300, 50]`; empty when heard direct |
| `modules[].heard_ts` | When the module's reply was heard, epoch ms |

### Fan-out: `io_state` on each module device (MAIT Bridge Cloud → device apps)

For every module report, MAIT Bridge Cloud writes one `io_state` message to the module's target device and
merges the same fields into that device's `io_state` aggregate:

```json
{"flood_gate_1": 0, "tank_level": 9.007, "flow_volume": 0, "flow_rate": 0, "battery_v": 13.0,
 "link_success_pct": 98.5, "retries": 0, "route": "Base → 300 → 10", "last_heard": 1795049990000}
```

Mapped fields are `raw × multiplier + offset`. The link fields (`link_success_pct`, `retries`, `route`,
`last_heard`) can carry a prefix, so a second module on the same device (a GPS tracker on a pivot) does
not overwrite the main module's link health. Each target device's connection status is refreshed to the
time its module was heard.

### Downlink: `mait_downlink` on the Doovit (MAIT Bridge Cloud → MAIT Bridge)

A command published on a module device's `io_commands` channel:

```json
{"type": "command", "device_id": "248969125739677702", "module": 10, "channel": 1,
 "payload": {"command": "open", "target": "flood_gate_1", "duration_s": 1800, "params": {},
             "request_id": "…", "app_key": "valve_control_1", "app": "valve_control", "ts": 1795050000000},
 "ts": 1795050000500}
```

A change to a module device's `control_settings` aggregate (the settings the edge enforces):

```json
{"type": "settings", "device_id": "248969152092489731", "modules": [50],
 "targets": {"valve_1": {"module": 50, "channel": 1}, "valve_3": {"module": 50, "channel": 3}},
 "payload": {"valve_control_1": {"app": "valve_control", "schema": 1, "…": "…"}},
 "ts": 1795050000500}
```

`module` / `channel` (and `targets` for settings) translate the generic output ids back to radio addresses,
using the module map in reverse: a command's `target` is the field name the output is published under.
Replies the edge writes back to `io_commands` (no `command` key) are not forwarded. Settings are
forwarded only when they change.

## Development

```sh
uv sync
uv run pytest
uv run export-config-cloud && uv run export-ui-cloud     # regenerate schemas locally (not committed)
```

`tools/replay_fixture.py` plays a recorded fixture into a Doovit's `mait_uplink` channel exactly as the
device app will, for end-to-end tests of the cloud half. `tools/barmount_module_map.json` is the module
map of the first site.

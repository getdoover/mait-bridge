# Building apps for a MAIT site

Read this before you build a new cloud app for a device on a MAIT-bridged site, or change an existing one so
the bridge can feed it. It explains how readings and commands find their way between a radio module and an
app, and the few rules an app has to follow for that to work. Nothing here makes an app MAIT-specific: an app
that follows it works the same with any edge source.

## The picture

```
MAIT radio modules ──radio──▶ Doovit: MAIT Bridge (DEV) ──mait_uplink──▶ MAIT Bridge Cloud (PRO, on the Doovit)
                                                                              │  uses the map on mait_map
                                                                              ▼
                                         each site device:  io_state  ──▶  its apps (Pump Control, Valve Control, …)
                                                            io_commands ◀── commands from those apps
```

- **One Doover device per thing an operator thinks of** (a tank, a pump, a pivot), not per radio module. One
  module can feed several devices, and several modules can feed one device.
- **The apps are generic.** They never mention MAIT, radio modules or module numbers. They take raw signals
  (mA, V, counts, 0/1, degrees) and do their own scaling. They are remote controls: the edge is the source
  of truth, and the page shows reported state, never assumed state.
- **The map is the only place a channel is wired.** It lives on the Doovit's `mait_map` channel and is
  edited on the **Module Mapping** page inside MAIT Bridge Cloud. Each row says: module *M*, channel *C* goes
  to this input of this app on this device. Nobody types field names, and no app setting needs changing.

## Rule 1: every input has an automatic address

Every input an app reads (a "message path" setting) has a fixed **point id**. When the setting is left
**blank** (make blank the default), the app reads that input from its automatic address:

```
$io_state.<APP_KEY>.<point id>          e.g.  $io_state.pump_control_2.pump_1
```

That is exactly where the bridge writes a channel mapped to that input. Because the address includes the
install's app key, two installs of one app on one device never collide.

- An explicit path (`$io_state.x`, `$on_dm_event.y`) still works and wins, so the app stays usable with other
  edge sources.
- Keep `io_state` in the app's default subscriptions.
- **Point ids are fixed per app**, and are built from config the operator already gives: a valve's or pump's
  **Target ID**, a reading's **Key**. Never use a list position, which shifts when items are reordered.
- **Controls (outputs) use their Target ID as their point id.** A MAIT output channel reports its own state,
  so the output's reported state arrives at `$io_state.<APP_KEY>.<target>`, and commands for it carry that
  same `target`.
- **Optional inputs** (a fault, a position, a speed) show nothing until a value has ever arrived at their
  automatic address, then are shown from then on, even when stale or faulted. Keep an "ever seen" record in
  a tag. Never hide a field because it reads zero or has gone quiet: a dead field is a live field.

## Rule 2: publish an `io_points` tag

So the mapping page can list an app's inputs by name, every app sets one tag, `io_points`, under its own
app key in `tag_values`. Write it on deployment and on every scheduled run, and only when it changes:

```json
{"version": 1, "points": [
  {"id": "flood_gate_1", "label": "Flood Gate 1", "kind": "output",
   "path": "$io_state.valve_control_1.flood_gate_1", "auto": true},
  {"id": "flood_gate_1_position", "label": "Flood Gate 1 position", "kind": "input",
   "path": "$io_state.valve_control_1.flood_gate_1_position", "auto": true}
]}
```

| Field | Meaning |
|---|---|
| `id` | The point id. Unique within the install |
| `label` | Plain words an operator understands, built from names they gave in config ("Pump 1", "Suction Pressure", "Battery voltage"). Never an id with underscores |
| `kind` | `output`: a control, commanded with `target` = `id`, with its reported state on `path`. `input`: read-only |
| `path` | The path the app actually reads, automatic or explicit |
| `auto` | Whether `path` is the automatic address. The page only lists automatic inputs as unwired |

List outputs first, then inputs, each in config order. Leave out points switched off in config. An app or
role with no inputs publishes `{"version": 1, "points": []}`.

An app without the tag still shows on the mapping page: the page offers every `$io_state.x` path found in the
app's config, named after the app, and the bridge writes to that path. That is how Analog Level Sensor (tank
levels) is mapped today. It works, but the app's labels are poorer and the config can't use a blank default.

## Rule 3: commands and settings

- **Commands** go on the device's `io_commands` channel, one message each:
  `{"command": "<verb>", "target": "<Target ID>", "duration_s": 1800, "params": {}, "request_id": "<uuid4>",
  "app_key": "<APP_KEY>", "app": "<app name>", "ts": <ms>}`. The bridge resolves (`app_key`, `target`) to the
  module and channel the map sends that output to. The edge may reply on the same channel with
  `{"request_id", "ok", "error"}`. Show the reply if there is one; never require it.
- **Settings the edge must enforce** (run limits, auto-fill levels, schedules) go in the device's
  `control_settings` aggregate under the app's key. Merge, don't clobber other apps' keys.
- The bridge only hears a device's commands if it subscribes to `<device id>-io_commands` (and
  `<device id>-control_settings`). The mapping page warns when a device with mapped controls is missing.

## Radio link statistics

Each module has one radio, so the map has one **radio link** row per module. It sends the module's link
success %, retries, route and last-heard time to one app. Any app that offers these point ids can take them:

| Point id | Value |
|---|---|
| `link_success` | Link success, % |
| `retries` | Average retries per poll |
| `route` | Relay route, e.g. "Base → 300 → 50 → 60" |
| `last_heard` | When the module was last heard, epoch ms |

Link Health is the app that does. A module's battery voltage is an ordinary channel (usually 17), mapped to
Link Health's `battery_voltage` input.

## The apps that follow these rules

| App (getdoover repo) | Point ids |
|---|---|
| Valve Control (`valve-control`) | each valve: `<target>` (output), `<target>_position` |
| Pump Control (`pump-control`), Pump role | each pump: `<target>` (output), `<target>_fault`; each enabled reading: its key. Auto-fill role: none |
| Pivot Control (`pivot-control`) | `<run target>`, `<forward target>`, `<reverse target>` (outputs); `speed`, `safety`, `pressure`, `schedule_state` |
| Flow Meter Processor (`flow-meter-processor`) | `flow` |
| GPS Tracker (`gps-tracker`) | `latitude`, `longitude`, `altitude`, `satellites`, `hdop`, `fix_status`, `gps_time` |
| Link Health (`link-health`) | `battery_voltage`, `link_success`, `success_count`, `attempt_count`, `retries`, `rssi`, `snr`, `route`, `last_heard` |

Each of those repos has an "automatic address" section in its README and tests that cover it. Use them as
the model.

## Checklist for a new or changed app

1. Every message-path setting defaults to blank, and blank resolves to `$io_state.<APP_KEY>.<point id>`.
   Every place the app reads a value (incoming messages and any aggregate refresh) uses the resolved path,
   including values nested under the app key.
2. Point ids come from stable config (target ids, keys), and outputs use their target id.
3. Optional inputs stay hidden until first seen, then stay shown.
4. `io_points` is published on deploy and schedule, only when it changes, with plain-word labels.
5. Commands follow Rule 3.
6. Tests cover path resolution (blank and explicit), the point list, and a nested message like
   `{"<app_key>": {"<point>": 1}}`.
7. After releasing, set existing installs' path settings to blank (an install keeps whatever path it has
   saved), redeploy them, and map their inputs on the Module Mapping page.
8. To check end to end without the radios, replay recorded data through the bridge:
   `uv run python tools/replay_fixture.py <fixture.json> --agent <doovit id> --profile dv2 --rounds 1`.

# MAIT Bridge Cloud

The cloud half of a MAIT radio bridge. Install it on the Doovit that runs **MAIT Bridge**. It takes the
readings the bridge publishes for every radio module and delivers each module's readings to the Doover
device that represents it, so a tank, pump or pivot gets its own device page with ordinary apps on it
(level, flow, valve, pump, pivot, GPS, link health). Commands and settings from those apps come back
through it to the bridge.

## What it does

- **Readings out.** For each module in an uplink, writes one `io_state` message to the module's target
  device with the mapped fields and the module's link health (`battery_v`, `link_success_pct`, `retries`,
  `route`, `last_heard`), and merges the same fields into the device's `io_state` aggregate.
- **Devices online.** Marks each target device as online at the time its module was heard. Devices show
  "Online N min ago. Back in …", and go offline on their own when a module stops reporting.
- **Commands back.** Forwards every command an app publishes on a target device's `io_commands` channel to
  the Doovit's `mait_downlink` channel, with the output's module and channel number.
- **Settings back.** Forwards a target device's `control_settings` aggregate (auto-fill levels,
  run limits, schedules) to `mait_downlink` whenever it changes, with every output id translated to its
  module and channel.

## Configuration

### Module Map

One entry per radio module and target device. A module whose channels belong to different things (one
module wired to two pumps' start relays and a channel level sensor) gets one entry per device, each with
its own channels; several modules may also feed one device:

| Setting | Meaning |
|---|---|
| Module Number | The module's number on the radio network |
| Label | Optional name shown on the bridge page |
| Target Device | The Doover device that receives the module's readings. Several modules may feed one device |
| Channel Mappings | Channel → field, with an optional multiplier, offset and conversion. Published value = raw × multiplier + offset. The conversion "UTC hhmmss to epoch ms" turns a GPS time of day into a timestamp |
| Publish Link Fields | Also publish the module's link health. Turn off on an entry that only lends a device a few channels, so it does not overwrite the link health of the device's own module. A device is marked online by the entries that publish link fields to it (or by every entry, if none does) |
| Link Field Prefix | Prefix for the link fields of a second module on the same device, e.g. `tracker_` |

A command's `target` is matched against the field names of the device's mappings, so an output published
as `valve_1` is commanded as `valve_1`.

### Other settings

| Setting | Default | Meaning |
|---|---|---|
| Show Devices Online | On | Refresh each target device's connection status when its module is heard |
| Expected Report Interval (min) | 15 | How often modules are expected to be heard |
| Offline After (min) | 90 | A device goes offline when its module has not been heard for this long |
| Module Stale After (min) | 120 | When a module counts as stale on the bridge page |
| Uplink Timeout (min) | 30 | When the bridge status warns that no uplink has arrived |
| Uplink / Downlink Channel | `mait_uplink` / `mait_downlink` | Channels on this device (advanced) |
| State / Command / Settings Channel | `io_state` / `io_commands` / `control_settings` | Channels on the target devices (advanced) |
| Subscriptions | `mait_uplink` | Add `<device id>-io_commands` and `<device id>-control_settings` for every target device, so commands and settings are forwarded as they happen |
| Schedule | every 5 minutes | Refreshes the page and re-checks every target device's settings |
| Devices | the device's group | The devices this app may write to. Grant the group that holds the target devices |

## Page

- **Bridge Status**: receiving, waiting, or how long since the last uplink.
- **Last Uplink**, **Modules** (heard of expected, and how many are stale), **Devices Mapped**.
- **Last Downlink** and what it was.
- **Modules Last Heard**: one row per mapped module, even when it is split across several devices.
- A warning lists problems: a module that is not in the map, a device the app may not write to, a command
  for an output that is not mapped.

## Channels

| Channel | Where | Direction |
|---|---|---|
| `mait_uplink` | This device | Read: module reports from MAIT Bridge |
| `mait_downlink` | This device | Written: commands and settings for MAIT Bridge |
| `io_state` | Each target device | Written: readings and link health |
| `doover_connection` | Each target device | Written: last heard / online status |
| `io_commands` | Each target device | Read: commands from the device's apps |
| `control_settings` | Each target device | Read: settings the edge enforces |

The message shapes are in the repository README.

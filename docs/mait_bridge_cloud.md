# MAIT Bridge Cloud

The cloud half of a MAIT radio bridge. Install it on the Doovit that runs **MAIT Bridge**. It takes the
readings the bridge publishes for every radio module and delivers each module's readings to the Doover
device that represents it, so a tank, pump or pivot gets its own device page with ordinary apps on it
(level, flow, valve, pump, pivot, GPS, link health). Commands and settings from those apps come back
through it to the bridge.

## What it does

- **Readings out.** For each module in an uplink, writes one `io_state` message to every device the module
  is mapped to, with each mapped channel's value at the input it feeds (and, where mapped, the module's
  radio link: link success, retries, route, last heard), and merges the same values into the device's
  `io_state` aggregate.
- **Devices online.** Marks each target device as online at the time its module was heard. Devices show
  "Online N min ago. Back in …", and go offline on their own when a module stops reporting.
- **Commands back.** Forwards every command an app publishes on a target device's `io_commands` channel to
  the Doovit's `mait_downlink` channel, with the output's module and channel number.
- **Settings back.** Forwards a target device's `control_settings` aggregate (auto-fill levels,
  run limits, schedules) to `mait_downlink` whenever it changes, with every output id translated to its
  module and channel.

## Mapping modules

Map modules on this app's page, under **Module Mapping**. Each row sends one radio module channel to one
input of one app on one device:

1. Add the module by its number.
2. For each channel in use: enter the channel number, pick the **device**, then pick what it **goes to**.
   That list shows every app on the device and the inputs it takes, by name ("Flood Gate 1",
   "Suction Pressure", "Battery voltage"). Controls (a valve, a pump, a pivot's run) are listed as well;
   their commands go back out on the same channel.
3. Add a **radio link** row to send the module's link success, retries, route and last-heard time to the
   device's Link Health app.
4. **Save.**

A module can be split across several devices (one row per channel), and several modules can feed one
device. The page flags a channel mapped twice, an input fed twice, an input whose app has been removed, and
devices whose controls can't reach the radios yet because the bridge isn't subscribed to their
`io_commands`. **Inputs with nothing mapped to them** lists what is still unwired on each device. Each
module shows when it was last heard.

No setting on the device's apps needs changing: an app input left blank reads its automatic address
(`io_state.<app key>.<input>`), and that is where the bridge writes it. Apps that only take an explicit
message path (for example Analog Level Sensor) are listed too; the bridge writes to that path.

The map is saved on this device's `mait_map` channel, so the Doovit's bridge has it too. A saved map
replaces the old **Module Map** setting below, which is only used until the page has been saved.

## Configuration

### Module Map (old)

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
| Map Channel | `mait_map` | Where the mapping page saves the map (advanced) |
| Subscriptions | `mait_uplink` | Add `<device id>-io_commands` and `<device id>-control_settings` for every target device, so commands and settings are forwarded as they happen |
| Schedule | every 5 minutes | Refreshes the page and re-checks every target device's settings |
| Devices | the device's group | The devices this app may write to. Grant the group that holds the target devices |

## Page

- **Bridge Status**: receiving, waiting, or how long since the last uplink.
- **Last Uplink**, **Modules** (heard of expected, and how many are stale), **Devices Mapped**.
- **Last Downlink** and what it was.
- **Map From**: the mapping page, or the old Module Map in config.
- **Module Mapping**: the mapping page above, with each module's last-heard time.
- A warning lists problems: a module that is not in the map, a device the app may not write to, a command
  for an output that is not mapped.

## Channels

| Channel | Where | Direction |
|---|---|---|
| `mait_uplink` | This device | Read: module reports from MAIT Bridge |
| `mait_downlink` | This device | Written: commands and settings for MAIT Bridge |
| `mait_map` | This device | Read: the map saved by the mapping page |
| `io_state` | Each target device | Written: readings and link health |
| `doover_connection` | Each target device | Written: last heard / online status |
| `io_commands` | Each target device | Read: commands from the device's apps |
| `control_settings` | Each target device | Read: settings the edge enforces |

The message shapes are in the repository README.

# MAIT Bridge

Connects a Doovit to a MAIT iNTELLiNet radio network. The Doovit sits on the base radio's serial link,
hears every field module's replies and publishes their readings to Doover, where **MAIT Bridge Cloud**
delivers each module's readings to the Doover device that represents it.

This release is the foundation of the bridge: configuration, status page and the channel contract. It
does not open the serial port yet and never transmits on the radio network.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| Serial Port | `/dev/ttyAMA0` | Serial device of the base radio. Mapped into the container read-only |
| Baud Rate | 9600 | Serial speed (8N1, no flow control) |
| Network ID | 2647 | Radio network id carried in every frame |
| Snapshot Poll Interval (s) | 300 | How often each module's live values are expected |
| Status Poll Interval (s) | 3600 | How often each module's status and logged records are expected |
| Uplink Publish Interval (s) | 60 | How often heard module reports are batched into one uplink message |
| Uplink Channel | `mait_uplink` | Where module reports are published (advanced) |
| Downlink Channel | `mait_downlink` | Where commands and settings arrive (advanced) |

## Page

- **Status**: connection to the base radio.
- **Serial Port**: port and speed in use.
- **Modules Heard** and **Last Uplink**.
- **Downlink**: how many commands and settings messages have arrived, and the latest one.

## Channels

| Channel | Direction | Content |
|---|---|---|
| `mait_uplink` | Published | `{"ts", "modules": [{"module", "channels", "link": {"success_pct", "retries", "route"}, "heard_ts"}]}` |
| `mait_downlink` | Received | `{"type": "command", "device_id", "module", "channel", "payload", "ts"}` or `{"type": "settings", "device_id", "modules", "targets", "payload", "ts"}` |

Channel values are as the radio reports them: 4–20 mA inputs in mA, digital points 0 or 1, battery
(channel 17) in volts. The full contract is in the repository README.

## Install

Install on the Doovit wired to the base radio, together with **MAIT Bridge Cloud** on the same device.

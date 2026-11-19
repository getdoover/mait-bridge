import logging
import time

from pydoover.docker import Application
from pydoover.models import MessageCreateEvent

from .app_config import MaitBridgeConfig
from .app_tags import MaitBridgeTags
from .app_ui import MaitBridgeUI
from .messages import parse_downlink
from .transport import SerialReceiver

log = logging.getLogger(__name__)


def describe_downlink(message: dict) -> str:
    if message["type"] == "command":
        payload = message.get("payload") or {}
        return (
            f"{payload.get('command')} → module {message.get('module')} "
            f"ch {message.get('channel')}"
        )
    return f"settings for modules {message.get('modules')}"


class MaitBridgeApplication(Application):
    """Stub of the Doovit half of the bridge.

    The finished app listens to the MAIT base radio, decodes each module's
    replies and publishes them as uplink messages (see ``messages.py``) for
    MAIT Bridge Cloud to fan out. This stub does no serial I/O: it shows its
    status, and logs the downlink messages it receives so the cloud half can be
    tested end to end.
    """

    config: MaitBridgeConfig
    tags: MaitBridgeTags
    ui: MaitBridgeUI

    config_cls = MaitBridgeConfig
    tags_cls = MaitBridgeTags
    ui_cls = MaitBridgeUI

    async def setup(self):
        self.loop_target_period = 5
        self.receiver = SerialReceiver(
            self.config.serial_port.value, self.config.baud_rate.value
        )
        self.receiver.start()
        await self.tags.port.set(
            f"{self.config.serial_port.value} @ {self.config.baud_rate.value} baud"
        )
        await self.tags.status.set("Not yet connected (stub)")
        await self.subscribe(self.config.downlink_channel.value)

    async def main_loop(self):
        # Frames will be decoded and batched into uplink messages here.
        self.receiver.drain()

    async def on_message_create(self, event: MessageCreateEvent):
        if event.channel.name != self.config.downlink_channel.value:
            return
        message = parse_downlink(event.message.data)
        if message is None:
            return
        text = describe_downlink(message)
        log.info("Downlink received (not transmitted, stub): %s", text)
        await self.tags.downlinks_received.set(
            (self.tags.downlinks_received.get() or 0) + 1
        )
        await self.tags.last_downlink.set(int(time.time() * 1000))
        await self.tags.last_downlink_text.set(text)

    async def close(self):
        self.receiver.stop()
        await super().close()

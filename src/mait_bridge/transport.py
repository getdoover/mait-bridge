"""Serial transport (placeholder). Receive-only by construction: there is no
write path in this module, and the bridge never transmits on the radio network
until it is commissioned as master.
"""

import logging

log = logging.getLogger(__name__)


class SerialReceiver:
    """Will own the serial port and hand complete frames to the protocol layer.

    The stub never opens the port: ``start`` only records the settings, so the
    app runs on any Doovit without the radio attached.
    """

    def __init__(self, port: str, baud: int):
        self.port = port
        self.baud = baud
        self.connected = False

    def start(self) -> None:
        log.info(
            "Serial receiver stub: would listen on %s @ %d baud (8N1, receive only)",
            self.port,
            self.baud,
        )

    def drain(self) -> list[bytes]:
        """Frames received since the last call. Always empty in the stub."""
        return []

    def stop(self) -> None:
        self.connected = False

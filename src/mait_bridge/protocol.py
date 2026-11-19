"""MAIT iNTELLiNet radio protocol (placeholder).

Only the framing constants and the checksum live here for now; decoding and
encoding come with the receive-only shadow phase.

Frame layout (all multi-byte fields little-endian)::

    B2 21 LEN NET(u16) HOP | PATH (u16 ..., then 00 00 00 00) | TID (u16) | CMD | PAYLOAD | CRC (u16)

- ``B2 21``  start of frame. The radio prefixes received frames with a
  ``55 55`` + zero-byte preamble; everything before ``B2 21`` is skipped.
- ``LEN``    bytes after LEN, including the CRC (total length - 3).
- ``NET``    radio network id, e.g. 2647 = ``57 0A``.
- ``HOP``    ``01`` sent by the base, ``02``.. repeated by each hop; bit 7 set
  on replies (``80`` = reply arriving at the base).
- ``PATH``   source route as module numbers, e.g. 300 → 50 → 60 → 80.
- ``TID``    transaction id, echoed by the reply.
- ``CMD``    request codes are even, the reply is request + 1
  (``2C``/``2D`` snapshot, ``36``/``37`` status, ``44``/``45`` logged record,
  ``26``/``27`` output, ``34``/``35`` interrogate).
- ``CRC``    CRC-16/MODBUS over the whole frame from ``B2``.

Reply values are a list of items: one header byte (top 3 bits = size code,
bottom 5 bits = channel - 1) and 0-8 value bytes. Integers are ÷ 1000 except
the housekeeping channels (17 battery, 20 RTC, 22 entry number, 23 records left).
"""

START = b"\xb2\x21"
DEFAULT_NETWORK_ID = 2647
BATTERY_CHANNEL = 17


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS (poly 0xA001 reflected, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def network_id_bytes(network_id: int) -> bytes:
    return int(network_id).to_bytes(2, "little")


def decode_frame(frame: bytes):
    """Decode one frame into a module report. Not implemented in the stub."""
    raise NotImplementedError("Frame decoding arrives with the shadow phase.")

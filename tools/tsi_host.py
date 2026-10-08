#!/usr/bin/env python3
"""Send SCuM v26 NFC Modem (TileLink) packets through the TRF7970A reader board.

The MSP430 firmware (APP_TILELINK in nfc_app.h) accepts one ASCII command per
line over the LaunchPad's Application UART and turns it into NFC packets:

    SOF | cmd (1) | addr (8, LE) | length (8, LE) | body | CRC-16 (2, LE) | EOF

The TRF7970A adds SOF/EOF/CRC in hardware (ISO15693 framing). This script also
computes the CRC so --dry-run can show exactly what goes on air.

Examples:
    python tools/tsi_host.py --port COM5 test
    python tools/tsi_host.py --port COM5 write 0x80000000 0807060504030201
    python tools/tsi_host.py --port COM5 load image.bin 0x80000000
    python tools/tsi_host.py --port COM5 read 0x80000000 8
    python tools/tsi_host.py --port COM5 raw 01 0000008000000000 0800000000000000 0807060504030201
    python tools/tsi_host.py --port COM5 mod 10
    python tools/tsi_host.py --port COM5 field off
    python tools/tsi_host.py --dry-run test
"""

import argparse
import sys
import time

CMD_READ = 0x00
CMD_WRITE = 0x01

FW_MAX_BODY = 8          # TILELINK_MAX_BODY in tilelink.h: body bytes per on-air packet
LINE_MAX_DATA = 32       # data bytes per "W" line (firmware line buffer is 96 chars)
RAW_MAX = 46             # bytes per "X" line

EXAMPLE_ADDR = 0x80000000
EXAMPLE_BODY = bytes([8, 7, 6, 5, 4, 3, 2, 1])

# tTrfStatus in trf79xxa.h
TRF_STATUS = [
    "TRF_IDLE", "TX_COMPLETE", "RX_COMPLETE", "TX_ERROR", "RX_WAIT",
    "RX_WAIT_EXTENSION", "TX_WAIT", "PROTOCOL_ERROR", "COLLISION_ERROR",
    "NO_RESPONSE_RECEIVED", "NO_RESPONSE_RECEIVED_15693",
]


def crc16_x25(data: bytes) -> int:
    """CRC-16 per the NFC Modem spec / ISO15693: poly 0x8408 reflected, init and xorout 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def build_frame(cmd: int, addr: int, length: int, body: bytes = b"") -> bytes:
    """cmd..body bytes, as written to the TRF7970A FIFO."""
    return bytes([cmd]) + addr.to_bytes(8, "little") + length.to_bytes(8, "little") + body


def on_air(frame: bytes) -> bytes:
    """Frame plus the CRC the TRF7970A appends (little endian)."""
    return frame + crc16_x25(frame).to_bytes(2, "little")


def self_check():
    assert crc16_x25(bytes([1, 2, 3, 4])) == 0x3991, "CRC does not match the spec example 0x3991"
    example = on_air(build_frame(CMD_WRITE, EXAMPLE_ADDR, len(EXAMPLE_BODY), EXAMPLE_BODY))
    assert example[-2:] == bytes([0x31, 0x2C]), "CRC does not match the spec packet example 0x312C"


def parse_int(text: str) -> int:
    return int(text, 0) if text.lower().startswith("0x") else int(text, 16)


def parse_hex(parts) -> bytes:
    text = "".join(parts).replace("0x", "").replace("_", "")
    try:
        return bytes.fromhex(text)
    except ValueError:
        sys.exit(f"invalid hex data: {text}")


def fmt_frame(data: bytes) -> str:
    """Hex with the header fields separated, matching the wiki table layout."""
    if len(data) < 17:
        return data.hex(" ")
    body_end = len(data) - 2
    return " | ".join(part.hex() for part in (data[:1], data[1:9], data[9:17], data[17:body_end], data[body_end:]) if part)


class TsiError(Exception):
    pass


class Board:
    def __init__(self, port: str, baud: int, timeout: float):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        # End any partial line left in the firmware and drop stale output (e.g. the boot banner)
        self.ser.write(b"\n")
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def command(self, line: str) -> str:
        self.ser.write(line.encode("ascii") + b"\n")
        while True:
            reply = self.ser.readline().decode("ascii", "replace").strip()
            if not reply:
                raise TsiError(f"no reply to '{line}' (check port, baud and RXD/TXD jumpers)")
            if reply == "TILELINK READY":
                continue  # board was reset while we were talking to it
            if reply == "OK" or reply.startswith("DATA"):
                return reply
            if reply.startswith("ERR"):
                code = reply[4:]
                try:
                    name = TRF_STATUS[int(code, 16)]
                except (ValueError, IndexError):
                    name = code
                raise TsiError(f"'{line}' failed: {name}")
            raise TsiError(f"unexpected reply to '{line}': {reply}")


class DryRun:
    def command(self, line: str) -> str:
        print(f"> {line}")
        return "OK"


def show_write_packets(addr: int, data: bytes):
    """Print the on-air packets the firmware will emit for a write."""
    for offset in range(0, len(data), FW_MAX_BODY):
        chunk = data[offset:offset + FW_MAX_BODY]
        print("  on air:", fmt_frame(on_air(build_frame(CMD_WRITE, addr + offset, len(chunk), chunk))))


def do_write(board, addr: int, data: bytes, dry_run: bool, progress: bool = False):
    for offset in range(0, len(data), LINE_MAX_DATA):
        chunk = data[offset:offset + LINE_MAX_DATA]
        board.command(f"W {addr + offset:08X} {chunk.hex().upper()}")
        if dry_run:
            show_write_packets(addr + offset, chunk)
        elif progress:
            done = offset + len(chunk)
            print(f"\r  {done}/{len(data)} bytes ({100 * done // len(data)}%)", end="", flush=True)
    if progress and not dry_run:
        print()


def main():
    self_check()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="Application UART COM port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=3.0, help="seconds to wait for each reply")
    parser.add_argument("--dry-run", action="store_true", help="print commands and on-air packets, no serial")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("test", help="send the NFC Modem wiki example write packet")
    p = sub.add_parser("write", help="write hex data to chip memory")
    p.add_argument("addr")
    p.add_argument("data", nargs="+")
    p = sub.add_parser("load", help="write a binary file to chip memory")
    p.add_argument("file")
    p.add_argument("addr")
    p = sub.add_parser("read", help="read bytes from chip memory (best effort)")
    p.add_argument("addr")
    p.add_argument("length")
    p = sub.add_parser("raw", help="send raw cmd..body bytes (CRC added by the TRF7970A)")
    p.add_argument("data", nargs="+")
    p = sub.add_parser("mod", help="modulation: 100 (OOK, default) or 10 (ASK)")
    p.add_argument("depth", choices=["10", "100"])
    p = sub.add_parser("field", help="RF field on/off")
    p.add_argument("state", choices=["on", "off"])
    args = parser.parse_args()

    if args.dry_run:
        board = DryRun()
    elif args.port:
        board = Board(args.port, args.baud, args.timeout)
    else:
        parser.error("--port is required unless --dry-run is given")

    try:
        # No "F 1" here: the firmware turns the field on for the first packet and keeps it on.
        # "F 1" resets the TRF, which blips the field and could reset a field-powered chip.
        if args.action == "test":
            board.command("T")
            print("on air:", fmt_frame(on_air(build_frame(CMD_WRITE, EXAMPLE_ADDR, len(EXAMPLE_BODY), EXAMPLE_BODY))))
            print("OK")

        elif args.action == "write":
            do_write(board, parse_int(args.addr), parse_hex(args.data), args.dry_run)
            print("OK")

        elif args.action == "load":
            with open(args.file, "rb") as f:
                data = f.read()
            if not data:
                sys.exit(f"{args.file} is empty")
            addr = parse_int(args.addr)
            print(f"loading {len(data)} bytes to 0x{addr:08X}")
            start = time.time()
            do_write(board, addr, data, args.dry_run, progress=True)
            print(f"OK ({time.time() - start:.1f} s)")

        elif args.action == "read":
            addr, length = parse_int(args.addr), parse_int(args.length)
            if not 0 < length <= 0xFF:
                sys.exit("length must be 1..0xFF")
            if args.dry_run:
                print("  on air:", fmt_frame(on_air(build_frame(CMD_READ, addr, length))))
            reply = board.command(f"R {addr:08X} {length:X}")
            print(reply)

        elif args.action == "raw":
            data = parse_hex(args.data)
            if not 0 < len(data) <= RAW_MAX:
                sys.exit(f"raw frame must be 1..{RAW_MAX} bytes")
            if args.dry_run:
                print("  on air:", fmt_frame(on_air(data)))
            print(board.command(f"X {data.hex().upper()}"))

        elif args.action == "mod":
            print(board.command(f"M {args.depth}"))

        elif args.action == "field":
            print(board.command("F 1" if args.state == "on" else "F 0"))

    except TsiError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()

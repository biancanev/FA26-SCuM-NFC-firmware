#!/usr/bin/env python3
"""Print the bitstream the TRF7970A modulates for a SCuM v26 NFC Modem packet.

The TRF sends SOF | data | EOF using ISO15693 high data rate, 1 out of 4 PPM:

  - FIFO bytes go out in order, each FIFO byte LSB first, two bits at a time.
  - Each bit pair is one 75.52 us symbol made of 8 slots of 9.44 us
    (128 carrier cycles). Pair value n puts the pause in slot 2n+1.
  - SOF = 8 slots, EOF = 4 slots (ISO/IEC 15693-2, section 7.2/7.3).

With MSB_FIRST (TILELINK_MSB_FIRST in tilelink.h) the firmware appends the CRC
itself and reverses the order of the four bit pairs in every byte before the
FIFO, so the symbols carry b7b6, b5b4, b3b2, b1b0. The SCuM modem RTL decodes
each symbol high bit first, so it gets each byte MSB first. Otherwise the TRF
appends the CRC and bytes go out LSB first (standard ISO15693: b1b0 first,
each symbol low bit first). Bytes shown are always the packet bytes.

Slot levels: 1 = carrier (unmodulated), 0 = pause (carrier off at OOK 100%,
reduced amplitude at ASK 10%). This is the envelope the chip's demodulator sees.

Examples:
    python tools/nfc_bitstream.py test
    python tools/nfc_bitstream.py write 0x80000000 0807060504030201
    python tools/nfc_bitstream.py read 0x80000000 8
    python tools/nfc_bitstream.py raw 01 0000008000000000 0800000000000000 0807060504030201
    python tools/nfc_bitstream.py test --slots-only > expected.txt
    python tools/nfc_bitstream.py --csv expected.csv test
    python tools/nfc_bitstream.py --plot test            (interactive window, zoom with the toolbar)
    python tools/nfc_bitstream.py --plot --save test.png test
    python tools/nfc_bitstream.py --plot --bytes 17:25 test   (zoom to the body bytes)
    python tools/nfc_bitstream.py csv expected.csv            (graph a CSV after editing it)
"""

import argparse
import sys

from tsi_host import (CMD_READ, CMD_WRITE, EXAMPLE_ADDR, EXAMPLE_BODY, FW_MAX_BODY,
                      build_frame, fmt_frame, on_air, parse_hex, parse_int)

SLOT_US = 128 / 13.56        # 9.44 us
SOF = "01111011"
EOF = "1101"
PAIR_SLOTS = ["10111111", "11101111", "11111011", "11111110"]   # pair value 0..3
MSB_FIRST = True             # TILELINK_MSB_FIRST in tilelink.h
ORDER = "MSB" if MSB_FIRST else "LSB"


def fifo_byte(byte: int) -> int:
    """The byte as written to the TRF FIFO (bit pairs in reverse order when MSB_FIRST). Its own inverse."""
    if not MSB_FIRST:
        return byte
    return ((byte & 0x03) << 6) | ((byte & 0x0C) << 2) | ((byte & 0x30) >> 2) | ((byte & 0xC0) >> 6)


def air_bits(data: bytes) -> str:
    """Bits in the order the receiver decodes them: each symbol high bit first
    when MSB_FIRST (so each byte MSB first), else low bit first (ISO15693)."""
    return "".join(f"{p:02b}" if MSB_FIRST else f"{p:02b}"[::-1]
                   for byte in data for p in pair_values(byte))


def pair_values(byte: int) -> list:
    """The four 1 out of 4 symbols a packet byte is sent as, in transmit order."""
    return [(fifo_byte(byte) >> shift) & 3 for shift in (0, 2, 4, 6)]


def ppm_slots(data: bytes) -> str:
    """SOF + 1 out of 4 coded data + EOF, one character per 9.44 us slot."""
    pairs = [p for byte in data for p in pair_values(byte)]
    return SOF + "".join(PAIR_SLOTS[p] for p in pairs) + EOF


def add_packet_commands(parser):
    """Add the test/write/read/raw subcommands that packets_for() understands."""
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("test", help="the NFC Modem wiki example write packet")
    p = sub.add_parser("write", help="write packets for hex data")
    p.add_argument("addr")
    p.add_argument("data", nargs="+")
    p = sub.add_parser("read", help="read request packet")
    p.add_argument("addr")
    p.add_argument("length")
    p = sub.add_parser("raw", help="raw cmd..body bytes (CRC is appended)")
    p.add_argument("data", nargs="+")
    return sub


def packets_for(args) -> list:
    """The on-air packets (bytes incl. CRC) the firmware sends for a command."""
    if args.action == "test":
        return [on_air(build_frame(CMD_WRITE, EXAMPLE_ADDR, len(EXAMPLE_BODY), EXAMPLE_BODY))]
    if args.action == "write":
        addr, data = parse_int(args.addr), parse_hex(args.data)
        return [on_air(build_frame(CMD_WRITE, addr + off, len(data[off:off + FW_MAX_BODY]), data[off:off + FW_MAX_BODY]))
                for off in range(0, len(data), FW_MAX_BODY)]
    if args.action == "read":
        return [on_air(build_frame(CMD_READ, parse_int(args.addr), parse_int(args.length)))]
    return [on_air(parse_hex(args.data))]


def show_packet(index: int, packet: bytes):
    slots = ppm_slots(packet)
    print(f"=== packet {index}: {len(packet)} bytes, {len(slots)} slots, {len(slots) * SLOT_US:.2f} us ===")
    print("bytes:", fmt_frame(packet))
    print()
    print(f"bits (transmit order, each byte {ORDER} first):")
    for i, byte in enumerate(packet):
        bits = air_bits(bytes([byte]))
        pairs = " ".join(str(p) for p in pair_values(byte))
        print(f"  [{i:2d}] 0x{byte:02X}  {bits}  pair values {pairs}")
    print()
    print("1 out of 4 slots (1 = carrier, 0 = pause, 9.44 us each):")
    print(f"  SOF        {SOF}")
    for i, byte in enumerate(packet):
        body = ppm_slots(bytes([byte]))[len(SOF):-len(EOF)]
        print(f"  [{i:2d}] 0x{byte:02X}  " + " ".join(body[j:j + 8] for j in range(0, 32, 8)))
    print(f"  EOF        {EOF}")
    print()


def decode_slots(slots: str) -> list:
    """Decode a slot stream like a demodulator would: one (byte label, [pair labels]) per byte.

    A symbol that isn't exactly one pause in an odd slot decodes as '?', and so does its byte.
    """
    body = slots[len(SOF):len(slots) - len(EOF)]
    pairs = []
    for j in range(0, len(body) - len(body) % 8, 8):
        symbol = body[j:j + 8]
        pairs.append(PAIR_SLOTS.index(symbol) if symbol in PAIR_SLOTS else None)
    decoded = []
    for j in range(0, len(pairs), 4):
        group = pairs[j:j + 4]
        valid = len(group) == 4 and None not in group
        label = f"{fifo_byte(sum(p << (2 * k) for k, p in enumerate(group))):02X}" if valid else "??"
        decoded.append((label, ["?" if p is None else str(p) for p in group]))
    return decoded


def read_csv(path: str) -> list:
    """Slot streams from a --csv file (columns packet,slot,level; t_us is ignored)."""
    import csv
    streams = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            streams.setdefault(int(row["packet"]), {})[int(row["slot"])] = row["level"].strip()
    return ["".join(slots[i] for i in sorted(slots)) for _, slots in sorted(streams.items())]


def plot_streams(streams: list, titles: list, save_path: str = None, byte_range: tuple = None):
    """Step plot of each slot stream, labelled with its decoded bytes and pair values. Needs matplotlib."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("--plot needs matplotlib: pip install matplotlib")

    fig, axes = plt.subplots(len(streams), 1, figsize=(16, 3 * len(streams)), squeeze=False)
    for ax, stream, title in zip(axes[:, 0], streams, titles):
        slots = [int(c) for c in stream]
        t = [i * SLOT_US for i in range(len(slots) + 1)]
        ax.step(t, slots + slots[-1:], where="post", color="#2a78d6", linewidth=1.5)

        # Shade every other byte and label it with its hex value and pair values 0..3
        start = len(SOF)
        for i, (label, pairs) in enumerate(decode_slots(stream)):
            x0 = (start + 32 * i) * SLOT_US
            if i % 2:
                ax.axvspan(x0, x0 + 32 * SLOT_US, color="#e1e0d9", alpha=0.5, linewidth=0)
            ax.text(x0 + 16 * SLOT_US, 1.25, label, ha="center", fontsize=8, family="monospace", clip_on=True)
            ax.text(x0 + 16 * SLOT_US, -0.35, " ".join(pairs), ha="center", fontsize=6, color="#52514e",
                    family="monospace", clip_on=True)
        ax.text(len(SOF) / 2 * SLOT_US, 1.25, "SOF", ha="center", fontsize=8, clip_on=True)
        ax.text((len(slots) - len(EOF) / 2) * SLOT_US, 1.25, "EOF", ha="center", fontsize=8, clip_on=True)

        ax.set_ylim(-0.5, 1.45)
        ax.set_yticks([0, 1], ["pause", "carrier"])
        if byte_range:
            first, last = byte_range
            ax.set_xlim((start + 32 * first) * SLOT_US, min((start + 32 * last) * SLOT_US, t[-1]))
        else:
            ax.set_xlim(0, t[-1])
        ax.set_xlabel("time (µs)")
        ax.set_title(title, fontsize=9, loc="left")
        ax.grid(axis="x", color="#e1e0d9", linewidth=0.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"wrote {save_path}", file=sys.stderr)
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--bits-only", action="store_true", help="print only the logical bitstream, one line per packet")
    out.add_argument("--slots-only", action="store_true", help="print only the slot stream (with SOF/EOF), one line per packet")
    out.add_argument("--csv", metavar="FILE", help="write packet,slot,t_us,level rows for plotting/diffing")
    out.add_argument("--plot", action="store_true", help="graph the envelope with matplotlib in a window")
    parser.add_argument("--save", metavar="FILE", help="with --plot, save the graph to FILE (.png/.pdf/.svg) instead")
    parser.add_argument("--bytes", metavar="A:B", help="with --plot, zoom to bytes A up to (not including) B, e.g. 17:25")
    sub = add_packet_commands(parser)
    p = sub.add_parser("csv", help="graph a (possibly edited) --csv file; implies --plot")
    p.add_argument("file")
    args = parser.parse_args()

    byte_range = None
    if args.bytes:
        try:
            first, last = (int(x) for x in args.bytes.split(":"))
        except ValueError:
            sys.exit("--bytes must look like A:B, e.g. 17:25")
        byte_range = (first, last)

    if args.action == "csv":
        streams = read_csv(args.file)
        plot_streams(streams, [f"{args.file} packet {n}" for n in range(len(streams))], args.save, byte_range)
        return

    packets = packets_for(args)

    if args.bits_only:
        for packet in packets:
            print(air_bits(packet))
    elif args.slots_only:
        for packet in packets:
            print(ppm_slots(packet))
    elif args.csv:
        with open(args.csv, "w") as f:
            f.write("packet,slot,t_us,level\n")
            for n, packet in enumerate(packets):
                for i, level in enumerate(ppm_slots(packet)):
                    f.write(f"{n},{i},{i * SLOT_US:.3f},{level}\n")
        print(f"wrote {args.csv}", file=sys.stderr)
    elif args.plot:
        plot_streams([ppm_slots(p) for p in packets],
                     [f"packet {n}: {fmt_frame(p)}" for n, p in enumerate(packets)], args.save, byte_range)
    else:
        for n, packet in enumerate(packets):
            show_packet(n, packet)


if __name__ == "__main__":
    main()

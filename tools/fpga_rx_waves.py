#!/usr/bin/env python3
"""Generate the fm_in / fm_clock / rx_clk waveforms the FPGA should see for a packet.

Models the receive side of the breadboard NFC front end, sampled at --fs (35 MHz):

  fm_in     demodulated envelope: 1 = carrier, 0 = pause (--invert-fm-in flips it)
  fm_clock  13.56 MHz clock recovered from the carrier. With --gate-clock it stops
            (held low) during pauses, as it would at 100% OOK when the carrier is gone.
  rx_clk    fm_clock divided by --div (default 128 -> 105.9 kHz, which is exactly one
            9.44 us slot per period). High for the first half of each period.

The packet is the same one nfc_bitstream.py prints (ISO15693 1 out of 4, bit order per
its MSB_FIRST), with --lead-us / --tail-us of plain carrier around it.

Examples:
    python tools/fpga_rx_waves.py --csv rx.csv test
    python tools/fpga_rx_waves.py --vcd rx.vcd test                (open in GTKWave / Vivado)
    python tools/fpga_rx_waves.py --rtl-csv rx_input.csv test      (one 0/1 per slot, for the RTL sim)
    python tools/fpga_rx_waves.py --plot --us 40:140 test          (SOF + first symbols)
    python tools/fpga_rx_waves.py --plot --gate-clock --div 128 --us 40:140 test
    python tools/fpga_rx_waves.py --vcd rx1.vcd --packet 1 write 0x80000000 00112233445566778899
"""

import argparse
import math
import sys

from nfc_bitstream import EOF, SLOT_US, SOF, add_packet_commands, decode_slots, fmt_frame, packets_for, ppm_slots

CARRIER_HZ = 13.56e6


def generate(slots: str, fs: float, div: int, gate: bool, lead_us: float, tail_us: float, invert: bool):
    """Sampled (fm_in, fm_clock, rx_clk) lists for one slot stream."""
    slot_s, lead_s = SLOT_US * 1e-6, lead_us * 1e-6
    total_s = lead_s + len(slots) * slot_s + tail_us * 1e-6

    # pause_before[k] = number of pause slots before slot k, for the gated cycle count
    pause_before = [0]
    for level in slots:
        pause_before.append(pause_before[-1] + (level == "0"))

    fm_in, fm_clock, rx_clk = [], [], []
    for n in range(int(total_s * fs)):
        t = n / fs
        k = math.floor((t - lead_s) / slot_s)
        carrier = not (0 <= k < len(slots) and slots[k] == "0")

        if gate:
            # Carrier on time so far = elapsed time minus completed pauses minus the current one
            kc = min(max(k, 0), len(slots))
            paused = pause_before[kc] * slot_s
            if not carrier:
                paused += t - (lead_s + k * slot_s)
            cycles = (t - paused) * CARRIER_HZ
        else:
            cycles = t * CARRIER_HZ

        fm_in.append(int(carrier) ^ invert)
        fm_clock.append(int((carrier or not gate) and (cycles % 1) < 0.5))
        rx_clk.append(int(math.floor(cycles) % div < div / 2))
    return fm_in, fm_clock, rx_clk


def write_csv(path: str, fs: float, waves):
    with open(path, "w") as f:
        f.write("sample,t_ns,fm_in,fm_clock,rx_clk\n")
        for n, values in enumerate(zip(*waves)):
            f.write(f"{n},{n * 1e9 / fs:.3f},{values[0]},{values[1]},{values[2]}\n")


RTL_IDLE_SLOTS = 6           # carrier slots after the EOF


def write_rtl_csv(path: str, slots: str):
    """One slot per line for the RTL testbench: 0 = pause, 1 = carrier. Starts right
    after the SOF, so the first 8 lines are the first symbol of byte 0, and ends with
    the EOF plus RTL_IDLE_SLOTS idle slots. No header. Independent of --fs and --invert-fm-in."""
    with open(path, "w") as f:
        f.write("\n".join(slots[len(SOF):] + "1" * RTL_IDLE_SLOTS) + "\n")


def write_vcd(path: str, fs: float, waves, names=("fm_in", "fm_clock", "rx_clk")):
    """Value change dump with 1 ps resolution; only changes are written."""
    ids = ["!", '"', "#"]
    with open(path, "w") as f:
        f.write("$timescale 1ps $end\n$scope module nfc_rx $end\n")
        for name, ident in zip(names, ids):
            f.write(f"$var wire 1 {ident} {name} $end\n")
        f.write("$upscope $end\n$enddefinitions $end\n")
        previous = None
        for n, values in enumerate(zip(*waves)):
            changes = [f"{v}{i}" for v, i, p in zip(values, ids, previous or (None,) * 3) if v != p]
            if changes:
                f.write(f"#{round(n * 1e12 / fs)}\n" + "\n".join(changes) + "\n")
            previous = values


def plot(slots: str, fs: float, waves, title: str, lead_us: float, window, save_path: str = None):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("--plot needs matplotlib: pip install matplotlib")

    total_us = len(waves[0]) * 1e6 / fs
    first_us, last_us = window if window else (0, total_us)
    lo, hi = max(0, int(first_us * fs / 1e6)), min(len(waves[0]), int(last_us * fs / 1e6) + 1)
    t = [n * 1e6 / fs for n in range(lo, hi)]

    fig, axes = plt.subplots(3, 1, figsize=(16, 6), sharex=True)
    for ax, wave, name in zip(axes, waves, ("fm_in", "fm_clock", "rx_clk")):
        ax.step(t, wave[lo:hi], where="post", color="#2a78d6", linewidth=1)
        ax.set_ylim(-0.3, 1.5)
        ax.set_yticks([0, 1])
        ax.set_ylabel(name)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    # Byte boundaries and decoded labels on fm_in
    ax = axes[0]
    start = lead_us + len(SOF) * SLOT_US
    ax.text(lead_us + len(SOF) / 2 * SLOT_US, 1.2, "SOF", ha="center", fontsize=8, clip_on=True)
    for i, (label, pairs) in enumerate(decode_slots(slots)):
        x0 = start + 32 * i * SLOT_US
        ax.axvline(x0, color="#c3c2b7", linewidth=0.8)
        ax.text(x0 + 16 * SLOT_US, 1.2, f"[{i}] {label}  ({' '.join(pairs)})", ha="center", fontsize=8,
                family="monospace", clip_on=True)
    ax.text(lead_us + (len(slots) - len(EOF) / 2) * SLOT_US, 1.2, "EOF", ha="center", fontsize=8, clip_on=True)

    axes[0].set_title(title, fontsize=9, loc="left")
    axes[-1].set_xlabel("time (µs)")
    axes[-1].set_xlim(t[0], t[-1])
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"wrote {save_path}", file=sys.stderr)
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fs", type=float, default=35e6, help="sample rate in Hz (default 35e6)")
    parser.add_argument("--div", type=int, default=128, help="fm_clock cycles per rx_clk period (default 128)")
    parser.add_argument("--gate-clock", action="store_true", help="stop fm_clock during pauses (100%% OOK)")
    parser.add_argument("--invert-fm-in", action="store_true", help="fm_in = 1 during pauses instead of carrier")
    parser.add_argument("--lead-us", type=float, default=50, help="carrier before SOF in us (default 50)")
    parser.add_argument("--tail-us", type=float, default=50, help="carrier after EOF in us (default 50)")
    parser.add_argument("--packet", type=int, default=0, help="which packet of a multi-packet write (default 0)")
    parser.add_argument("--csv", metavar="FILE", help="write sample,t_ns,fm_in,fm_clock,rx_clk rows")
    parser.add_argument("--vcd", metavar="FILE", help="write a VCD waveform")
    parser.add_argument("--rtl-csv", metavar="FILE", help="write one 0/1 per slot after the SOF, for the RTL testbench")
    parser.add_argument("--plot", action="store_true", help="graph the waveforms with matplotlib")
    parser.add_argument("--save", metavar="FILE", help="with --plot, save the graph to FILE instead")
    parser.add_argument("--us", metavar="A:B", help="with --plot, show A..B microseconds (default: everything)")
    add_packet_commands(parser)
    args = parser.parse_args()

    if not (args.csv or args.vcd or args.rtl_csv or args.plot):
        parser.error("choose at least one of --csv, --vcd, --rtl-csv, --plot")
    window = None
    if args.us:
        try:
            window = tuple(float(x) for x in args.us.split(":"))
        except ValueError:
            sys.exit("--us must look like A:B, e.g. 40:140")

    packets = packets_for(args)
    if not 0 <= args.packet < len(packets):
        sys.exit(f"--packet must be 0..{len(packets) - 1}")
    packet = packets[args.packet]
    slots = ppm_slots(packet)

    waves = generate(slots, args.fs, args.div, args.gate_clock, args.lead_us, args.tail_us, args.invert_fm_in)

    print(f"packet {args.packet}: {fmt_frame(packet)}", file=sys.stderr)
    print(f"{len(waves[0])} samples at {args.fs / 1e6:g} MHz, SOF starts at {args.lead_us:g} us; "
          f"{args.fs / CARRIER_HZ:.2f} samples per fm_clock period, {SLOT_US * args.fs / 1e6:.1f} per slot; "
          f"rx_clk = {CARRIER_HZ / args.div / 1e3:.2f} kHz", file=sys.stderr)

    if args.csv:
        write_csv(args.csv, args.fs, waves)
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.vcd:
        write_vcd(args.vcd, args.fs, waves)
        print(f"wrote {args.vcd}", file=sys.stderr)
    if args.rtl_csv:
        write_rtl_csv(args.rtl_csv, slots)
        print(f"wrote {args.rtl_csv} ({len(slots) - len(SOF) + RTL_IDLE_SLOTS} slots)", file=sys.stderr)
    if args.plot:
        title = f"packet {args.packet}: {fmt_frame(packet)}  ({args.fs / 1e6:g} MHz samples, rx_clk = fm_clock / {args.div}" \
                f"{', fm_clock gated in pauses' if args.gate_clock else ''})"
        plot(slots, args.fs, waves, title, args.lead_us, window, args.save)


if __name__ == "__main__":
    main()

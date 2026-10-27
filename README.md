# NFC Dev Board Programming

This board sends TileLink commands to the SCuM v26 chip over NFC. Use it to write data into the chip's memory, for example to load a program, without plugging in a debugger.

You type a command on your PC. The board turns it into an NFC packet and sends it to the chip's antenna.

```
PC (Python script) --USB--> LaunchPad (MSP430) --SPI--> TRF7970A BoosterPack --NFC--> SCuM chip
```

The packet format is described on the [NFC Modem wiki page](https://bwrcrepo.eecs.berkeley.edu/ee194-290c-sp26/scumv26/-/wikis/Spring-2026-SCuM-v26-Tapeout-Wiki/Digital/NFC-Modem).


## 2. Build and flash the firmware

Run:

```powershell
cd TRF7970ABP_RFID_Reader_Demo
make
make flash
cd ..
```
- `make` builds the firmware.
- `make flash` copies it onto the board.

---

## 3. Check that it works

Run this from the main folder. Replace `COM5` with your COM port:

```
python tools/tsi_host.py --port COM5 test
```

This sends the example packet from the wiki. You should see:

```
on air: 01 | 0000008000000000 | 0800000000000000 | 0807060504030201 | 312c
OK
```

`OK` means the board sent the packet. The board can't tell whether the chip received it, because the chip doesn't reply to writes.

---

## 4. Send commands

Every command looks like this:

```
python tools/tsi_host.py --port COM5 <command>
```

| What you want to do | Command |
|---|---|
| Send the wiki example packet | `test` |
| Write bytes to an address | `write 0x80000000 0807060504030201` |
| Load a whole program file | `load program.bin 0x80000000` |
| Read bytes back (experimental) | `read 0x80000000 8` |
| Send any packet you build yourself | `raw 01 0000008000000000 0800000000000000 0807060504030201` |
| Turn the NFC field on or off | `field on` / `field off` |
| Change the modulation | `mod 100` (default) / `mod 10` |
| Change the pause length (µs) | `pulse 14.7` (default) / `pulse 0` (9.44 µs ISO15693 preset) |

**Notes**
- **Addresses and data are in hex.**
- **`load` needs a raw `.bin` file.** To make one from an ELF, use your compiler's objcopy, for example `riscv64-unknown-elf-objcopy -O binary program.elf program.bin`.
- **The NFC field turns on by itself** when you send the first packet. It stays on until you run `field off` or reset the board.
- **`mod` and `pulse` stay set** until you reset the board.
- **`pulse` sets how long the TRF7970A holds each pause**, in 73.7 ns steps up to 18.8 µs. The breadboard demodulator shortens pauses by about 5.3 µs (9.44 µs sent showed up as ~4.1 µs on `fm_in`), so the default is 14.7 µs to give ~9.44 µs at `fm_in`. Measure `fm_in` on the ILA and adjust; keep it under ~17.7 µs, because pauses can start 18.88 µs apart. The compiled-in default is `TILELINK_TX_PULSE_DEFAULT` in `NFC/tilelink.h`.
- **`read` is experimental.** The chip's replies may not be readable by this board yet. If you get `NO_RESPONSE_RECEIVED_15693`, the board heard nothing back.

**Preview without a board:** add `--dry-run` to see the exact bytes that would be sent:

```
python tools/tsi_host.py --dry-run write 0x80000000 0807060504030201
```

---

## 5. See the modulated bitstream

`tools/nfc_bitstream.py` prints exactly what the TRF7970A modulates for a packet, so you can compare it with what the chip's NFC demodulator outputs. It takes the same `test` / `write` / `read` / `raw` commands as `tsi_host.py` and doesn't need a board:

```
python tools/nfc_bitstream.py test
python tools/nfc_bitstream.py write 0x80000000 0807060504030201
```

For each packet it shows:
- **Bytes:** the frame, including the CRC the TRF adds.
- **Bits in transmit order:** each byte is sent MSB first, as the SCuM modem RTL expects. The TRF7970A always sends LSB first, so when `TILELINK_MSB_FIRST` is 1 in `NFC/tilelink.h` the firmware reverses the order of the four bit pairs in every byte (each 1 out of 4 symbol then carries b7b6, b5b4, b3b2, b1b0, which the RTL decodes high bit first) and computes the CRC itself. Set it to 0, and `MSB_FIRST = False` in `tools/nfc_bitstream.py`, for standard ISO15693 bit order.
- **1 out of 4 slots:** one character per 9.44 µs slot (`1` = carrier, `0` = pause), with the SOF (`01111011`) and EOF (`1101`). Each pair of bits picks which slot gets the pause.

To compare with demodulator output:

| Output | Option |
|---|---|
| Decoded bits, one line per packet | `--bits-only` |
| Slot pattern with SOF/EOF, one line per packet | `--slots-only` |
| `packet,slot,t_us,level` rows for plotting | `--csv out.csv` |
| Graph of the envelope (needs `pip install matplotlib`) | `--plot`, or `--plot --save out.png` |
| Graph zoomed to bytes A up to B (e.g. the body) | `--plot --bytes 17:25` |
| Graph a CSV after editing its `level` column | `csv out.csv` (bad symbols decode as `?`) |

For example, `python tools/nfc_bitstream.py --bits-only test > expected.txt`, then `diff` it against the demodulator's output.

**Notes**
- **Bit order:** `--bits-only` prints bits the way the RTL decodes them (each byte MSB first). If you flip `TILELINK_MSB_FIRST`, flip `MSB_FIRST` in `tools/nfc_bitstream.py` too; `make test` checks they match.
- **Writes over 8 bytes** are split into several packets, one line each.
- **This is the ideal stream** from the ISO15693 spec, not a capture. It doesn't show timing jitter or 10% ASK depth.

---

## 6. Generate FPGA / RTL simulation inputs

`tools/fpga_rx_waves.py` turns a packet into what the FPGA should see from the breadboard NFC front end, sampled at the ILA rate (35 MHz by default). It takes the same `test` / `write` / `read` / `raw` commands:

| Signal | What it is |
|---|---|
| `fm_in` | demodulated envelope: `1` = carrier, `0` = pause |
| `fm_clock` | 13.56 MHz clock recovered from the carrier |
| `rx_clk` | `fm_clock` divided by 128 (105.9 kHz, one 9.44 µs slot per period) |

| Output | Option |
|---|---|
| Graph of all three signals | `--plot` (add `--us 40:140` to zoom, `--save out.png` to save) |
| One row per 35 MHz sample: `sample,t_ns,fm_in,fm_clock,rx_clk` | `--csv rx_input_samples.csv` |
| Waveform for GTKWave / Vivado | `--vcd rx.vcd` |
| One `0`/`1` per slot for the RTL testbench (see below) | `--rtl-csv rx_input.csv` |

Generate everything for the wiki example packet in one go:

```
python tools/fpga_rx_waves.py --csv rx_input_samples.csv --vcd rx.vcd --rtl-csv rx_input.csv test
```

**RTL testbench file (`--rtl-csv`):** one line per 9.44 µs slot, no header, `0` where a pause starts and `1` otherwise. It starts right after the SOF and ends with the EOF plus 6 idle slots. For the wiki example the first 8 lines are `1 0 1 1 1 1 1 1` (the first symbol of byte `01`). It comes straight from the slot pattern, so `--fs`, `--gate-clock` and `--invert-fm-in` don't change it.

**Options**
- `--fs 50e6`: sample rate, if your ILA clock isn't 35 MHz.
- `--div N`: `rx_clk` divider, if it isn't 128.
- `--gate-clock`: stop `fm_clock` during pauses, as happens with 100% OOK when the carrier disappears.
- `--invert-fm-in`: `fm_in` is `1` during pauses instead.
- `--lead-us 0`: start the SOF at time 0 (default is 50 µs of carrier first), to line up with an ILA trigger on the first pause.
- `--packet N`: which packet of a write longer than 8 bytes.

**Notes**
- **One packet at a time.** The full wiki example is about 293k samples at 35 MHz, likely more than the ILA holds; use `--us` to plot only the part you captured.
- **`--us` only affects the plot.** The CSV and VCD always contain the whole packet.
- **`fm_clock` looks uneven** in the CSV: at 35 MHz each 13.56 MHz period is only 2.58 samples, so its high time alternates between 1 and 2 samples.

---
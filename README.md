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

**Notes**
- **Addresses and data are in hex.**
- **`load` needs a raw `.bin` file.** To make one from an ELF, use your compiler's objcopy, for example `riscv64-unknown-elf-objcopy -O binary program.elf program.bin`.
- **The NFC field turns on by itself** when you send the first packet. It stays on until you run `field off` or reset the board.
- **`mod` stays set** until you reset the board.
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
- **Bit order:** if the demodulator collects bits MSB first, every byte will look reversed.
- **Writes over 8 bytes** are split into several packets, one line each.
- **This is the ideal stream** from the ISO15693 spec, not a capture. It doesn't show timing jitter or 10% ASK depth.

---
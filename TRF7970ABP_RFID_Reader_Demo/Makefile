# Build the TRF7970A reader demo with msp430-elf-gcc (no Code Composer Studio).
#
#   make          - compile + link  -> build/nfc_reader.elf / .hex
#   make flash    - program the MSP430G2553 through the LaunchPad debugger
#   make size     - show flash/RAM usage
#   make test     - run the host tests in ../tests/host (PC gcc, no board needed)
#   make clean

GCC_DIR ?= C:/ti/msp430-gcc
MCU     := msp430g2553
TARGET  := nfc_reader
BUILD   := build

CC      := $(GCC_DIR)/bin/msp430-elf-gcc
OBJCOPY := $(GCC_DIR)/bin/msp430-elf-objcopy
SIZE    := $(GCC_DIR)/bin/msp430-elf-size
GDB     := $(GCC_DIR)/bin/msp430-elf-gdb
AGENT   := $(GCC_DIR)/bin/gdb_agent_console
AGENT_CFG := $(GCC_DIR)/msp430.dat

SRCS := main.c system_pre_init.c $(wildcard Hardware/*.c) $(wildcard NFC/*.c)
OBJS := $(addprefix $(BUILD)/,$(SRCS:.c=.o))

CFLAGS  := -mmcu=$(MCU) -Os -g -Wall -ffunction-sections -fdata-sections \
           -I$(GCC_DIR)/include -I. -IHardware -INFC
LDFLAGS := -mmcu=$(MCU) -L$(GCC_DIR)/include -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map

all: $(BUILD)/$(TARGET).hex size

$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS)
	$(CC) $(LDFLAGS) $^ -o $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

size: $(BUILD)/$(TARGET).elf
	$(SIZE) $<

# Starts the TI GDB agent (talks to the LaunchPad's on-board debugger on port
# 55000), loads the ELF into flash, then resets and runs the MCU before
# stopping the agent. A plain "detach" is not enough: the agent reconnects as
# soon as gdb leaves, which halts the MCU, and it stays halted after the agent is
# killed (no UART output until the board is power cycled). So a second gdb
# leaves the target running ("continue") and is killed along with the agent.
flash: $(BUILD)/$(TARGET).elf
	$(AGENT) $(AGENT_CFG) & agent=$$!; sleep 3; \
	$(GDB) -batch -ex "target remote :55000" -ex "load" $<; status=$$?; \
	if [ $$status -eq 0 ]; then \
		$(GDB) -batch -ex "target remote :55000" -ex "monitor reset" -ex "continue" $< > $(BUILD)/run.log 2>&1 & gdb=$$!; \
		for i in $$(seq 30); do grep -q "Continuing" $(BUILD)/run.log && break; sleep 1; done; \
		cat $(BUILD)/run.log; sleep 1; kill $$gdb; \
	fi; \
	kill $$agent; exit $$status

test:
	python ../tests/host/run_tests.py

clean:
	rm -rf $(BUILD)

.PHONY: all size flash test clean

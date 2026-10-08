/*
 * File Name: tilelink.h
 *
 * Description: Framing for the SCuM v26 NFC Modem custom protocol, which
 * carries TileLink read/write requests over an LRI2K/ISO15693-style link.
 *
 * Downlink frame (reader -> chip), as sent on air:
 *   SOF | cmd (1) | addr (8, LE) | length (8, LE) | body (length) | CRC (2, LE) | EOF
 *
 * SOF/EOF, 1 out of 4 PPM coding and the CRC-16 (ISO/IEC 13239, poly 0x8408
 * reflected, init/xorout 0xFFFF) are the same as ISO15693 at the high data
 * rate, so the TRF79xxA generates them in hardware when configured for
 * ISO15693 and given the "transmit with CRC" command. Only cmd..body are
 * written to the FIFO.
 */

#ifndef _TILELINK_H_
#define _TILELINK_H_

//================================================================

#include "trf79xxa.h"

//===============================================================

#define TILELINK_CMD_READ			0x00
#define TILELINK_CMD_WRITE			0x01

// ISO15693, high bit rate, one subcarrier, 1 out of 4, RX CRC enabled
#define TILELINK_ISO_CONTROL		0x02

#define TILELINK_HEADER_SIZE		17		// cmd + addr + length

// Body bytes per write packet. The wiki example uses 8. Upper bound is
// NFC_FIFO_SIZE - 5 TRF command bytes - TILELINK_HEADER_SIZE.
#define TILELINK_MAX_BODY			8

// Delay between write packets. Writes are not acknowledged, so this is
// the only flow control into the chip's 255 byte PacketBuffer.
#define TILELINK_GAP_MS				5

// TRF79xxA_waitRxIRQ timeouts (ms). Writes only need to outlast the TRF
// no response window (TILELINK_NO_RESP_WRITE * 37.76us); reads allow the
// chip time to perform the TileLink access and reply.
#define TILELINK_RX_TIMEOUT_WRITE	5
#define TILELINK_RX_TIMEOUT_READ	30

// TRF79XXA_RX_NO_RESPONSE_WAIT_TIME values (units of 37.76us in ISO15693)
#define TILELINK_NO_RESP_WRITE		0x15	// ~0.8ms, TI ISO15693 default
#define TILELINK_NO_RESP_READ		0xFF	// ~9.6ms

//===============================================================

void Tilelink_fieldOn(void);
void Tilelink_fieldOff(void);
void Tilelink_setAsk10(bool bAsk10);
bool Tilelink_isFieldOn(void);

tTrfStatus Tilelink_sendRaw(uint8_t * pui8Frame, uint8_t ui8Length);
tTrfStatus Tilelink_write(uint32_t ui32Address, const uint8_t * pui8Data, uint8_t ui8Length);
tTrfStatus Tilelink_read(uint32_t ui32Address, uint8_t ui8Length);

//===============================================================

#endif

/*
 * File Name: tilelink.c
 *
 * Description: Sends SCuM v26 NFC Modem packets (TileLink read/write
 * requests) through the TRF79xxA configured for ISO15693. See tilelink.h
 * for the frame format.
 */

#include "tilelink.h"

//===============================================================

#define TRF_CMD_BYTES		5		// Reset FIFO, Transmit with/without CRC, Write Continuous, 2 length bytes

#if TILELINK_MSB_FIRST
#define TILELINK_CRC_BYTES	2		// CRC is added by the firmware, so it takes FIFO space
#else
#define TILELINK_CRC_BYTES	0		// CRC is added by the TRF79xxA
#endif

static bool g_bTilelinkFieldOn = false;
static bool g_bTilelinkAsk10 = false;
static uint8_t g_ui8TilelinkPulseLength = TILELINK_TX_PULSE_DEFAULT;

//===============================================================
//
// Tilelink_fieldOn - Configure the TRF79xxA for the NFC Modem link and
// turn on the RF field.
//
// The field stays on between packets since the chip derives its modem
// clocks from the 13.56 MHz carrier.
//
//===============================================================

void Tilelink_fieldOn(void)
{
	TRF79xxA_setupInitiator(TILELINK_ISO_CONTROL);	// Resets the TRF, turns RF on, sets OOK 100%

	TRF79xxA_writeRegister(TRF79XXA_TX_PULSE_LENGTH_CONTROL, g_ui8TilelinkPulseLength);	// Cleared by the ISO Control write

	if (g_bTilelinkAsk10)
	{
		TRF79xxA_writeRegister(TRF79XXA_MODULATOR_CONTROL, 0x00);	// ASK 10%
	}

	g_bTilelinkFieldOn = true;

	MCU_delayMillisecond(20);		// Guard time for the chip to power up / lock to the carrier
}

void Tilelink_fieldOff(void)
{
	TRF79xxA_turnRfOff();
	g_bTilelinkFieldOn = false;
}

bool Tilelink_isFieldOn(void)
{
	return g_bTilelinkFieldOn;
}

//===============================================================
//
// Tilelink_setAsk10 - Select 10% ASK (true) or 100% OOK (false)
// modulation. Applied immediately if the field is on.
//
//===============================================================

void Tilelink_setAsk10(bool bAsk10)
{
	g_bTilelinkAsk10 = bAsk10;

	if (g_bTilelinkFieldOn)
	{
		TRF79xxA_writeRegister(TRF79XXA_MODULATOR_CONTROL, bAsk10 ? 0x00 : 0x01);
	}
}

#if TILELINK_MSB_FIRST

//===============================================================
//
// crc16 - CRC-16 per the NFC Modem spec / ISO15693 (poly 0x8408
// reflected, init and xorout 0xFFFF). Same as the TRF79xxA's TX CRC.
//
//===============================================================

static uint16_t crc16(const uint8_t * pui8Data, uint8_t ui8Length)
{
	uint16_t ui16Crc = 0xFFFF;
	uint8_t ui8Bit;

	while (ui8Length--)
	{
		ui16Crc ^= *pui8Data++;
		for (ui8Bit = 0; ui8Bit < 8; ui8Bit++)
		{
			ui16Crc = (ui16Crc & 1) ? (ui16Crc >> 1) ^ 0x8408 : ui16Crc >> 1;
		}
	}

	return ~ui16Crc;
}

// Reverse the order of the four bit pairs (b7b6 b5b4 b3b2 b1b0 -> b1b0 b3b2
// b5b4 b7b6), keeping the bits within each pair. See TILELINK_MSB_FIRST.
static uint8_t reversePairs(uint8_t ui8Byte)
{
	ui8Byte = (ui8Byte >> 4) | (ui8Byte << 4);
	return ((ui8Byte & 0xCC) >> 2) | ((ui8Byte & 0x33) << 2);
}

#endif

//===============================================================
//
// Tilelink_setPulseLength - Set the modulation pause length in steps of
// 73.7 ns (0 = 9.44 us ISO15693 preset). Applied immediately if the
// field is on. See TILELINK_TX_PULSE_DEFAULT.
//
//===============================================================

void Tilelink_setPulseLength(uint8_t ui8PulseLength)
{
	g_ui8TilelinkPulseLength = ui8PulseLength;

	if (g_bTilelinkFieldOn)
	{
		TRF79xxA_writeRegister(TRF79XXA_TX_PULSE_LENGTH_CONTROL, ui8PulseLength);
	}
}

//===============================================================
//
// transmitFrame - Send the frame already placed after the TRF command
// bytes in the TRF buffer, then wait for a reply or the no response
// timeout.
//
// \param ui8Length is the number of cmd..body bytes in the frame
// \param bExpectReply selects the longer no response window for reads
//
// \return the TRF79xxA driver status. RX_COMPLETE means reply bytes are in
// TRF79xxA_getTrfBuffer(); NO_RESPONSE_RECEIVED(_15693) means silence.
//
//===============================================================

static tTrfStatus transmitFrame(uint8_t ui8Length, bool bExpectReply)
{
	uint8_t * pui8Buffer = TRF79xxA_getTrfBuffer();
	tTrfStatus sStatus;

	if (!g_bTilelinkFieldOn)
	{
		Tilelink_fieldOn();
	}

	TRF79xxA_writeRegister(TRF79XXA_RX_NO_RESPONSE_WAIT_TIME,
						   bExpectReply ? TILELINK_NO_RESP_READ : TILELINK_NO_RESP_WRITE);

#if TILELINK_MSB_FIRST
	{
		uint8_t * pui8Frame = pui8Buffer + TRF_CMD_BYTES;
		uint16_t ui16Crc = crc16(pui8Frame, ui8Length);
		uint8_t ui8Index;

		pui8Frame[ui8Length++] = (uint8_t) ui16Crc;			// CRC little endian, as the TRF79xxA would send it
		pui8Frame[ui8Length++] = (uint8_t) (ui16Crc >> 8);

		for (ui8Index = 0; ui8Index < ui8Length; ui8Index++)
		{
			pui8Frame[ui8Index] = reversePairs(pui8Frame[ui8Index]);
		}
	}
	pui8Buffer[1] = 0x90;							// Send without CRC
#else
	pui8Buffer[1] = 0x91;							// Send with CRC
#endif
	pui8Buffer[0] = 0x8F;							// Reset FIFO
	pui8Buffer[2] = 0x3D;							// Write Continuous
	pui8Buffer[3] = (ui8Length & 0xF0) >> 0x04;		// Length of packet in bytes - upper and middle nibbles
	pui8Buffer[4] = ui8Length << 0x04;				// Length of packet in bytes - lower and broken nibbles

	TRF79xxA_writeRaw(pui8Buffer, ui8Length + TRF_CMD_BYTES);

	sStatus = TRF79xxA_waitRxData(10, bExpectReply ? TILELINK_RX_TIMEOUT_READ : TILELINK_RX_TIMEOUT_WRITE);

	if ((sStatus == PROTOCOL_ERROR) || (sStatus == COLLISION_ERROR) || (sStatus == TX_ERROR))
	{
		// The driver soft resets the TRF on receive errors, which clears the
		// ISO15693 setup and RF field, so restore them for the next packet
		Tilelink_fieldOn();
	}

	return sStatus;
}

//===============================================================
//
// buildHeader - Write cmd, 8 byte little endian address and 8 byte
// little endian length into the frame.
//
//===============================================================

static void buildHeader(uint8_t * pui8Frame, uint8_t ui8Cmd, uint32_t ui32Address, uint8_t ui8Length)
{
	uint8_t ui8Index;

	pui8Frame[0] = ui8Cmd;

	for (ui8Index = 0; ui8Index < 8; ui8Index++)
	{
		pui8Frame[1+ui8Index] = (uint8_t) ui32Address;		// Upper 4 address bytes end up 0
		ui32Address >>= 8;
		pui8Frame[9+ui8Index] = 0x00;
	}

	pui8Frame[9] = ui8Length;
}

static bool isSuccess(tTrfStatus sStatus)
{
	return (sStatus == NO_RESPONSE_RECEIVED) || (sStatus == NO_RESPONSE_RECEIVED_15693) || (sStatus == RX_COMPLETE);
}

//===============================================================
//
// Tilelink_sendRaw - Send arbitrary cmd..body bytes (CRC is appended by
// the TRF79xxA). Uses the read reply window since the content is unknown.
//
//===============================================================

tTrfStatus Tilelink_sendRaw(uint8_t * pui8Frame, uint8_t ui8Length)
{
	uint8_t * pui8Buffer = TRF79xxA_getTrfBuffer() + TRF_CMD_BYTES;
	uint8_t ui8Index;

	if (ui8Length > NFC_FIFO_SIZE - TRF_CMD_BYTES - TILELINK_CRC_BYTES)
	{
		return TX_ERROR;
	}

	for (ui8Index = 0; ui8Index < ui8Length; ui8Index++)
	{
		pui8Buffer[ui8Index] = pui8Frame[ui8Index];
	}

	return transmitFrame(ui8Length, true);
}

//===============================================================
//
// Tilelink_write - Write data to chip memory, split into
// TILELINK_MAX_BODY sized write packets.
//
// \return status of the last packet sent, or the first failing one.
//
//===============================================================

tTrfStatus Tilelink_write(uint32_t ui32Address, const uint8_t * pui8Data, uint8_t ui8Length)
{
	uint8_t * pui8Frame = TRF79xxA_getTrfBuffer() + TRF_CMD_BYTES;
	uint8_t ui8Chunk;
	uint8_t ui8Index;
	tTrfStatus sStatus = TX_ERROR;

	while (ui8Length > 0)
	{
		ui8Chunk = (ui8Length > TILELINK_MAX_BODY) ? TILELINK_MAX_BODY : ui8Length;

		buildHeader(pui8Frame, TILELINK_CMD_WRITE, ui32Address, ui8Chunk);

		for (ui8Index = 0; ui8Index < ui8Chunk; ui8Index++)
		{
			pui8Frame[TILELINK_HEADER_SIZE+ui8Index] = pui8Data[ui8Index];
		}

		sStatus = transmitFrame(TILELINK_HEADER_SIZE + ui8Chunk, false);

		if (!isSuccess(sStatus))
		{
			break;
		}

		ui32Address += ui8Chunk;
		pui8Data += ui8Chunk;
		ui8Length -= ui8Chunk;

		if (ui8Length > 0)
		{
			MCU_delayMillisecond(TILELINK_GAP_MS);
		}
	}

	return sStatus;
}

//===============================================================
//
// Tilelink_read - Request ui8Length bytes from chip memory. The request
// carries no body. On RX_COMPLETE the reply is in TRF79xxA_getTrfBuffer()
// with TRF79xxA_getRxBytesReceived() bytes.
//
//===============================================================

tTrfStatus Tilelink_read(uint32_t ui32Address, uint8_t ui8Length)
{
	buildHeader(TRF79xxA_getTrfBuffer() + TRF_CMD_BYTES, TILELINK_CMD_READ, ui32Address, ui8Length);

	return transmitFrame(TILELINK_HEADER_SIZE, true);
}

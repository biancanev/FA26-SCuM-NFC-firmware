/*
 * Host-test stand-in for Hardware/trf79xxa.h, uart.h and mcu.h.
 *
 * Only declares what NFC/tilelink.c and the APP_TILELINK block of
 * NFC/nfc_app.c use. The tTrfStatus enum and the register / buffer size
 * defines are copied from the real headers into fw_constants.h by
 * run_tests.py, so they always match the firmware.
 *
 * If you change the signature of one of these driver/UART functions in the
 * firmware, update the prototype here too.
 */
#ifndef _TRF79xxa_H_
#define _TRF79xxa_H_

#include <stdint.h>
#include <stdbool.h>

#define STATUS_FAIL		0x00
#define STATUS_SUCCESS	0x01
#define ENABLE_HOST
#define APP_TILELINK

#include "fw_constants.h"		// generated: tTrfStatus, NFC_FIFO_SIZE, register addresses

void TRF79xxA_setupInitiator(uint8_t ui8IsoControl);
void TRF79xxA_turnRfOff(void);
void TRF79xxA_writeRegister(uint8_t ui8TrfRegister, uint8_t ui8Value);
void TRF79xxA_writeRaw(uint8_t * pui8Payload, uint8_t ui8Length);
tTrfStatus TRF79xxA_waitRxData(uint8_t ui8TxTimeout, uint8_t ui8RxTimeout);
uint8_t * TRF79xxA_getTrfBuffer(void);
uint8_t TRF79xxA_getRxBytesReceived(void);
void MCU_delayMillisecond(uint32_t n_ms);

void UART_putByte(uint8_t ui8TxByte);
void UART_putNewLine(void);
void UART_putBufferAscii(const uint8_t * pui8Buffer, uint8_t ui8Length);
void UART_sendCString(uint8_t * pui8Buffer);
uint8_t UART_getLine(uint8_t * pui8Buffer, uint8_t ui8MaxLength);

#endif

/*
 * Runs the real Tilelink firmware code (NFC/tilelink.c plus the
 * APP_TILELINK block of NFC/nfc_app.c) on the PC, with the TRF79xxA, UART
 * and MCU calls replaced by stubs that log what the firmware does.
 *
 * stdin, one test per line:   <status> <rxhex|-> <command line>
 *   status  tTrfStatus value the stubbed TRF79xxA_waitRxData returns for every packet
 *   rxhex   reply bytes placed in the TRF buffer when status is RX_COMPLETE
 *
 * stdout, per test:
 *   CMD <command line>
 *   SETUP xx / RFOFF / REG rr=vv / RAW <bytes> / WAIT tx rx / DELAY ms   (driver calls, in order)
 *   OUT <everything sent to the UART, newlines shown as \r\n>
 *   END
 *
 * Built and driven by run_tests.py.
 */
#include <stdio.h>
#include <string.h>
#include "tilelink.h"

static uint8_t g_pui8TrfBuffer[NFC_FIFO_SIZE];
static uint8_t g_pui8Rx[NFC_FIFO_SIZE];
static uint8_t g_ui8RxLen;
static tTrfStatus g_sNextStatus;
static const char * g_pcLine;
static char g_pcOut[1024];

//---- TRF79xxA / MCU stubs ------------------------------------------------

void TRF79xxA_setupInitiator(uint8_t v) { printf("SETUP %02X\n", v); }
void TRF79xxA_turnRfOff(void) { printf("RFOFF\n"); }
void TRF79xxA_writeRegister(uint8_t r, uint8_t v) { printf("REG %02X=%02X\n", r, v); }

void TRF79xxA_writeRaw(uint8_t * p, uint8_t n)
{
	printf("RAW ");
	for (uint8_t i = 0; i < n; i++) printf("%02X", p[i]);
	printf("\n");
}

tTrfStatus TRF79xxA_waitRxData(uint8_t tx, uint8_t rx)
{
	printf("WAIT %u %u\n", tx, rx);
	if (g_sNextStatus == RX_COMPLETE) memcpy(g_pui8TrfBuffer, g_pui8Rx, g_ui8RxLen);
	return g_sNextStatus;
}

uint8_t * TRF79xxA_getTrfBuffer(void) { return g_pui8TrfBuffer; }
uint8_t TRF79xxA_getRxBytesReceived(void) { return g_ui8RxLen; }
void MCU_delayMillisecond(uint32_t n) { printf("DELAY %u\n", (unsigned) n); }

//---- UART stubs -----------------------------------------------------------

void UART_sendCString(uint8_t * p) { strcat(g_pcOut, (char *) p); }
void UART_putByte(uint8_t b) { sprintf(g_pcOut + strlen(g_pcOut), "%02X", b); }
void UART_putBufferAscii(const uint8_t * p, uint8_t n) { while (n--) UART_putByte(*p++); }
void UART_putNewLine(void) { strcat(g_pcOut, "\\r\\n"); }

// Same contract as Hardware/uart.c: ui8MaxLength + 1 means the line was truncated
uint8_t UART_getLine(uint8_t * p, uint8_t max)
{
	uint8_t n = 0;
	while (*g_pcLine && n < max) p[n++] = *g_pcLine++;
	return *g_pcLine ? max + 1 : n;
}

//---- Code under test --------------------------------------------------------

#include "app_tilelink_block.c"		// generated: copied from NFC/nfc_app.c

int main(void)
{
	char pcTest[1024];

	while (fgets(pcTest, sizeof pcTest, stdin))
	{
		unsigned uStatus;
		char pcRx[512];
		int iUsed = 0;

		pcTest[strcspn(pcTest, "\r\n")] = 0;
		if (sscanf(pcTest, "%u %511s %n", &uStatus, pcRx, &iUsed) < 2) continue;

		g_sNextStatus = (tTrfStatus) uStatus;
		g_ui8RxLen = 0;
		if (strcmp(pcRx, "-"))
		{
			for (char * c = pcRx; c[0] && c[1] && g_ui8RxLen < NFC_FIFO_SIZE; c += 2)
				sscanf(c, "%2hhx", &g_pui8Rx[g_ui8RxLen++]);
		}
		g_pcLine = pcTest + iUsed;
		g_pcOut[0] = 0;

		printf("CMD %s\n", g_pcLine);
		NFC_appTilelink();
		printf("OUT %s\nEND\n", g_pcOut);
	}
	return 0;
}

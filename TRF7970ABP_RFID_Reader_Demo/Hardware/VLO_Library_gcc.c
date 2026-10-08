//*******************************************************************************
//   C port of VLO_Library.asm for msp430-elf-gcc, which cannot assemble TI
//   assembler syntax. The CCS build keeps using VLO_Library.asm.
//*******************************************************************************

#if defined(__GNUC__) && !defined(__TI_COMPILER_VERSION__)

#include <msp430.h>
#include "VLO_Library.h"

unsigned int TI_8MHz_Counts_Per_VLO_Clock;

int TI_measureVLO(void)
{
	unsigned char ui8Bcsctl1 = BCSCTL1;			// preserve previous settings
	unsigned char ui8Dcoctl = DCOCTL;
	unsigned char ui8Bcsctl2 = BCSCTL2;
	unsigned char ui8Bcsctl3 = BCSCTL3;
	unsigned char ui8P2sel = P2SEL;
	unsigned int ui16First;

	P2SEL &= ~0xC0;								// clear P2SEL bits to avoid XTAL interference
	BCSCTL1 = CALBC1_1MHZ;						// Set range
	DCOCTL = CALDCO_1MHZ;						// Set DCO step + modulation
	TACCTL0 = CM_1 + CCIS_1 + CAP;				// CAP, ACLK
	TACTL = TASSEL_2 + MC_2 + TACLR;			// SMCLK, cont-mode, clear
	BCSCTL3 = LFXT1S_2;							// ACLK = VLO
	BCSCTL2 = 0;
	BCSCTL1 |= DIVA_3;							// ACLK = VLO/8

	TACCTL0 &= ~CCIFG;
	while (!(TACCTL0 & CCIFG));					// skip first signal
	TACCTL0 &= ~CCIFG;
	while (!(TACCTL0 & CCIFG));					// skip second signal
	ui16First = TACCR0;
	TACCTL0 &= ~CCIFG;
	while (!(TACCTL0 & CCIFG));					// capture a good clock
	TACTL &= ~MC_3;								// stop timer

	TI_8MHz_Counts_Per_VLO_Clock = TACCR0 - ui16First;

	BCSCTL1 = ui8Bcsctl1;
	DCOCTL = ui8Dcoctl;
	P2SEL = ui8P2sel;
	BCSCTL3 = ui8Bcsctl3;
	BCSCTL2 = ui8Bcsctl2;

	return TI_8MHz_Counts_Per_VLO_Clock;
}

#endif

/* SPDX-License-Identifier: Apache-2.0 */

#ifndef IVC_AARCH64_PSCI_H_
#define IVC_AARCH64_PSCI_H_

#include <stdint.h>

#define IVC_PSCI_SYSTEM_OFF UINT64_C(0x84000008)

static inline void ivc_aarch64_psci_system_off(void)
{
	register uint64_t function_id __asm__("x0") = IVC_PSCI_SYSTEM_OFF;

	/* AxVisor exposes PSCI 0.2 through the guest device tree. The barriers make
	 * the terminal UART evidence visible before the VM leaves the run state.
	 */
	__asm__ volatile("dsb sy\n\t"
			 "isb\n\t"
			 "smc #0"
			 : "+r"(function_id)
			 :
			 : "x1", "x2", "x3", "memory");
	for (;;) {
		__asm__ volatile("wfe");
	}
}

#endif /* IVC_AARCH64_PSCI_H_ */

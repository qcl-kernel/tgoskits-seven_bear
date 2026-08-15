/* SPDX-License-Identifier: Apache-2.0 */

#ifndef IVC_RTTHREAD_NETWORK_H_
#define IVC_RTTHREAD_NETWORK_H_

#include <stdbool.h>
#include <stdint.h>

bool ivc_rtthread_network_start(void);
uint64_t ivc_rtthread_monotonic_us(void *context);

#endif /* IVC_RTTHREAD_NETWORK_H_ */

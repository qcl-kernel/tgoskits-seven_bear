/* SPDX-License-Identifier: Apache-2.0 */

#include "network.h"

#include "virtio_net_mmio.h"

#include <FreeRTOS.h>
#include <FreeRTOS_IP.h>
#include <FreeRTOS_IP_Private.h>
#include <NetworkBufferManagement.h>
#include <NetworkInterface.h>
#include <task.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <sysregs.h>

#define IVC_VIRTIO_MMIO_BASE ((uintptr_t)UINT32_C(0x0b000000))
#define IVC_NETWORK_POLL_STACK_DEPTH 2048U
#define IVC_NETWORK_POLL_PRIORITY (configMAX_PRIORITIES - 3U)

static const uint8_t expected_mac[6] = {0x52, 0x54, 0x00, 0x00, 0x00, 0x02};

struct ivc_freertos_network {
	struct ivc_virtio_net virtio;
	NetworkInterface_t *interface;
	TaskHandle_t poll_task;
	uint8_t rx_frame[IVC_VIRTIO_NET_MAX_FRAME_LENGTH];
	bool initialized;
	bool fault_reported;
};

static struct ivc_freertos_network network;

uint64_t ivc_freertos_monotonic_us(void *context)
{
	uint64_t counter = sysreg_cntvct_el0_read();
	uint64_t frequency = sysreg_cntfrq_el0_read();

	(void)context;
	if (frequency == 0U) {
		return 0U;
	}
	return (counter / frequency) * UINT64_C(1000000) +
	       ((counter % frequency) * UINT64_C(1000000)) / frequency;
}

static void cpu_relax(void *context)
{
	(void)context;
	__asm__ volatile("yield" ::: "memory");
}

static void network_poll_entry(void *parameter)
{
	struct ivc_freertos_network *adapter = parameter;

	for (;;) {
		int length;

		ivc_virtio_net_ack_interrupt(&adapter->virtio);
		while ((length = ivc_virtio_net_receive(&adapter->virtio,
						 adapter->rx_frame,
						 sizeof(adapter->rx_frame))) > 0) {
			NetworkBufferDescriptor_t *descriptor =
				pxGetNetworkBufferWithDescriptor((size_t)length, 0U);
			IPStackEvent_t event = {
				.eEventType = eNetworkRxEvent,
				.pvData = descriptor,
			};

			if (descriptor == NULL) {
				printf("IVC-RTOS-NET-ERROR rtos=freertos "
				       "stage=rx-allocate\n");
				continue;
			}
			memcpy(descriptor->pucEthernetBuffer, adapter->rx_frame,
			       (size_t)length);
			descriptor->xDataLength = (size_t)length;
			descriptor->pxInterface = adapter->interface;
			descriptor->pxEndPoint = FreeRTOS_MatchingEndpoint(
				adapter->interface, descriptor->pucEthernetBuffer);
			if (descriptor->pxEndPoint == NULL ||
			    xSendEventStructToIPTask(&event, 0U) != pdPASS) {
				vReleaseNetworkBufferAndDescriptor(descriptor);
			}
		}
		if (length < 0 && !adapter->fault_reported) {
			adapter->fault_reported = true;
			printf("IVC-RTOS-FATAL rtos=freertos stage=rx reason=%s\n",
			       ivc_virtio_net_error_name(adapter->virtio.last_error));
		}
		vTaskDelay(pdMS_TO_TICKS(1U));
	}
}

static BaseType_t network_initialize(NetworkInterface_t *interface)
{
	const uint8_t *mac;

	if (network.initialized) {
		return pdPASS;
	}
	network.interface = interface;
	if (!ivc_virtio_net_init(&network.virtio, IVC_VIRTIO_MMIO_BASE,
				 ivc_freertos_monotonic_us, cpu_relax, NULL)) {
		printf("IVC-RTOS-FATAL rtos=freertos stage=virtio-init reason=%s\n",
		       ivc_virtio_net_error_name(network.virtio.last_error));
		return pdFAIL;
	}
	mac = ivc_virtio_net_mac(&network.virtio);
	if (memcmp(mac, expected_mac, sizeof(expected_mac)) != 0) {
		printf("IVC-RTOS-FATAL rtos=freertos stage=mac "
		       "actual=%02x:%02x:%02x:%02x:%02x:%02x\n",
		       mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
		return pdFAIL;
	}
	if (xTaskCreate(network_poll_entry, "ivcnet",
			IVC_NETWORK_POLL_STACK_DEPTH, &network,
			IVC_NETWORK_POLL_PRIORITY, &network.poll_task) != pdPASS) {
		printf("IVC-RTOS-FATAL rtos=freertos stage=network-poll\n");
		return pdFAIL;
	}
	network.initialized = true;
	printf("IVC-RTOS-NET rtos=freertos "
	       "mac=52:54:00:00:00:02 ip=10.0.0.2/24 mmio=0x0b000000\n");
	return pdPASS;
}

static BaseType_t network_output(NetworkInterface_t *interface,
				 NetworkBufferDescriptor_t *descriptor,
				 BaseType_t release_after_send)
{
	BaseType_t result = pdFAIL;

	(void)interface;
	if (descriptor != NULL && descriptor->xDataLength > 0U &&
	    descriptor->xDataLength <= IVC_VIRTIO_NET_MAX_FRAME_LENGTH &&
	    ivc_virtio_net_transmit(&network.virtio,
				    descriptor->pucEthernetBuffer,
				    descriptor->xDataLength)) {
		result = pdPASS;
	} else {
		printf("IVC-RTOS-NET-ERROR rtos=freertos stage=tx reason=%s\n",
		       ivc_virtio_net_error_name(network.virtio.last_error));
	}
	if (release_after_send != pdFALSE && descriptor != NULL) {
		vReleaseNetworkBufferAndDescriptor(descriptor);
	}
	return result;
}

static BaseType_t network_link_status(NetworkInterface_t *interface)
{
	(void)interface;
	return network.initialized ? pdTRUE : pdFALSE;
}

NetworkInterface_t *pxFillInterfaceDescriptor(BaseType_t index,
					      NetworkInterface_t *interface)
{
	static char interface_name[] = "ivc0";

	if (index != 0 || interface == NULL) {
		return NULL;
	}
	memset(interface, 0, sizeof(*interface));
	interface->pcName = interface_name;
	interface->pvArgument = &network;
	interface->pfInitialise = network_initialize;
	interface->pfOutput = network_output;
	interface->pfGetPhyLinkStatus = network_link_status;
	FreeRTOS_AddNetworkInterface(interface);
	return interface;
}

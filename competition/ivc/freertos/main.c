/* SPDX-License-Identifier: Apache-2.0 */

#include "ivc_rtos_server.h"
#include "network.h"

#include <FreeRTOS.h>
#include <FreeRTOS_IP.h>
#include <FreeRTOS_Sockets.h>
#include <task.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef IVC_EXPECTED_COMMANDS
#define IVC_EXPECTED_COMMANDS 100U
#endif

#ifndef IVC_EXPECTED_PROTOCOL_ERRORS
#define IVC_EXPECTED_PROTOCOL_ERRORS 0U
#endif

#ifndef IVC_DROP_ACK_EVERY
#define IVC_DROP_ACK_EVERY 0U
#endif

#define IVC_LOCAL_ADDRESS "10.0.0.2"
#define IVC_LOCAL_PORT 5500U
#define IVC_SERVER_STACK_DEPTH 4096U
#define IVC_SERVER_PRIORITY (configMAX_PRIORITIES - 4U)

struct socket_transport {
	Socket_t socket;
};

static volatile bool network_up;

BaseType_t xApplicationGetRandomNumber(uint32_t *number)
{
	static uint32_t state = UINT32_C(0x6d2b79f5);

	if (number == NULL) {
		return pdFAIL;
	}
	taskENTER_CRITICAL();
	state ^= state << 13U;
	state ^= state >> 17U;
	state ^= state << 5U;
	*number = state;
	taskEXIT_CRITICAL();
	return pdPASS;
}

static Socket_t open_socket(void)
{
	struct freertos_sockaddr local = {
		.sin_len = sizeof(local),
		.sin_family = FREERTOS_AF_INET4,
		.sin_port = FreeRTOS_htons(IVC_LOCAL_PORT),
		.sin_addr = FreeRTOS_inet_addr_quick(10U, 0U, 0U, 2U),
	};
	TickType_t timeout = pdMS_TO_TICKS(IVC_RTOS_SOCKET_POLL_MS);
	Socket_t socket = FreeRTOS_socket(FREERTOS_AF_INET4, FREERTOS_SOCK_DGRAM,
					 FREERTOS_IPPROTO_UDP);

	if (socket == FREERTOS_INVALID_SOCKET ||
	    FreeRTOS_setsockopt(socket, 0, FREERTOS_SO_RCVTIMEO, &timeout,
				 sizeof(timeout)) != 0 ||
	    FreeRTOS_bind(socket, &local, sizeof(local)) != 0) {
		if (socket != FREERTOS_INVALID_SOCKET) {
			(void)FreeRTOS_closesocket(socket);
		}
		return FREERTOS_INVALID_SOCKET;
	}
	return socket;
}

static int socket_receive(void *context, uint8_t *frame, size_t capacity,
			  struct ivc_rtos_peer *peer, uint32_t timeout_ms)
{
	struct socket_transport *transport = context;
	struct freertos_sockaddr address;
	socklen_t address_length = sizeof(address);
	int32_t result;

	(void)timeout_ms;
	result = FreeRTOS_recvfrom(transport->socket, frame, capacity, 0,
				  &address, &address_length);
	if (result < 0) {
		return 0;
	}
	if (address_length > sizeof(peer->bytes)) {
		return -1;
	}
	memcpy(peer->bytes, &address, address_length);
	peer->length = address_length;
	return (int)result;
}

static bool socket_send(void *context, const uint8_t *frame, size_t length,
			const struct ivc_rtos_peer *peer)
{
	struct socket_transport *transport = context;

	if (peer->length == 0U || peer->length > sizeof(peer->bytes)) {
		return false;
	}
	return FreeRTOS_sendto(transport->socket, frame, length, 0,
			       (const struct freertos_sockaddr *)peer->bytes,
			       (socklen_t)peer->length) == (int32_t)length;
}

static void log_line(void *context, const char *line)
{
	(void)context;
	printf("%s\n", line);
}

static void server_entry(void *parameter)
{
	struct socket_transport socket_context;
	struct ivc_rtos_transport transport;
	const struct ivc_rtos_server_config config = {
		.rtos_name = "freertos",
		.local_address = IVC_LOCAL_ADDRESS,
		.local_port = IVC_LOCAL_PORT,
		.expected_commands = IVC_EXPECTED_COMMANDS,
		.expected_protocol_errors = IVC_EXPECTED_PROTOCOL_ERRORS,
		.drop_ack_every = IVC_DROP_ACK_EVERY,
	};

	(void)parameter;
	while (!network_up) {
		vTaskDelay(pdMS_TO_TICKS(10U));
	}
	socket_context.socket = open_socket();
	if (socket_context.socket == FREERTOS_INVALID_SOCKET) {
		printf("IVC-RTOS-FATAL rtos=freertos stage=socket\n");
		vTaskSuspend(NULL);
	}
	transport = (struct ivc_rtos_transport){
		.now_us = ivc_freertos_monotonic_us,
		.receive = socket_receive,
		.send = socket_send,
		.log_line = log_line,
		.context = &socket_context,
	};
	(void)ivc_rtos_server_run(&config, &transport);
	vTaskSuspend(NULL);
}

void vApplicationIPNetworkEventHook(eIPCallbackEvent_t event)
{
	if (event == eNetworkUp) {
		network_up = true;
	}
}

void vApplicationMallocFailedHook(void)
{
	printf("IVC-RTOS-FATAL rtos=freertos stage=malloc\n");
	for (;;) {
		__asm__ volatile("wfe");
	}
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *task_name)
{
	(void)task;
	printf("IVC-RTOS-FATAL rtos=freertos stage=stack task=%s\n",
	       task_name == NULL ? "unknown" : task_name);
	for (;;) {
		__asm__ volatile("wfe");
	}
}

void vApplicationAssert(const char *file, uint32_t line)
{
	printf("IVC-RTOS-FATAL rtos=freertos stage=assert file=%s line=%u\n",
	       file, (unsigned int)line);
	for (;;) {
		__asm__ volatile("wfe");
	}
}

int main(void)
{
	static const uint8_t ip_address[4] = {10U, 0U, 0U, 2U};
	static const uint8_t netmask[4] = {255U, 255U, 255U, 0U};
	static const uint8_t gateway[4] = {0U, 0U, 0U, 0U};
	static const uint8_t dns_server[4] = {0U, 0U, 0U, 0U};
	static const uint8_t mac_address[6] = {0x52, 0x54, 0x00,
					       0x00, 0x00, 0x02};

	if (FreeRTOS_IPInit(ip_address, netmask, gateway, dns_server,
			    mac_address) != pdPASS ||
	    xTaskCreate(server_entry, "ivc", IVC_SERVER_STACK_DEPTH, NULL,
			IVC_SERVER_PRIORITY, NULL) != pdPASS) {
		printf("IVC-RTOS-FATAL rtos=freertos stage=init\n");
		return 1;
	}
	vTaskStartScheduler();
	printf("IVC-RTOS-FATAL rtos=freertos stage=scheduler-return\n");
	return 1;
}

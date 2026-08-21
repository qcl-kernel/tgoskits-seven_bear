/* SPDX-License-Identifier: Apache-2.0 */

#include "aarch64_psci.h"
#include "ivc_rtos_server.h"
#include "network.h"

#include <lwip/inet.h>
#include <lwip/sockets.h>
#include <rtthread.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
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

#ifndef IVC_STOP_AFTER_RESULT
#define IVC_STOP_AFTER_RESULT 0U
#endif

#define IVC_LOCAL_ADDRESS "10.0.0.2"
#define IVC_LOCAL_PORT 5500U

struct socket_transport {
	int socket;
};

static int open_socket(void)
{
	struct sockaddr_in local = {
		.sin_family = AF_INET,
		.sin_port = htons(IVC_LOCAL_PORT),
		.sin_addr.s_addr = inet_addr(IVC_LOCAL_ADDRESS),
	};
	const struct timeval timeout = {
		.tv_sec = IVC_RTOS_SOCKET_POLL_MS / 1000U,
		.tv_usec = (IVC_RTOS_SOCKET_POLL_MS % 1000U) * 1000U,
	};
	int socket_fd = lwip_socket(AF_INET, SOCK_DGRAM, 0);

	if (socket_fd < 0 ||
	    lwip_setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout,
			    sizeof(timeout)) != 0 ||
	    lwip_bind(socket_fd, (const struct sockaddr *)&local, sizeof(local)) != 0) {
		if (socket_fd >= 0) {
			(void)lwip_close(socket_fd);
		}
		return -1;
	}
	return socket_fd;
}

static int socket_receive(void *context, uint8_t *frame, size_t capacity,
			  struct ivc_rtos_peer *peer, uint32_t timeout_ms)
{
	struct socket_transport *transport = context;
	struct sockaddr_in address;
	socklen_t address_length = sizeof(address);
	int result;

	(void)timeout_ms;
	result = lwip_recvfrom(transport->socket, frame, capacity, 0,
			       (struct sockaddr *)&address, &address_length);
	if (result < 0) {
		return 0;
	}
	if (address_length > sizeof(peer->bytes)) {
		return -1;
	}
	memcpy(peer->bytes, &address, address_length);
	peer->length = address_length;
	return result;
}

static bool socket_send(void *context, const uint8_t *frame, size_t length,
			const struct ivc_rtos_peer *peer)
{
	struct socket_transport *transport = context;

	if (peer->length == 0U || peer->length > sizeof(peer->bytes)) {
		return false;
	}
	return lwip_sendto(transport->socket, frame, length, 0,
			   (const struct sockaddr *)peer->bytes,
			   (socklen_t)peer->length) == (int)length;
}

static void log_line(void *context, const char *line)
{
	(void)context;
	rt_kprintf("%s\n", line);
}

static void sleep_ms(void *context, uint32_t milliseconds)
{
	(void)context;
	rt_thread_mdelay(milliseconds);
}

static void power_off(void *context)
{
	(void)context;
	ivc_aarch64_psci_system_off();
}

int main(void)
{
	struct socket_transport socket_context;
	struct ivc_rtos_transport transport;
	const struct ivc_rtos_server_config config = {
		.rtos_name = "rt-thread",
		.local_address = IVC_LOCAL_ADDRESS,
		.local_port = IVC_LOCAL_PORT,
		.expected_commands = IVC_EXPECTED_COMMANDS,
		.expected_protocol_errors = IVC_EXPECTED_PROTOCOL_ERRORS,
		.drop_ack_every = IVC_DROP_ACK_EVERY,
		.stop_after_result = IVC_STOP_AFTER_RESULT != 0U,
	};

	if (!ivc_rtthread_network_start()) {
		return 1;
	}
	rt_thread_mdelay(100U);
	socket_context.socket = open_socket();
	if (socket_context.socket < 0) {
		rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=socket\n");
		return 1;
	}
	transport = (struct ivc_rtos_transport){
		.now_us = ivc_rtthread_monotonic_us,
		.receive = socket_receive,
		.send = socket_send,
		.log_line = log_line,
		.sleep_ms = sleep_ms,
		.power_off = power_off,
		.context = &socket_context,
	};
	return ivc_rtos_server_run(&config, &transport);
}

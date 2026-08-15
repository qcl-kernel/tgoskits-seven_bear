/* SPDX-License-Identifier: Apache-2.0 */

#ifndef IVC_RTOS_SERVER_H_
#define IVC_RTOS_SERVER_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define IVC_RTOS_PEER_CAPACITY 32U
#define IVC_RTOS_SOCKET_POLL_MS 100U

struct ivc_rtos_peer {
	uint8_t bytes[IVC_RTOS_PEER_CAPACITY];
	size_t length;
};

struct ivc_rtos_transport {
	uint64_t (*now_us)(void *context);
	int (*receive)(void *context, uint8_t *frame, size_t capacity,
		       struct ivc_rtos_peer *peer, uint32_t timeout_ms);
	bool (*send)(void *context, const uint8_t *frame, size_t length,
		     const struct ivc_rtos_peer *peer);
	void (*log_line)(void *context, const char *line);
	void *context;
};

struct ivc_rtos_server_config {
	const char *rtos_name;
	const char *local_address;
	uint16_t local_port;
	uint32_t expected_commands;
	uint32_t expected_protocol_errors;
	uint32_t drop_ack_every;
	bool stop_after_result;
};

int ivc_rtos_server_run(const struct ivc_rtos_server_config *config,
			const struct ivc_rtos_transport *transport);

#endif /* IVC_RTOS_SERVER_H_ */

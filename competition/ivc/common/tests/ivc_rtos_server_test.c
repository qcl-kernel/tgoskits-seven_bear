/* SPDX-License-Identifier: Apache-2.0 */

#include "ivc_rtos_server.h"

#include "protocol.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define TEST_DATAGRAM_CAPACITY 8U
#define TEST_RESPONSE_CAPACITY 16U
#define TEST_LOG_CAPACITY 32U
#define TEST_LOG_LINE_CAPACITY 320U

struct test_datagram {
	uint8_t bytes[IVC_MAX_FRAME_LENGTH];
	size_t length;
};

struct test_transport {
	struct test_datagram incoming[TEST_DATAGRAM_CAPACITY];
	size_t incoming_count;
	size_t incoming_index;
	struct test_datagram outgoing[TEST_RESPONSE_CAPACITY];
	size_t outgoing_count;
	char logs[TEST_LOG_CAPACITY][TEST_LOG_LINE_CAPACITY];
	size_t log_count;
	uint64_t now_us;
};

static void append_control(struct test_transport *transport, uint32_t sequence)
{
	const struct ivc_control_command command = {
		.operation = IVC_CONTROL_SET_ACTUATOR,
		.mode = IVC_MODE_NEURAL,
		.actuator_permille = (uint16_t)(300U + sequence),
		.setpoint_milli_c = 45000,
		.sample_id = sequence,
	};
	const struct ivc_header header = {
		.message_type = IVC_MESSAGE_CONTROL,
		.flags = IVC_FLAG_ACK_REQUIRED,
		.session_id = UINT32_C(0x4354524c),
		.sequence = sequence,
		.timestamp_us = (uint64_t)sequence * UINT64_C(1000),
		.payload_length = IVC_CONTROL_PAYLOAD_LENGTH,
		.error_code = IVC_ERROR_NONE,
	};
	struct test_datagram *datagram;
	uint8_t payload[IVC_CONTROL_PAYLOAD_LENGTH];

	assert(transport->incoming_count < TEST_DATAGRAM_CAPACITY);
	datagram = &transport->incoming[transport->incoming_count++];
	assert(ivc_encode_control(&command, payload));
	assert(ivc_encode_frame(&header, payload, datagram->bytes,
				sizeof(datagram->bytes), &datagram->length));
}

static uint64_t test_now_us(void *context)
{
	const struct test_transport *transport = context;

	return transport->now_us;
}

static int test_receive(void *context, uint8_t *frame, size_t capacity,
			struct ivc_rtos_peer *peer, uint32_t timeout_ms)
{
	struct test_transport *transport = context;
	const struct test_datagram *datagram;

	(void)timeout_ms;
	transport->now_us += UINT64_C(1000);
	if (transport->incoming_index == transport->incoming_count) {
		return 0;
	}
	datagram = &transport->incoming[transport->incoming_index++];
	assert(datagram->length <= capacity);
	memcpy(frame, datagram->bytes, datagram->length);
	peer->bytes[0] = 1U;
	peer->length = 1U;
	return (int)datagram->length;
}

static bool test_send(void *context, const uint8_t *frame, size_t length,
		      const struct ivc_rtos_peer *peer)
{
	struct test_transport *transport = context;
	struct test_datagram *datagram;

	assert(peer->length == 1U);
	assert(transport->outgoing_count < TEST_RESPONSE_CAPACITY);
	assert(length <= IVC_MAX_FRAME_LENGTH);
	datagram = &transport->outgoing[transport->outgoing_count++];
	memcpy(datagram->bytes, frame, length);
	datagram->length = length;
	return true;
}

static void test_log_line(void *context, const char *line)
{
	struct test_transport *transport = context;

	assert(transport->log_count < TEST_LOG_CAPACITY);
	assert(strlen(line) < TEST_LOG_LINE_CAPACITY);
	strcpy(transport->logs[transport->log_count++], line);
}

static bool has_log(const struct test_transport *transport, const char *fragment)
{
	size_t index;

	for (index = 0U; index < transport->log_count; ++index) {
		if (strstr(transport->logs[index], fragment) != NULL) {
			return true;
		}
	}
	return false;
}

static void assert_response_counts(const struct test_transport *transport,
				   size_t expected_status, size_t expected_ack)
{
	size_t status_count = 0U;
	size_t ack_count = 0U;
	size_t index;

	for (index = 0U; index < transport->outgoing_count; ++index) {
		struct ivc_frame_view frame;
		const struct test_datagram *datagram = &transport->outgoing[index];

		assert(ivc_decode_frame(datagram->bytes, datagram->length, &frame) ==
		       IVC_DECODE_OK);
		assert(frame.header.session_id == UINT32_C(0x4354524c));
		if (frame.header.message_type == IVC_MESSAGE_STATUS) {
			++status_count;
		} else {
			assert(frame.header.message_type == IVC_MESSAGE_ACK);
			++ack_count;
		}
	}
	assert(status_count == expected_status);
	assert(ack_count == expected_ack);
}

static struct ivc_rtos_transport transport_api(struct test_transport *context)
{
	return (struct ivc_rtos_transport){
		.now_us = test_now_us,
		.receive = test_receive,
		.send = test_send,
		.log_line = test_log_line,
		.context = context,
	};
}

static void test_normal_campaign_reports_exact_counts(void)
{
	struct test_transport context = {0};
	const struct ivc_rtos_server_config config = {
		.rtos_name = "test-rtos",
		.local_address = "10.0.0.2",
		.local_port = 5500U,
		.expected_commands = 3U,
		.expected_protocol_errors = 0U,
		.drop_ack_every = 0U,
		.stop_after_result = true,
	};
	struct ivc_rtos_transport transport = transport_api(&context);
	uint32_t sequence;

	for (sequence = 1U; sequence <= config.expected_commands; ++sequence) {
		append_control(&context, sequence);
	}
	assert(ivc_rtos_server_run(&config, &transport) == 0);
	assert(context.incoming_index == context.incoming_count);
	assert_response_counts(&context, 3U, 3U);
	assert(has_log(&context, "IVC-RTOS-SELFTEST PASS rtos=test-rtos"));
	assert(has_log(&context, "IVC-RTOS-RESULT rtos=test-rtos profile=normal "
				 "accepted=3 applied=3 duplicates=0 acks_dropped=0 "
				 "status_sent=3 acks_sent=3 errors_sent=0 "
				 "protocol_errors=0"));
}

static void test_ack_loss_recovery_does_not_reapply_control(void)
{
	struct test_transport context = {0};
	const struct ivc_rtos_server_config config = {
		.rtos_name = "test-rtos",
		.local_address = "10.0.0.2",
		.local_port = 5500U,
		.expected_commands = 5U,
		.expected_protocol_errors = 0U,
		.drop_ack_every = 5U,
		.stop_after_result = true,
	};
	struct ivc_rtos_transport transport = transport_api(&context);
	uint32_t sequence;

	for (sequence = 1U; sequence <= config.expected_commands; ++sequence) {
		append_control(&context, sequence);
	}
	append_control(&context, 5U);
	assert(ivc_rtos_server_run(&config, &transport) == 0);
	assert(context.incoming_index == context.incoming_count);
	assert_response_counts(&context, 6U, 5U);
	assert(has_log(&context,
		       "IVC-RTOS-INJECT rtos=test-rtos drop_ack_seq=5"));
	assert(has_log(&context,
		       "IVC-RTOS-DUPLICATE rtos=test-rtos seq=5 next_expected=6 "
		       "duplicates=1"));
	assert(has_log(&context, "IVC-RTOS-RESULT rtos=test-rtos profile=ack-loss "
				 "accepted=5 applied=5 duplicates=1 acks_dropped=1 "
				 "status_sent=6 acks_sent=5 errors_sent=0 "
				 "protocol_errors=0"));
}

static void test_invalid_configuration_is_rejected(void)
{
	struct test_transport context = {0};
	const struct ivc_rtos_server_config config = {
		.rtos_name = "test-rtos",
		.local_address = "10.0.0.2",
		.local_port = 5500U,
		.expected_commands = 4U,
		.drop_ack_every = 5U,
		.stop_after_result = true,
	};
	struct ivc_rtos_transport transport = transport_api(&context);

	assert(ivc_rtos_server_run(&config, &transport) == -1);
}

int main(void)
{
	test_normal_campaign_reports_exact_counts();
	test_ack_loss_recovery_does_not_reapply_control();
	test_invalid_configuration_is_rejected();
	puts("ivc-rtos-server-tests: PASS");
	return 0;
}

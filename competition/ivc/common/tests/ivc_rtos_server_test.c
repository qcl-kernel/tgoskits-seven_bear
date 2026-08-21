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
	uint32_t slept_ms;
	size_t power_off_count;
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

static void append_vision_decision(struct test_transport *transport, uint32_t sequence,
				   enum ivc_vision_action action)
{
	const bool detection_present = action != IVC_VISION_HOLD;
	const uint64_t inference_finished_at_us = (uint64_t)sequence * UINT64_C(1000);
	const struct ivc_vision_decision decision = {
		.requested_action = action,
		.safe_action = IVC_VISION_HOLD,
		.detection_present = detection_present,
		.frame_id = sequence,
		.captured_at_us = inference_finished_at_us - UINT64_C(500),
		.inference_finished_at_us = inference_finished_at_us,
		.ttl_us = 5000U,
		.class_id = detection_present ? 32U : IVC_NO_DETECTION_CLASS_ID,
		.confidence_q10000 = detection_present ? 8591U : 0U,
		.region_id = detection_present ? (uint16_t)action : 0U,
		.bounding_box = detection_present ?
			(struct ivc_bounding_box){.left = 517U, .top = 932U,
						  .right = 730U, .bottom = 1151U} :
			(struct ivc_bounding_box){0},
	};
	const struct ivc_header header = {
		.message_type = IVC_MESSAGE_VISION_DECISION,
		.flags = IVC_FLAG_ACK_REQUIRED,
		.session_id = UINT32_C(0x4354524c),
		.sequence = sequence,
		.timestamp_us = inference_finished_at_us + UINT64_C(100),
		.payload_length = IVC_VISION_DECISION_PAYLOAD_LENGTH,
		.error_code = IVC_ERROR_NONE,
	};
	struct test_datagram *datagram;
	uint8_t payload[IVC_VISION_DECISION_PAYLOAD_LENGTH];

	assert(transport->incoming_count < TEST_DATAGRAM_CAPACITY);
	datagram = &transport->incoming[transport->incoming_count++];
	assert(ivc_encode_vision_decision(&decision, payload));
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

static void test_sleep_ms(void *context, uint32_t milliseconds)
{
	struct test_transport *transport = context;

	transport->slept_ms += milliseconds;
}

static void test_power_off(void *context)
{
	struct test_transport *transport = context;

	transport->power_off_count++;
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
		.sleep_ms = test_sleep_ms,
		.power_off = test_power_off,
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
	assert(has_log(&context, "IVC-RTOS-OUTCOME profile=normal accepted=3 "
				 "applied=3 duplicates=0 acks_dropped=0"));
	assert(has_log(&context, "IVC-RTOS-MESSAGES status_sent=3 acks_sent=3 "
				 "errors_sent=0 protocol_errors=0"));
	assert(has_log(&context,
		       "IVC-RTOS-POWEROFF rtos=test-rtos accepted=3"));
	assert(context.slept_ms == 1000U);
	assert(context.power_off_count == 1U);
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
	assert(has_log(&context, "IVC-RTOS-OUTCOME profile=ack-loss accepted=5 "
				 "applied=5 duplicates=1 acks_dropped=1"));
	assert(has_log(&context, "IVC-RTOS-MESSAGES status_sent=6 acks_sent=5 "
				 "errors_sent=0 protocol_errors=0"));
}

static void test_visual_sorting_returns_actual_actions_and_acks(void)
{
	static const enum ivc_vision_action expected_actions[] = {
		IVC_VISION_SORT_LEFT,
		IVC_VISION_SORT_RIGHT,
		IVC_VISION_HOLD,
	};
	struct test_transport context = {0};
	const struct ivc_rtos_server_config config = {
		.rtos_name = "test-rtos",
		.local_address = "10.0.0.2",
		.local_port = 5500U,
		.expected_vision_decisions = 3U,
		.stop_after_result = true,
	};
	struct ivc_rtos_transport transport = transport_api(&context);
	size_t status_count = 0U;
	size_t ack_count = 0U;
	size_t index;

	append_vision_decision(&context, 1U, IVC_VISION_SORT_LEFT);
	append_vision_decision(&context, 2U, IVC_VISION_SORT_RIGHT);
	append_vision_decision(&context, 3U, IVC_VISION_HOLD);
	assert(ivc_rtos_server_run(&config, &transport) == 0);
	for (index = 0U; index < context.outgoing_count; ++index) {
		struct ivc_frame_view frame;
		struct ivc_actuator_status status;
		const struct test_datagram *datagram = &context.outgoing[index];

		assert(ivc_decode_frame(datagram->bytes, datagram->length, &frame) ==
		       IVC_DECODE_OK);
		if (frame.header.message_type == IVC_MESSAGE_ACTUATOR_STATUS) {
			assert(status_count < sizeof(expected_actions) /
						      sizeof(expected_actions[0]));
			assert(ivc_decode_actuator_status(frame.payload,
						  frame.header.payload_length, &status));
			assert(status.state == IVC_ACTUATOR_APPLIED);
			assert(status.requested_action == expected_actions[status_count]);
			assert(status.actual_action == expected_actions[status_count]);
			assert(status.frame_id == status_count + 1U);
			assert(status.decision_age_at_send_us == 100U);
			++status_count;
		} else {
			assert(frame.header.message_type == IVC_MESSAGE_ACK);
			++ack_count;
		}
	}
	assert(status_count == 3U);
	assert(ack_count == 3U);
	assert(has_log(&context, "IVC-RTOS-VISION rtos=test-rtos frame=1 "
				 "requested=left actual=left state=applied"));
	assert(has_log(&context, "IVC-RTOS-VISION-RESULT rtos=test-rtos "
				 "accepted=3 applied=3 actuator_status_sent=3 "
				 "acks_sent=3 errors_sent=0 protocol_errors=0"));
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
	test_visual_sorting_returns_actual_actions_and_acks();
	test_invalid_configuration_is_rejected();
	puts("ivc-rtos-server-tests: PASS");
	return 0;
}

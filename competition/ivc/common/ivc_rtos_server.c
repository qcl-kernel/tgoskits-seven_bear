/* SPDX-License-Identifier: Apache-2.0 */

#include "ivc_rtos_server.h"

#include "endpoint.h"
#include "protocol.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define IVC_LOG_LINE_CAPACITY 320U
#define IVC_RESULT_RECORD_COPIES 2U
#define IVC_POWEROFF_INITIAL_PAUSE_MS 500U
#define IVC_POWEROFF_RECORD_COPIES 5U
#define IVC_POWEROFF_RECORD_PAUSE_MS 100U

struct server_state {
	struct ivc_receive_window receive_window;
	struct ivc_endpoint endpoint;
	struct ivc_vision_endpoint vision_endpoint;
	struct ivc_thermal_plant plant;
	struct ivc_ack_loss_policy ack_loss;
	uint32_t applied_commands;
	uint32_t applied_vision_decisions;
	uint64_t protocol_errors;
	uint64_t status_sent;
	uint64_t acknowledgements_sent;
	uint64_t errors_sent;
	uint64_t safe_fallbacks;
	uint64_t actuator_status_sent;
	struct ivc_actuator_status last_actuator_status;
	struct ivc_header last_vision_request;
	struct ivc_rtos_peer last_vision_peer;
	bool has_last_vision_response;
	bool result_reported;
};

static uint8_t receive_frame[IVC_MAX_FRAME_LENGTH];
static uint8_t transmit_frame[IVC_MAX_FRAME_LENGTH];

static void log_message(const struct ivc_rtos_transport *transport,
			const char *format, ...)
{
	char line[IVC_LOG_LINE_CAPACITY];
	va_list arguments;
	int length;

	va_start(arguments, format);
	length = vsnprintf(line, sizeof(line), format, arguments);
	va_end(arguments);
	if (length < 0) {
		transport->log_line(transport->context,
				    "IVC-RTOS-FATAL stage=format-log");
		return;
	}
	line[sizeof(line) - 1U] = '\0';
	transport->log_line(transport->context, line);
}

static bool send_payload(const struct ivc_rtos_transport *transport,
			 const struct ivc_rtos_peer *peer,
			 const struct ivc_header *request,
			 enum ivc_message_type message_type,
			 enum ivc_error_code error_code, const uint8_t *payload,
			 uint16_t payload_length)
{
	const struct ivc_header response = {
		.message_type = message_type,
		.flags = 0U,
		.session_id = request->session_id,
		.sequence = request->sequence,
		.timestamp_us = transport->now_us(transport->context),
		.payload_length = payload_length,
		.error_code = error_code,
	};
	size_t frame_length;

	if (!ivc_encode_frame(&response, payload, transmit_frame,
			      sizeof(transmit_frame), &frame_length)) {
		log_message(transport,
			    "IVC-RTOS-FATAL stage=encode-response seq=%u type=%u",
			    request->sequence, (unsigned int)message_type);
		return false;
	}
	if (!transport->send(transport->context, transmit_frame, frame_length,
			     peer)) {
		log_message(transport, "IVC-RTOS-TX-ERROR seq=%u type=%u",
			    request->sequence, (unsigned int)message_type);
		return false;
	}
	return true;
}

static bool send_status(struct server_state *server,
			const struct ivc_rtos_transport *transport,
			const struct ivc_rtos_peer *peer,
			const struct ivc_header *request)
{
	const struct ivc_status_report status = ivc_endpoint_status(
		&server->endpoint, ivc_thermal_plant_temperature(&server->plant));
	uint8_t payload[IVC_STATUS_PAYLOAD_LENGTH];

	if (!ivc_encode_status(&status, payload) ||
	    !send_payload(transport, peer, request, IVC_MESSAGE_STATUS,
			  IVC_ERROR_NONE, payload, sizeof(payload))) {
		return false;
	}
	server->status_sent++;
	return true;
}

static bool send_actuator_status(struct server_state *server,
				 const struct ivc_rtos_transport *transport,
				 const struct ivc_rtos_peer *peer,
				 const struct ivc_header *request,
				 const struct ivc_actuator_status *status)
{
	uint8_t payload[IVC_ACTUATOR_STATUS_PAYLOAD_LENGTH];

	if (!ivc_encode_actuator_status(status, payload) ||
	    !send_payload(transport, peer, request, IVC_MESSAGE_ACTUATOR_STATUS,
			  IVC_ERROR_NONE, payload, sizeof(payload))) {
		return false;
	}
	server->actuator_status_sent++;
	return true;
}

static bool send_ack(struct server_state *server,
		     const struct ivc_rtos_transport *transport,
		     const struct ivc_rtos_peer *peer,
		     const struct ivc_header *request)
{
	const struct ivc_ack_payload ack =
		ivc_receive_window_ack(&server->receive_window, request->sequence);
	uint8_t payload[IVC_ACK_PAYLOAD_LENGTH];

	if (!ivc_encode_ack(&ack, payload) ||
	    !send_payload(transport, peer, request, IVC_MESSAGE_ACK,
			  IVC_ERROR_NONE, payload, sizeof(payload))) {
		return false;
	}
	server->acknowledgements_sent++;
	return true;
}

static void reject_request(struct server_state *server,
			   const struct ivc_rtos_transport *transport,
			   const struct ivc_rtos_peer *peer,
			   const struct ivc_header *request,
			   enum ivc_error_code error_code, const char *reason)
{
	const struct ivc_error_payload error = {
		.offending_message_type = request->message_type,
		.offending_sequence = request->sequence,
	};
	uint8_t payload[IVC_ERROR_PAYLOAD_LENGTH];

	server->protocol_errors++;
	log_message(transport, "IVC-RTOS-ERROR seq=%u code=%u reason=%s",
		    request->sequence, (unsigned int)error_code, reason);
	if (ivc_encode_error_payload(&error, payload) &&
	    send_payload(transport, peer, request, IVC_MESSAGE_ERROR, error_code,
			 payload, sizeof(payload))) {
		server->errors_sent++;
	}
}

static enum ivc_error_code delivery_error(enum ivc_delivery delivery)
{
	return delivery == IVC_DELIVERY_SEQUENCE_EXHAUSTED ? IVC_ERROR_INTERNAL :
							    IVC_ERROR_SEQUENCE_OUTSIDE_WINDOW;
}

static const char *delivery_error_name(enum ivc_delivery delivery)
{
	switch (delivery) {
	case IVC_DELIVERY_NEW_OUT_OF_ORDER:
	case IVC_DELIVERY_OUTSIDE_WINDOW:
		return "sequence-outside-window";
	case IVC_DELIVERY_INVALID_IDENTIFIER:
		return "zero-session-or-sequence";
	case IVC_DELIVERY_SEQUENCE_EXHAUSTED:
		return "sequence-exhausted";
	case IVC_DELIVERY_SESSION_REJECTED:
		return "retired-or-invalid-session";
	default:
		return "invalid-delivery";
	}
}

static bool delivery_rejected(enum ivc_delivery delivery)
{
	return delivery == IVC_DELIVERY_NEW_OUT_OF_ORDER ||
	       delivery == IVC_DELIVERY_OUTSIDE_WINDOW ||
	       delivery == IVC_DELIVERY_INVALID_IDENTIFIER ||
	       delivery == IVC_DELIVERY_SEQUENCE_EXHAUSTED ||
	       delivery == IVC_DELIVERY_SESSION_REJECTED;
}

static void report_progress(const struct ivc_rtos_server_config *config,
			    const struct ivc_rtos_transport *transport,
			    const struct server_state *server,
			    const struct ivc_header *header,
			    const struct ivc_control_command *command)
{
	if (server->applied_commands != 1U &&
	    (server->applied_commands % 100U) != 0U &&
	    (config->expected_commands == 0U ||
	     server->applied_commands != config->expected_commands)) {
		return;
	}
	log_message(transport,
		    "IVC-RTOS-PROGRESS rtos=%s accepted=%u seq=%u mode=%s "
		    "actuator_permille=%u measured_milli_c=%d duplicates=%llu "
		    "protocol_errors=%llu",
		    config->rtos_name, server->applied_commands, header->sequence,
		    ivc_control_mode_name(command->mode),
		    (unsigned int)server->endpoint.actuator_permille,
		    ivc_thermal_plant_temperature(&server->plant),
		    (unsigned long long)server->receive_window.metrics.duplicates,
		    (unsigned long long)server->protocol_errors);
}

static bool report_result_if_complete(const struct ivc_rtos_server_config *config,
				      const struct ivc_rtos_transport *transport,
				      struct server_state *server)
{
	uint64_t expected_drops;
	uint32_t expected_messages;
	const char *profile;

	expected_messages = config->expected_vision_decisions != 0U ?
		config->expected_vision_decisions : config->expected_commands;
	if (server->result_reported || expected_messages == 0U ||
	    server->receive_window.metrics.accepted != expected_messages ||
	    server->protocol_errors != config->expected_protocol_errors ||
	    server->errors_sent != config->expected_protocol_errors) {
		return false;
	}
	if (config->expected_vision_decisions != 0U) {
		if (server->applied_vision_decisions != config->expected_vision_decisions ||
		    server->receive_window.metrics.duplicates != 0U) {
			return false;
		}
		log_message(transport,
			    "IVC-RTOS-VISION-RESULT rtos=%s accepted=%llu applied=%u "
			    "actuator_status_sent=%llu acks_sent=%llu errors_sent=%llu "
			    "protocol_errors=%llu",
			    config->rtos_name,
			    (unsigned long long)server->receive_window.metrics.accepted,
			    server->applied_vision_decisions,
			    (unsigned long long)server->actuator_status_sent,
			    (unsigned long long)server->acknowledgements_sent,
			    (unsigned long long)server->errors_sent,
			    (unsigned long long)server->protocol_errors);
		server->result_reported = true;
		return true;
	}
	expected_drops = config->drop_ack_every == 0U ? 0U :
		config->expected_commands / config->drop_ack_every;
	if (server->receive_window.metrics.duplicates != expected_drops ||
	    server->ack_loss.acknowledgements_dropped != expected_drops) {
		return false;
	}
	profile = config->drop_ack_every == 0U ? "normal" : "ack-loss";
	log_message(transport,
		    "IVC-RTOS-RESULT rtos=%s profile=%s accepted=%llu applied=%u "
		    "duplicates=%llu acks_dropped=%llu status_sent=%llu "
		    "acks_sent=%llu errors_sent=%llu protocol_errors=%llu",
		    config->rtos_name, profile,
		    (unsigned long long)server->receive_window.metrics.accepted,
		    server->applied_commands,
		    (unsigned long long)server->receive_window.metrics.duplicates,
		    (unsigned long long)server->ack_loss.acknowledgements_dropped,
		    (unsigned long long)server->status_sent,
		    (unsigned long long)server->acknowledgements_sent,
		    (unsigned long long)server->errors_sent,
		    (unsigned long long)server->protocol_errors);
	for (uint32_t copy = 0U; copy < IVC_RESULT_RECORD_COPIES; ++copy) {
		log_message(transport,
			    "IVC-RTOS-OUTCOME profile=%s accepted=%llu applied=%u "
			    "duplicates=%llu acks_dropped=%llu",
			    profile,
			    (unsigned long long)server->receive_window.metrics.accepted,
			    server->applied_commands,
			    (unsigned long long)server->receive_window.metrics.duplicates,
			    (unsigned long long)server->ack_loss.acknowledgements_dropped);
		log_message(transport,
			    "IVC-RTOS-MESSAGES status_sent=%llu acks_sent=%llu "
			    "errors_sent=%llu protocol_errors=%llu",
			    (unsigned long long)server->status_sent,
			    (unsigned long long)server->acknowledgements_sent,
			    (unsigned long long)server->errors_sent,
			    (unsigned long long)server->protocol_errors);
	}
	server->result_reported = true;
	return true;
}

static void report_poweroff_evidence(
	const struct ivc_rtos_server_config *config,
	const struct ivc_rtos_transport *transport,
	const struct server_state *server)
{
	uint32_t copy;

	/* The peer emits its terminal counters immediately after the final ACK.
	 * Replay a compact identity in the following quiet window before PSCI off.
	 */
	transport->sleep_ms(transport->context, IVC_POWEROFF_INITIAL_PAUSE_MS);
	for (copy = 0U; copy < IVC_POWEROFF_RECORD_COPIES; ++copy) {
		log_message(transport,
			    "IVC-RTOS-POWEROFF rtos=%s accepted=%llu",
			    config->rtos_name,
			    (unsigned long long)server->receive_window.metrics.accepted);
		transport->sleep_ms(transport->context,
				    IVC_POWEROFF_RECORD_PAUSE_MS);
	}
}

static const char *vision_action_name(enum ivc_vision_action action)
{
	switch (action) {
	case IVC_VISION_HOLD:
		return "hold";
	case IVC_VISION_SORT_LEFT:
		return "left";
	case IVC_VISION_SORT_RIGHT:
		return "right";
	case IVC_VISION_EMERGENCY_STOP:
		return "emergency-stop";
	default:
		return "unknown";
	}
}

static const char *actuator_state_name(enum ivc_actuator_state state)
{
	switch (state) {
	case IVC_ACTUATOR_APPLIED:
		return "applied";
	case IVC_ACTUATOR_SAFE_FALLBACK:
		return "safe-fallback";
	case IVC_ACTUATOR_REJECTED:
		return "rejected";
	case IVC_ACTUATOR_FAULT:
		return "fault";
	default:
		return "unknown";
	}
}

static void process_control(const struct ivc_rtos_server_config *config,
			    const struct ivc_rtos_transport *transport,
			    struct server_state *server,
			    const struct ivc_rtos_peer *peer,
			    const struct ivc_frame_view *frame,
			    const struct ivc_control_command *command)
{
	enum ivc_delivery delivery = ivc_receive_window_observe(
		&server->receive_window, frame->header.session_id,
		frame->header.sequence);
	bool drop_ack;

	if (delivery_rejected(delivery)) {
		reject_request(server, transport, peer, &frame->header,
			       delivery_error(delivery), delivery_error_name(delivery));
		return;
	}
	if (ivc_delivery_applies_control(delivery)) {
		enum ivc_apply_result result;
		uint64_t received_us;

		if (delivery == IVC_DELIVERY_NEW_SESSION) {
			ivc_endpoint_begin_session(&server->endpoint);
		}
		received_us = transport->now_us(transport->context);
		result = ivc_endpoint_apply(&server->endpoint, frame->header.sequence,
					    command, received_us, received_us);
		if (result != IVC_APPLY_APPLIED &&
		    result != IVC_APPLY_ENTERED_SAFE_STATE) {
			reject_request(server, transport, peer, &frame->header,
				       result == IVC_APPLY_INVALID_PAYLOAD ?
					       IVC_ERROR_INVALID_CONTROL :
					       IVC_ERROR_STALE_CONTROL,
				       ivc_apply_result_name(result));
			return;
		}
		ivc_thermal_plant_step(&server->plant,
				       server->endpoint.actuator_permille,
				       server->applied_commands);
		server->applied_commands++;
		report_progress(config, transport, server, &frame->header, command);
	} else {
		log_message(transport,
			    "IVC-RTOS-DUPLICATE rtos=%s seq=%u next_expected=%u "
			    "duplicates=%llu",
			    config->rtos_name, frame->header.sequence,
			    server->receive_window.next_sequence,
			    (unsigned long long)server->receive_window.metrics.duplicates);
	}

	(void)send_status(server, transport, peer, &frame->header);
	drop_ack = ivc_ack_loss_policy_should_drop(&server->ack_loss, delivery,
					   frame->header.sequence);
	if (drop_ack) {
		log_message(transport, "IVC-RTOS-INJECT rtos=%s drop_ack_seq=%u",
			    config->rtos_name, frame->header.sequence);
	} else {
		(void)send_ack(server, transport, peer, &frame->header);
	}
}

static void process_vision_decision(
	const struct ivc_rtos_server_config *config,
	const struct ivc_rtos_transport *transport, struct server_state *server,
	const struct ivc_rtos_peer *peer, const struct ivc_frame_view *frame,
	const struct ivc_vision_decision *decision)
{
	enum ivc_delivery delivery = ivc_receive_window_observe(
		&server->receive_window, frame->header.session_id,
		frame->header.sequence);
	struct ivc_actuator_status status;
	bool have_status = false;

	if (delivery_rejected(delivery)) {
		reject_request(server, transport, peer, &frame->header,
			       delivery_error(delivery), delivery_error_name(delivery));
		return;
	}
	if (ivc_delivery_applies_control(delivery)) {
		enum ivc_vision_apply_result result;
		uint64_t received_us;

		if (delivery == IVC_DELIVERY_NEW_SESSION) {
			ivc_vision_endpoint_begin_session(&server->vision_endpoint);
		}
		received_us = transport->now_us(transport->context);
		result = ivc_vision_endpoint_apply(
			&server->vision_endpoint, frame->header.sequence, decision,
			frame->header.timestamp_us, received_us, &status);
		if (result != IVC_VISION_APPLY_APPLIED) {
			reject_request(
				server, transport, peer, &frame->header,
				result == IVC_VISION_APPLY_EXPIRED ?
					IVC_ERROR_VISION_DECISION_EXPIRED :
					IVC_ERROR_INVALID_VISION_DECISION,
				result == IVC_VISION_APPLY_EXPIRED ?
					"vision-decision-expired" :
					"invalid-vision-decision");
			return;
		}
		server->last_actuator_status = status;
		server->last_vision_request = frame->header;
		server->last_vision_peer = *peer;
		server->has_last_vision_response = true;
		server->applied_vision_decisions++;
		have_status = true;
		log_message(transport,
			    "IVC-RTOS-VISION rtos=%s frame=%u requested=%s actual=%s "
			    "state=%s seq=%u age_at_send_us=%u local_apply_us=%u",
			    config->rtos_name, status.frame_id,
			    vision_action_name(status.requested_action),
			    vision_action_name(status.actual_action),
			    actuator_state_name(status.state), status.applied_sequence,
			    status.decision_age_at_send_us,
			    status.local_apply_latency_us);
	} else if (server->has_last_vision_response &&
		   server->last_actuator_status.applied_sequence ==
			   frame->header.sequence) {
		status = server->last_actuator_status;
		have_status = true;
		log_message(transport,
			    "IVC-RTOS-VISION-DUPLICATE rtos=%s frame=%u seq=%u",
			    config->rtos_name, status.frame_id, frame->header.sequence);
	}
	if (have_status) {
		(void)send_actuator_status(server, transport, peer, &frame->header,
					   &status);
	}
	(void)send_ack(server, transport, peer, &frame->header);
}

static void process_datagram(const struct ivc_rtos_server_config *config,
			     const struct ivc_rtos_transport *transport,
			     struct server_state *server,
			     const struct ivc_rtos_peer *peer, size_t length)
{
	struct ivc_decode_rejection rejection;
	struct ivc_frame_view frame;
	struct ivc_control_command command;
	struct ivc_vision_decision decision;
	enum ivc_decode_result decode_result =
		ivc_decode_frame(receive_frame, length, &frame);

	if (decode_result != IVC_DECODE_OK) {
		if (ivc_decode_rejection_context(receive_frame, length, decode_result,
					 &rejection)) {
			reject_request(server, transport, peer, &rejection.request,
				       rejection.response_error,
				       ivc_decode_result_name(decode_result));
		} else {
			server->protocol_errors++;
			log_message(transport, "IVC-RTOS-DROP rtos=%s reason=%s length=%u",
				    config->rtos_name,
				    ivc_decode_result_name(decode_result),
				    (unsigned int)length);
		}
		return;
	}
	if (frame.header.message_type == IVC_MESSAGE_VISION_DECISION) {
		if (!ivc_decode_vision_decision(frame.payload,
					frame.header.payload_length, &decision)) {
			reject_request(server, transport, peer, &frame.header,
				       IVC_ERROR_INVALID_VISION_DECISION,
				       "invalid-vision-decision-payload");
			return;
		}
		process_vision_decision(config, transport, server, peer, &frame,
					&decision);
		return;
	}
	if (frame.header.message_type != IVC_MESSAGE_CONTROL) {
		reject_request(server, transport, peer, &frame.header,
			       IVC_ERROR_INVALID_CONTROL, "unexpected-message-type");
		return;
	}
	if (!ivc_decode_control(frame.payload, frame.header.payload_length,
				&command)) {
		reject_request(server, transport, peer, &frame.header,
			       IVC_ERROR_INVALID_CONTROL, "invalid-control-payload");
		return;
	}
	process_control(config, transport, server, peer, &frame, &command);
}

static void check_safe_timeout(const struct ivc_rtos_server_config *config,
			       const struct ivc_rtos_transport *transport,
			       struct server_state *server)
{
	struct ivc_actuator_status vision_status;
	enum ivc_timeout_result result = ivc_endpoint_check_timeout(
		&server->endpoint, transport->now_us(transport->context));

	if (result == IVC_TIMEOUT_ENTERED_SAFE_STATE) {
		server->safe_fallbacks++;
		log_message(transport,
			    "IVC-RTOS-SAFE-FALLBACK rtos=%s reason=controller-timeout "
			    "actuator_permille=%u last_sequence=%u session=%u "
			    "safe_fallbacks=%llu",
			    config->rtos_name,
			    (unsigned int)server->endpoint.actuator_permille,
			    server->endpoint.last_sequence,
			    server->receive_window.session_id,
			    (unsigned long long)server->safe_fallbacks);
	} else if (result == IVC_TIMEOUT_CLOCK_MOVED_BACKWARD) {
		server->protocol_errors++;
		log_message(transport,
			    "IVC-RTOS-ERROR rtos=%s seq=%u code=%u "
			    "reason=clock-moved-backward",
			    config->rtos_name, server->endpoint.last_sequence,
			    (unsigned int)IVC_ERROR_INTERNAL);
	}
	if (ivc_vision_endpoint_check_timeout(
		    &server->vision_endpoint, transport->now_us(transport->context),
		    &vision_status)) {
		server->safe_fallbacks++;
		server->last_actuator_status = vision_status;
		if (server->has_last_vision_response) {
			(void)send_actuator_status(
				server, transport, &server->last_vision_peer,
				&server->last_vision_request, &vision_status);
		}
		log_message(transport,
			    "IVC-RTOS-VISION-SAFE-FALLBACK rtos=%s frame=%u "
			    "actual=%s reason=controller-timeout",
			    config->rtos_name, vision_status.frame_id,
			    vision_action_name(vision_status.actual_action));
	}
}

static bool valid_configuration(const struct ivc_rtos_server_config *config,
				const struct ivc_rtos_transport *transport)
{
	uint32_t expected_messages;

	if (config == NULL) {
		return false;
	}
	expected_messages = config->expected_vision_decisions != 0U ?
		config->expected_vision_decisions : config->expected_commands;
	return config != NULL && transport != NULL && config->rtos_name != NULL &&
	       config->local_address != NULL && config->local_port != 0U &&
	       transport->now_us != NULL && transport->receive != NULL &&
	       transport->send != NULL && transport->log_line != NULL &&
	       (!config->stop_after_result ||
		(transport->sleep_ms != NULL && transport->power_off != NULL)) &&
	       !(config->expected_commands != 0U &&
		 config->expected_vision_decisions != 0U) &&
	       (config->drop_ack_every == 0U ||
		(expected_messages != 0U &&
		 config->drop_ack_every <= expected_messages));
}

int ivc_rtos_server_run(const struct ivc_rtos_server_config *config,
			const struct ivc_rtos_transport *transport)
{
	struct server_state server;

	if (!valid_configuration(config, transport)) {
		return -1;
	}
	if (!ivc_protocol_self_test()) {
		log_message(transport,
			    "IVC-RTOS-SELFTEST FAIL rtos=%s vector=rust-wire-v1",
			    config->rtos_name);
		return -1;
	}
	log_message(transport, "IVC-RTOS-SELFTEST PASS rtos=%s vector=rust-wire-v1",
		    config->rtos_name);
	memset(&server, 0, sizeof(server));
	ivc_receive_window_init(&server.receive_window);
	ivc_endpoint_init(&server.endpoint);
	ivc_vision_endpoint_init(&server.vision_endpoint, IVC_COMMAND_TIMEOUT_US);
	ivc_thermal_plant_init(&server.plant);
	ivc_ack_loss_policy_init(&server.ack_loss, config->drop_ack_every);
	log_message(transport,
		    "IVC-RTOS-READY rtos=%s bind=%s:%u window_bits=%u "
		    "ack_loss_drop_every=%u expected_commands=%u "
		    "expected_vision_decisions=%u expected_protocol_errors=%u",
		    config->rtos_name, config->local_address,
		    (unsigned int)config->local_port, IVC_RECEIVE_WINDOW_BITS,
		    config->drop_ack_every, config->expected_commands,
		    config->expected_vision_decisions,
		    config->expected_protocol_errors);

	for (;;) {
		struct ivc_rtos_peer peer = {0};
		int received = transport->receive(
			transport->context, receive_frame, sizeof(receive_frame), &peer,
			IVC_RTOS_SOCKET_POLL_MS);

		if (received > 0) {
			process_datagram(config, transport, &server, &peer,
					 (size_t)received);
		} else if (received < 0) {
			log_message(transport, "IVC-RTOS-RX-ERROR rtos=%s",
				    config->rtos_name);
		}
		check_safe_timeout(config, transport, &server);
		if (report_result_if_complete(config, transport, &server) &&
		    config->stop_after_result) {
			report_poweroff_evidence(config, transport, &server);
			transport->power_off(transport->context);
			return 0;
		}
	}
}

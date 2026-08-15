/* SPDX-License-Identifier: Apache-2.0 */

#include "ivc_rtos_server.h"

#include "endpoint.h"
#include "protocol.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define IVC_LOG_LINE_CAPACITY 320U

struct server_state {
	struct ivc_receive_window receive_window;
	struct ivc_endpoint endpoint;
	struct ivc_thermal_plant plant;
	struct ivc_ack_loss_policy ack_loss;
	uint32_t applied_commands;
	uint64_t protocol_errors;
	uint64_t status_sent;
	uint64_t acknowledgements_sent;
	uint64_t errors_sent;
	uint64_t safe_fallbacks;
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
	const char *profile;

	if (server->result_reported || config->expected_commands == 0U ||
	    server->receive_window.metrics.accepted != config->expected_commands ||
	    server->protocol_errors != config->expected_protocol_errors ||
	    server->errors_sent != config->expected_protocol_errors) {
		return false;
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
	server->result_reported = true;
	return true;
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

static void process_datagram(const struct ivc_rtos_server_config *config,
			     const struct ivc_rtos_transport *transport,
			     struct server_state *server,
			     const struct ivc_rtos_peer *peer, size_t length)
{
	struct ivc_decode_rejection rejection;
	struct ivc_frame_view frame;
	struct ivc_control_command command;
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
}

static bool valid_configuration(const struct ivc_rtos_server_config *config,
				const struct ivc_rtos_transport *transport)
{
	return config != NULL && transport != NULL && config->rtos_name != NULL &&
	       config->local_address != NULL && config->local_port != 0U &&
	       transport->now_us != NULL && transport->receive != NULL &&
	       transport->send != NULL && transport->log_line != NULL &&
	       (config->drop_ack_every == 0U ||
		(config->expected_commands != 0U &&
		 config->drop_ack_every <= config->expected_commands));
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
	ivc_thermal_plant_init(&server.plant);
	ivc_ack_loss_policy_init(&server.ack_loss, config->drop_ack_every);
	log_message(transport,
		    "IVC-RTOS-READY rtos=%s bind=%s:%u window_bits=%u "
		    "ack_loss_drop_every=%u expected_commands=%u "
		    "expected_protocol_errors=%u",
		    config->rtos_name, config->local_address,
		    (unsigned int)config->local_port, IVC_RECEIVE_WINDOW_BITS,
		    config->drop_ack_every, config->expected_commands,
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
			return 0;
		}
	}
}

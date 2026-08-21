/* SPDX-License-Identifier: Apache-2.0 */

#ifndef IVC_PROTOCOL_H_
#define IVC_PROTOCOL_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define IVC_PROTOCOL_VERSION 1U
#define IVC_HEADER_LENGTH 32U
#define IVC_MAX_PAYLOAD_LENGTH 1200U
#define IVC_MAX_FRAME_LENGTH (IVC_HEADER_LENGTH + IVC_MAX_PAYLOAD_LENGTH)

#define IVC_CONTROL_PAYLOAD_LENGTH 12U
#define IVC_STATUS_PAYLOAD_LENGTH 20U
#define IVC_ACK_PAYLOAD_LENGTH 12U
#define IVC_ERROR_PAYLOAD_LENGTH 8U
#define IVC_VISION_DECISION_PAYLOAD_LENGTH 44U
#define IVC_ACTUATOR_STATUS_PAYLOAD_LENGTH 32U

#define IVC_FLAG_ACK_REQUIRED UINT16_C(0x0001)
#define IVC_FLAG_RETRANSMISSION UINT16_C(0x0002)
#define IVC_VALID_FLAGS (IVC_FLAG_ACK_REQUIRED | IVC_FLAG_RETRANSMISSION)

#define IVC_MIN_TEMPERATURE_MILLI_C (-40000)
#define IVC_MAX_TEMPERATURE_MILLI_C 150000
#define IVC_MAX_ACTUATOR_PERMILLE 1000U
#define IVC_VISION_PAYLOAD_VERSION 1U
#define IVC_MAX_VISION_TTL_US UINT32_C(5000000)
#define IVC_NO_DETECTION_CLASS_ID UINT16_MAX

enum ivc_message_type {
	IVC_MESSAGE_CONTROL = 1,
	IVC_MESSAGE_STATUS = 2,
	IVC_MESSAGE_ERROR = 3,
	IVC_MESSAGE_ACK = 4,
	IVC_MESSAGE_TELEMETRY = 5,
	IVC_MESSAGE_VISION_DECISION = 6,
	IVC_MESSAGE_ACTUATOR_STATUS = 7,
};

enum ivc_error_code {
	IVC_ERROR_NONE = 0,
	IVC_ERROR_MALFORMED_FRAME = 1,
	IVC_ERROR_UNSUPPORTED_VERSION = 2,
	IVC_ERROR_CHECKSUM_MISMATCH = 3,
	IVC_ERROR_SEQUENCE_OUTSIDE_WINDOW = 4,
	IVC_ERROR_INVALID_CONTROL = 5,
	IVC_ERROR_STALE_CONTROL = 6,
	IVC_ERROR_ACTUATOR_RANGE = 7,
	IVC_ERROR_CONTROLLER_TIMEOUT = 8,
	IVC_ERROR_INTERNAL = 9,
	IVC_ERROR_INVALID_VISION_DECISION = 10,
	IVC_ERROR_VISION_DECISION_EXPIRED = 11,
};

enum ivc_vision_action {
	IVC_VISION_HOLD = 0,
	IVC_VISION_SORT_LEFT = 1,
	IVC_VISION_SORT_RIGHT = 2,
	IVC_VISION_EMERGENCY_STOP = 3,
};

enum ivc_actuator_state {
	IVC_ACTUATOR_APPLIED = 1,
	IVC_ACTUATOR_SAFE_FALLBACK = 2,
	IVC_ACTUATOR_REJECTED = 3,
	IVC_ACTUATOR_FAULT = 4,
};

enum ivc_control_operation {
	IVC_CONTROL_SET_ACTUATOR = 1,
	IVC_CONTROL_ENTER_SAFE_STATE = 2,
	IVC_CONTROL_HEARTBEAT = 3,
};

enum ivc_control_mode {
	IVC_MODE_SAFE = 0,
	IVC_MODE_MANUAL_FIXED = 1,
	IVC_MODE_NEURAL = 2,
};

enum ivc_status_state {
	IVC_STATUS_READY = 1,
	IVC_STATUS_APPLIED = 2,
	IVC_STATUS_SAFE_FALLBACK = 3,
	IVC_STATUS_FAULT = 4,
};

enum ivc_decode_result {
	IVC_DECODE_OK = 0,
	IVC_DECODE_TOO_SHORT,
	IVC_DECODE_BAD_MAGIC,
	IVC_DECODE_UNSUPPORTED_VERSION,
	IVC_DECODE_UNKNOWN_MESSAGE_TYPE,
	IVC_DECODE_INVALID_FLAGS,
	IVC_DECODE_PAYLOAD_TOO_LARGE,
	IVC_DECODE_LENGTH_MISMATCH,
	IVC_DECODE_INVALID_ERROR_CODE,
	IVC_DECODE_CHECKSUM_MISMATCH,
};

struct ivc_header {
	enum ivc_message_type message_type;
	uint16_t flags;
	uint32_t session_id;
	uint32_t sequence;
	uint64_t timestamp_us;
	uint16_t payload_length;
	enum ivc_error_code error_code;
};

struct ivc_frame_view {
	struct ivc_header header;
	const uint8_t *payload;
};

struct ivc_decode_rejection {
	struct ivc_header request;
	enum ivc_error_code response_error;
};

struct ivc_control_command {
	enum ivc_control_operation operation;
	enum ivc_control_mode mode;
	uint16_t actuator_permille;
	int32_t setpoint_milli_c;
	uint32_t sample_id;
};

struct ivc_status_report {
	enum ivc_status_state state;
	enum ivc_control_mode active_mode;
	uint16_t actuator_permille;
	int32_t measured_milli_c;
	int32_t setpoint_milli_c;
	uint32_t applied_sequence;
	enum ivc_error_code fault;
};

struct ivc_ack_payload {
	uint32_t acknowledged_sequence;
	uint32_t next_expected_sequence;
	uint32_t received_mask;
};

struct ivc_error_payload {
	enum ivc_message_type offending_message_type;
	uint32_t offending_sequence;
};

struct ivc_bounding_box {
	uint16_t left;
	uint16_t top;
	uint16_t right;
	uint16_t bottom;
};

struct ivc_vision_decision {
	enum ivc_vision_action requested_action;
	enum ivc_vision_action safe_action;
	bool detection_present;
	uint32_t frame_id;
	uint64_t captured_at_us;
	uint64_t inference_finished_at_us;
	uint32_t ttl_us;
	uint16_t class_id;
	uint16_t confidence_q10000;
	uint16_t region_id;
	struct ivc_bounding_box bounding_box;
};

struct ivc_actuator_status {
	enum ivc_actuator_state state;
	enum ivc_vision_action requested_action;
	enum ivc_vision_action actual_action;
	uint32_t frame_id;
	uint32_t applied_sequence;
	uint32_t decision_age_at_send_us;
	uint32_t local_apply_latency_us;
	uint64_t executed_at_us;
	enum ivc_error_code fault;
};

uint32_t ivc_crc32_bytes(const uint8_t *bytes, size_t length);

uint32_t ivc_crc32(const uint8_t *frame, size_t frame_length);

bool ivc_encode_frame(const struct ivc_header *header, const uint8_t *payload,
		      uint8_t *frame, size_t frame_capacity, size_t *frame_length);

enum ivc_decode_result ivc_decode_frame(const uint8_t *frame, size_t frame_length,
					struct ivc_frame_view *view);

bool ivc_decode_rejection_context(const uint8_t *frame, size_t frame_length,
				  enum ivc_decode_result decode_result,
				  struct ivc_decode_rejection *rejection);

const char *ivc_decode_result_name(enum ivc_decode_result result);

bool ivc_encode_control(const struct ivc_control_command *command,
			uint8_t payload[IVC_CONTROL_PAYLOAD_LENGTH]);

bool ivc_decode_control(const uint8_t *payload, size_t payload_length,
			struct ivc_control_command *command);

bool ivc_encode_status(const struct ivc_status_report *status,
		       uint8_t payload[IVC_STATUS_PAYLOAD_LENGTH]);

bool ivc_encode_ack(const struct ivc_ack_payload *ack,
		    uint8_t payload[IVC_ACK_PAYLOAD_LENGTH]);

bool ivc_encode_error_payload(const struct ivc_error_payload *error,
			      uint8_t payload[IVC_ERROR_PAYLOAD_LENGTH]);

bool ivc_encode_vision_decision(
	const struct ivc_vision_decision *decision,
	uint8_t payload[IVC_VISION_DECISION_PAYLOAD_LENGTH]);

bool ivc_decode_vision_decision(const uint8_t *payload, size_t payload_length,
				struct ivc_vision_decision *decision);

bool ivc_encode_actuator_status(
	const struct ivc_actuator_status *status,
	uint8_t payload[IVC_ACTUATOR_STATUS_PAYLOAD_LENGTH]);

bool ivc_decode_actuator_status(const uint8_t *payload, size_t payload_length,
				struct ivc_actuator_status *status);

bool ivc_protocol_self_test(void);

#endif /* IVC_PROTOCOL_H_ */

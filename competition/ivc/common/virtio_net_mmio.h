/* SPDX-License-Identifier: Apache-2.0 */

#ifndef IVC_VIRTIO_NET_MMIO_H_
#define IVC_VIRTIO_NET_MMIO_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define IVC_VIRTIO_NET_QUEUE_SIZE 16U
#define IVC_VIRTIO_NET_HEADER_LENGTH 12U
#define IVC_VIRTIO_NET_MAX_FRAME_LENGTH 1514U
#define IVC_VIRTIO_NET_PACKET_CAPACITY \
	(IVC_VIRTIO_NET_HEADER_LENGTH + IVC_VIRTIO_NET_MAX_FRAME_LENGTH)
#define IVC_VIRTIO_NET_TX_TIMEOUT_US UINT64_C(100000)

enum ivc_virtio_net_error {
	IVC_VIRTIO_NET_OK = 0,
	IVC_VIRTIO_NET_BAD_ARGUMENT,
	IVC_VIRTIO_NET_BAD_MAGIC,
	IVC_VIRTIO_NET_UNSUPPORTED_TRANSPORT,
	IVC_VIRTIO_NET_WRONG_DEVICE,
	IVC_VIRTIO_NET_WRONG_VENDOR,
	IVC_VIRTIO_NET_MISSING_FEATURE,
	IVC_VIRTIO_NET_FEATURE_REJECTED,
	IVC_VIRTIO_NET_QUEUE_TOO_SMALL,
	IVC_VIRTIO_NET_QUEUE_REJECTED,
	IVC_VIRTIO_NET_FRAME_TOO_LARGE,
	IVC_VIRTIO_NET_TX_TIMEOUT,
	IVC_VIRTIO_NET_CORRUPT_USED_RING,
	IVC_VIRTIO_NET_RX_BUFFER_TOO_SMALL,
	IVC_VIRTIO_NET_BAD_RX_HEADER,
};

struct ivc_virtio_net_io {
	uint32_t (*read32)(void *context, uintptr_t address);
	void (*write32)(void *context, uintptr_t address, uint32_t value);
	uint64_t (*now_us)(void *context);
	void (*relax)(void *context);
	void *context;
};

struct ivc_virtq_descriptor {
	uint64_t address;
	uint32_t length;
	uint16_t flags;
	uint16_t next;
};

struct ivc_virtq_available {
	volatile uint16_t flags;
	volatile uint16_t index;
	volatile uint16_t ring[IVC_VIRTIO_NET_QUEUE_SIZE];
	volatile uint16_t used_event;
};

struct ivc_virtq_used_element {
	volatile uint32_t id;
	volatile uint32_t length;
};

struct ivc_virtq_used {
	volatile uint16_t flags;
	volatile uint16_t index;
	struct ivc_virtq_used_element ring[IVC_VIRTIO_NET_QUEUE_SIZE];
	volatile uint16_t available_event;
};

struct ivc_virtio_net_queue {
	struct ivc_virtq_descriptor descriptors[IVC_VIRTIO_NET_QUEUE_SIZE]
		__attribute__((aligned(16)));
	struct ivc_virtq_available available __attribute__((aligned(2)));
	struct ivc_virtq_used used __attribute__((aligned(4)));
};

struct ivc_virtio_net {
	uintptr_t mmio_base;
	struct ivc_virtio_net_io io;
	uint64_t negotiated_features;
	uint8_t mac[6];
	enum ivc_virtio_net_error last_error;
	uint16_t rx_last_used;
	uint16_t tx_last_used;
	struct ivc_virtio_net_queue rx_queue;
	struct ivc_virtio_net_queue tx_queue;
	uint8_t rx_buffers[IVC_VIRTIO_NET_QUEUE_SIZE][IVC_VIRTIO_NET_PACKET_CAPACITY]
		__attribute__((aligned(16)));
	uint8_t tx_buffer[IVC_VIRTIO_NET_PACKET_CAPACITY] __attribute__((aligned(16)));
};

bool ivc_virtio_net_init(struct ivc_virtio_net *device, uintptr_t mmio_base,
			 uint64_t (*now_us)(void *context),
			 void (*relax)(void *context), void *context);

bool ivc_virtio_net_init_with_io(struct ivc_virtio_net *device,
				 uintptr_t mmio_base,
				 const struct ivc_virtio_net_io *io);

bool ivc_virtio_net_transmit(struct ivc_virtio_net *device,
			     const uint8_t *frame, size_t frame_length);

int ivc_virtio_net_receive(struct ivc_virtio_net *device, uint8_t *frame,
			   size_t frame_capacity);

void ivc_virtio_net_ack_interrupt(struct ivc_virtio_net *device);

const uint8_t *ivc_virtio_net_mac(const struct ivc_virtio_net *device);

const char *ivc_virtio_net_error_name(enum ivc_virtio_net_error error);

#endif /* IVC_VIRTIO_NET_MMIO_H_ */

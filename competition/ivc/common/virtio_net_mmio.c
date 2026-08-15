/* SPDX-License-Identifier: Apache-2.0 */

#include "virtio_net_mmio.h"

#include <string.h>

#define VIRTIO_MMIO_MAGIC_VALUE 0x000U
#define VIRTIO_MMIO_VERSION 0x004U
#define VIRTIO_MMIO_DEVICE_ID 0x008U
#define VIRTIO_MMIO_VENDOR_ID 0x00cU
#define VIRTIO_MMIO_DEVICE_FEATURES 0x010U
#define VIRTIO_MMIO_DEVICE_FEATURES_SEL 0x014U
#define VIRTIO_MMIO_DRIVER_FEATURES 0x020U
#define VIRTIO_MMIO_DRIVER_FEATURES_SEL 0x024U
#define VIRTIO_MMIO_QUEUE_SEL 0x030U
#define VIRTIO_MMIO_QUEUE_NUM_MAX 0x034U
#define VIRTIO_MMIO_QUEUE_NUM 0x038U
#define VIRTIO_MMIO_QUEUE_READY 0x044U
#define VIRTIO_MMIO_QUEUE_NOTIFY 0x050U
#define VIRTIO_MMIO_INTERRUPT_STATUS 0x060U
#define VIRTIO_MMIO_INTERRUPT_ACK 0x064U
#define VIRTIO_MMIO_STATUS 0x070U
#define VIRTIO_MMIO_QUEUE_DESC_LOW 0x080U
#define VIRTIO_MMIO_QUEUE_DESC_HIGH 0x084U
#define VIRTIO_MMIO_QUEUE_DRIVER_LOW 0x090U
#define VIRTIO_MMIO_QUEUE_DRIVER_HIGH 0x094U
#define VIRTIO_MMIO_QUEUE_DEVICE_LOW 0x0a0U
#define VIRTIO_MMIO_QUEUE_DEVICE_HIGH 0x0a4U
#define VIRTIO_MMIO_CONFIG 0x100U

#define VIRTIO_MAGIC UINT32_C(0x74726976)
#define VIRTIO_VERSION_1_0 2U
#define VIRTIO_DEVICE_NET 1U
#define VIRTIO_VENDOR_REDHAT UINT32_C(0x1af4)

#define VIRTIO_STATUS_ACKNOWLEDGE (1U << 0)
#define VIRTIO_STATUS_DRIVER (1U << 1)
#define VIRTIO_STATUS_DRIVER_OK (1U << 2)
#define VIRTIO_STATUS_FEATURES_OK (1U << 3)

#define VIRTIO_NET_F_MAC (UINT64_C(1) << 5)
#define VIRTIO_NET_F_STATUS (UINT64_C(1) << 16)
#define VIRTIO_F_VERSION_1 (UINT64_C(1) << 32)

#define VIRTQ_DESC_F_WRITE (1U << 1)
#define VIRTQ_AVAIL_F_NO_INTERRUPT (1U << 0)

#define VIRTIO_NET_RX_QUEUE 0U
#define VIRTIO_NET_TX_QUEUE 1U

static uint32_t direct_read32(void *context, uintptr_t address)
{
	(void)context;
	return *(volatile uint32_t *)address;
}

static void direct_write32(void *context, uintptr_t address, uint32_t value)
{
	(void)context;
	*(volatile uint32_t *)address = value;
}

static void memory_barrier(void)
{
	__atomic_thread_fence(__ATOMIC_SEQ_CST);
}

static uint32_t mmio_read(const struct ivc_virtio_net *device, uintptr_t offset)
{
	return device->io.read32(device->io.context, device->mmio_base + offset);
}

static void mmio_write(const struct ivc_virtio_net *device, uintptr_t offset,
		       uint32_t value)
{
	device->io.write32(device->io.context, device->mmio_base + offset, value);
}

static bool fail(struct ivc_virtio_net *device, enum ivc_virtio_net_error error)
{
	device->last_error = error;
	return false;
}

static void write_address(const struct ivc_virtio_net *device, uintptr_t low_offset,
			  uintptr_t high_offset, const void *address)
{
	uint64_t value = (uint64_t)(uintptr_t)address;

	mmio_write(device, low_offset, (uint32_t)value);
	mmio_write(device, high_offset, (uint32_t)(value >> 32));
}

static uint64_t read_device_features(const struct ivc_virtio_net *device)
{
	uint64_t features;

	mmio_write(device, VIRTIO_MMIO_DEVICE_FEATURES_SEL, 0U);
	features = mmio_read(device, VIRTIO_MMIO_DEVICE_FEATURES);
	mmio_write(device, VIRTIO_MMIO_DEVICE_FEATURES_SEL, 1U);
	features |= (uint64_t)mmio_read(device, VIRTIO_MMIO_DEVICE_FEATURES) << 32;
	return features;
}

static void write_driver_features(const struct ivc_virtio_net *device,
				  uint64_t features)
{
	mmio_write(device, VIRTIO_MMIO_DRIVER_FEATURES_SEL, 0U);
	mmio_write(device, VIRTIO_MMIO_DRIVER_FEATURES, (uint32_t)features);
	mmio_write(device, VIRTIO_MMIO_DRIVER_FEATURES_SEL, 1U);
	mmio_write(device, VIRTIO_MMIO_DRIVER_FEATURES, (uint32_t)(features >> 32));
}

static bool configure_queue(struct ivc_virtio_net *device, uint32_t queue_index,
			    struct ivc_virtio_net_queue *queue)
{
	mmio_write(device, VIRTIO_MMIO_QUEUE_SEL, queue_index);
	if (mmio_read(device, VIRTIO_MMIO_QUEUE_NUM_MAX) < IVC_VIRTIO_NET_QUEUE_SIZE) {
		return fail(device, IVC_VIRTIO_NET_QUEUE_TOO_SMALL);
	}
	mmio_write(device, VIRTIO_MMIO_QUEUE_NUM, IVC_VIRTIO_NET_QUEUE_SIZE);
	write_address(device, VIRTIO_MMIO_QUEUE_DESC_LOW,
		      VIRTIO_MMIO_QUEUE_DESC_HIGH, queue->descriptors);
	write_address(device, VIRTIO_MMIO_QUEUE_DRIVER_LOW,
		      VIRTIO_MMIO_QUEUE_DRIVER_HIGH, &queue->available);
	write_address(device, VIRTIO_MMIO_QUEUE_DEVICE_LOW,
		      VIRTIO_MMIO_QUEUE_DEVICE_HIGH, &queue->used);
	memory_barrier();
	mmio_write(device, VIRTIO_MMIO_QUEUE_READY, 1U);
	if (mmio_read(device, VIRTIO_MMIO_QUEUE_READY) != 1U) {
		return fail(device, IVC_VIRTIO_NET_QUEUE_REJECTED);
	}
	return true;
}

static void prepare_receive_queue(struct ivc_virtio_net *device)
{
	struct ivc_virtio_net_queue *queue = &device->rx_queue;

	queue->available.flags = VIRTQ_AVAIL_F_NO_INTERRUPT;
	for (uint16_t index = 0U; index < IVC_VIRTIO_NET_QUEUE_SIZE; ++index) {
		queue->descriptors[index] = (struct ivc_virtq_descriptor){
			.address = (uint64_t)(uintptr_t)device->rx_buffers[index],
			.length = IVC_VIRTIO_NET_PACKET_CAPACITY,
			.flags = VIRTQ_DESC_F_WRITE,
		};
		queue->available.ring[index] = index;
	}
	memory_barrier();
	queue->available.index = IVC_VIRTIO_NET_QUEUE_SIZE;
}

static void prepare_transmit_queue(struct ivc_virtio_net *device)
{
	device->tx_queue.available.flags = VIRTQ_AVAIL_F_NO_INTERRUPT;
	device->tx_queue.descriptors[0] = (struct ivc_virtq_descriptor){
		.address = (uint64_t)(uintptr_t)device->tx_buffer,
	};
}

static void read_mac(struct ivc_virtio_net *device)
{
	uint32_t low = mmio_read(device, VIRTIO_MMIO_CONFIG);
	uint32_t high = mmio_read(device, VIRTIO_MMIO_CONFIG + sizeof(uint32_t));

	for (size_t index = 0U; index < 4U; ++index) {
		device->mac[index] = (uint8_t)(low >> (index * 8U));
	}
	device->mac[4] = (uint8_t)high;
	device->mac[5] = (uint8_t)(high >> 8);
}

bool ivc_virtio_net_init(struct ivc_virtio_net *device, uintptr_t mmio_base,
			 uint64_t (*now_us)(void *context),
			 void (*relax)(void *context), void *context)
{
	const struct ivc_virtio_net_io io = {
		.read32 = direct_read32,
		.write32 = direct_write32,
		.now_us = now_us,
		.relax = relax,
		.context = context,
	};

	return ivc_virtio_net_init_with_io(device, mmio_base, &io);
}

bool ivc_virtio_net_init_with_io(struct ivc_virtio_net *device,
				 uintptr_t mmio_base,
				 const struct ivc_virtio_net_io *io)
{
	uint32_t status;
	uint64_t device_features;
	uint64_t driver_features;

	if (device == NULL || io == NULL || io->read32 == NULL ||
	    io->write32 == NULL || io->now_us == NULL) {
		return false;
	}
	memset(device, 0, sizeof(*device));
	device->mmio_base = mmio_base;
	device->io = *io;
	if (mmio_read(device, VIRTIO_MMIO_MAGIC_VALUE) != VIRTIO_MAGIC) {
		return fail(device, IVC_VIRTIO_NET_BAD_MAGIC);
	}
	if (mmio_read(device, VIRTIO_MMIO_VERSION) != VIRTIO_VERSION_1_0) {
		return fail(device, IVC_VIRTIO_NET_UNSUPPORTED_TRANSPORT);
	}
	if (mmio_read(device, VIRTIO_MMIO_DEVICE_ID) != VIRTIO_DEVICE_NET) {
		return fail(device, IVC_VIRTIO_NET_WRONG_DEVICE);
	}
	if (mmio_read(device, VIRTIO_MMIO_VENDOR_ID) != VIRTIO_VENDOR_REDHAT) {
		return fail(device, IVC_VIRTIO_NET_WRONG_VENDOR);
	}

	mmio_write(device, VIRTIO_MMIO_STATUS, 0U);
	status = VIRTIO_STATUS_ACKNOWLEDGE;
	mmio_write(device, VIRTIO_MMIO_STATUS, status);
	status |= VIRTIO_STATUS_DRIVER;
	mmio_write(device, VIRTIO_MMIO_STATUS, status);

	device_features = read_device_features(device);
	if ((device_features & (VIRTIO_F_VERSION_1 | VIRTIO_NET_F_MAC)) !=
	    (VIRTIO_F_VERSION_1 | VIRTIO_NET_F_MAC)) {
		return fail(device, IVC_VIRTIO_NET_MISSING_FEATURE);
	}
	driver_features = VIRTIO_F_VERSION_1 | VIRTIO_NET_F_MAC;
	driver_features |= device_features & VIRTIO_NET_F_STATUS;
	write_driver_features(device, driver_features);
	status |= VIRTIO_STATUS_FEATURES_OK;
	mmio_write(device, VIRTIO_MMIO_STATUS, status);
	if ((mmio_read(device, VIRTIO_MMIO_STATUS) & VIRTIO_STATUS_FEATURES_OK) == 0U) {
		return fail(device, IVC_VIRTIO_NET_FEATURE_REJECTED);
	}
	device->negotiated_features = driver_features;

	prepare_receive_queue(device);
	prepare_transmit_queue(device);
	if (!configure_queue(device, VIRTIO_NET_RX_QUEUE, &device->rx_queue) ||
	    !configure_queue(device, VIRTIO_NET_TX_QUEUE, &device->tx_queue)) {
		return false;
	}
	read_mac(device);
	status |= VIRTIO_STATUS_DRIVER_OK;
	mmio_write(device, VIRTIO_MMIO_STATUS, status);
	device->last_error = IVC_VIRTIO_NET_OK;
	mmio_write(device, VIRTIO_MMIO_QUEUE_NOTIFY, VIRTIO_NET_RX_QUEUE);
	return true;
}

bool ivc_virtio_net_transmit(struct ivc_virtio_net *device,
			     const uint8_t *frame, size_t frame_length)
{
	struct ivc_virtio_net_queue *queue;
	uint16_t available_index;
	uint16_t used_index;
	uint64_t started_us;

	if (device == NULL || frame == NULL) {
		return false;
	}
	if (frame_length == 0U || frame_length > IVC_VIRTIO_NET_MAX_FRAME_LENGTH) {
		return fail(device, IVC_VIRTIO_NET_FRAME_TOO_LARGE);
	}
	queue = &device->tx_queue;
	used_index = __atomic_load_n(&queue->used.index, __ATOMIC_ACQUIRE);
	if (used_index != device->tx_last_used) {
		return fail(device, IVC_VIRTIO_NET_CORRUPT_USED_RING);
	}
	memset(device->tx_buffer, 0, IVC_VIRTIO_NET_HEADER_LENGTH);
	memcpy(device->tx_buffer + IVC_VIRTIO_NET_HEADER_LENGTH, frame, frame_length);
	queue->descriptors[0].length =
		(uint32_t)(IVC_VIRTIO_NET_HEADER_LENGTH + frame_length);
	available_index = __atomic_load_n(&queue->available.index, __ATOMIC_RELAXED);
	queue->available.ring[available_index % IVC_VIRTIO_NET_QUEUE_SIZE] = 0U;
	memory_barrier();
	__atomic_store_n(&queue->available.index, (uint16_t)(available_index + 1U),
			 __ATOMIC_RELEASE);
	mmio_write(device, VIRTIO_MMIO_QUEUE_NOTIFY, VIRTIO_NET_TX_QUEUE);

	started_us = device->io.now_us(device->io.context);
	for (;;) {
		used_index = __atomic_load_n(&queue->used.index, __ATOMIC_ACQUIRE);
		if (used_index != device->tx_last_used) {
			const struct ivc_virtq_used_element *used =
				&queue->used.ring[device->tx_last_used %
						 IVC_VIRTIO_NET_QUEUE_SIZE];
			uint32_t expected_length =
				(uint32_t)(IVC_VIRTIO_NET_HEADER_LENGTH + frame_length);

			if (used_index != (uint16_t)(device->tx_last_used + 1U) ||
			    used->id != 0U || used->length != expected_length) {
				return fail(device, IVC_VIRTIO_NET_CORRUPT_USED_RING);
			}
			device->tx_last_used = used_index;
			device->last_error = IVC_VIRTIO_NET_OK;
			return true;
		}
		if (device->io.now_us(device->io.context) - started_us >
		    IVC_VIRTIO_NET_TX_TIMEOUT_US) {
			return fail(device, IVC_VIRTIO_NET_TX_TIMEOUT);
		}
		if (device->io.relax != NULL) {
			device->io.relax(device->io.context);
		}
	}
}

int ivc_virtio_net_receive(struct ivc_virtio_net *device, uint8_t *frame,
			   size_t frame_capacity)
{
	struct ivc_virtio_net_queue *queue;
	const struct ivc_virtq_used_element *used;
	uint16_t used_index;
	uint16_t descriptor;
	uint32_t packet_length;
	size_t frame_length;
	uint16_t available_index;

	if (device == NULL || frame == NULL) {
		return -1;
	}
	queue = &device->rx_queue;
	used_index = __atomic_load_n(&queue->used.index, __ATOMIC_ACQUIRE);
	if (used_index == device->rx_last_used) {
		return 0;
	}
	if ((uint16_t)(used_index - device->rx_last_used) > IVC_VIRTIO_NET_QUEUE_SIZE) {
		fail(device, IVC_VIRTIO_NET_CORRUPT_USED_RING);
		return -1;
	}
	used = &queue->used.ring[device->rx_last_used % IVC_VIRTIO_NET_QUEUE_SIZE];
	descriptor = (uint16_t)used->id;
	packet_length = used->length;
	if (descriptor >= IVC_VIRTIO_NET_QUEUE_SIZE ||
	    packet_length < IVC_VIRTIO_NET_HEADER_LENGTH ||
	    packet_length > IVC_VIRTIO_NET_PACKET_CAPACITY) {
		fail(device, IVC_VIRTIO_NET_CORRUPT_USED_RING);
		return -1;
	}
	frame_length = packet_length - IVC_VIRTIO_NET_HEADER_LENGTH;
	if (frame_length > frame_capacity) {
		fail(device, IVC_VIRTIO_NET_RX_BUFFER_TOO_SMALL);
		return -1;
	}
	if (device->rx_buffers[descriptor][0] != 0U ||
	    device->rx_buffers[descriptor][1] != 0U ||
	    (device->rx_buffers[descriptor][10] != 0U &&
	     device->rx_buffers[descriptor][10] != 1U) ||
	    device->rx_buffers[descriptor][11] != 0U) {
		fail(device, IVC_VIRTIO_NET_BAD_RX_HEADER);
		return -1;
	}
	memcpy(frame, device->rx_buffers[descriptor] + IVC_VIRTIO_NET_HEADER_LENGTH,
	       frame_length);
	device->rx_last_used++;
	available_index = __atomic_load_n(&queue->available.index, __ATOMIC_RELAXED);
	queue->available.ring[available_index % IVC_VIRTIO_NET_QUEUE_SIZE] = descriptor;
	memory_barrier();
	__atomic_store_n(&queue->available.index, (uint16_t)(available_index + 1U),
			 __ATOMIC_RELEASE);
	device->last_error = IVC_VIRTIO_NET_OK;
	return (int)frame_length;
}

void ivc_virtio_net_ack_interrupt(struct ivc_virtio_net *device)
{
	uint32_t status;

	if (device == NULL) {
		return;
	}
	status = mmio_read(device, VIRTIO_MMIO_INTERRUPT_STATUS);
	if (status != 0U) {
		mmio_write(device, VIRTIO_MMIO_INTERRUPT_ACK, status);
	}
}

const uint8_t *ivc_virtio_net_mac(const struct ivc_virtio_net *device)
{
	return device == NULL ? NULL : device->mac;
}

const char *ivc_virtio_net_error_name(enum ivc_virtio_net_error error)
{
	switch (error) {
	case IVC_VIRTIO_NET_OK:
		return "ok";
	case IVC_VIRTIO_NET_BAD_ARGUMENT:
		return "bad-argument";
	case IVC_VIRTIO_NET_BAD_MAGIC:
		return "bad-magic";
	case IVC_VIRTIO_NET_UNSUPPORTED_TRANSPORT:
		return "unsupported-transport";
	case IVC_VIRTIO_NET_WRONG_DEVICE:
		return "wrong-device";
	case IVC_VIRTIO_NET_WRONG_VENDOR:
		return "wrong-vendor";
	case IVC_VIRTIO_NET_MISSING_FEATURE:
		return "missing-feature";
	case IVC_VIRTIO_NET_FEATURE_REJECTED:
		return "feature-rejected";
	case IVC_VIRTIO_NET_QUEUE_TOO_SMALL:
		return "queue-too-small";
	case IVC_VIRTIO_NET_QUEUE_REJECTED:
		return "queue-rejected";
	case IVC_VIRTIO_NET_FRAME_TOO_LARGE:
		return "frame-too-large";
	case IVC_VIRTIO_NET_TX_TIMEOUT:
		return "tx-timeout";
	case IVC_VIRTIO_NET_CORRUPT_USED_RING:
		return "corrupt-used-ring";
	case IVC_VIRTIO_NET_RX_BUFFER_TOO_SMALL:
		return "rx-buffer-too-small";
	case IVC_VIRTIO_NET_BAD_RX_HEADER:
		return "bad-rx-header";
	default:
		return "unknown";
	}
}

/* SPDX-License-Identifier: Apache-2.0 */

#include "virtio_net_mmio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TEST_MMIO_BASE ((uintptr_t)UINT32_C(0x0b000000))
#define REG_MAGIC 0x000U
#define REG_VERSION 0x004U
#define REG_DEVICE_ID 0x008U
#define REG_VENDOR_ID 0x00cU
#define REG_DEVICE_FEATURES 0x010U
#define REG_DEVICE_FEATURES_SEL 0x014U
#define REG_DRIVER_FEATURES 0x020U
#define REG_DRIVER_FEATURES_SEL 0x024U
#define REG_QUEUE_SEL 0x030U
#define REG_QUEUE_NUM_MAX 0x034U
#define REG_QUEUE_NUM 0x038U
#define REG_QUEUE_READY 0x044U
#define REG_QUEUE_NOTIFY 0x050U
#define REG_INTERRUPT_STATUS 0x060U
#define REG_INTERRUPT_ACK 0x064U
#define REG_STATUS 0x070U
#define REG_QUEUE_DESC_LOW 0x080U
#define REG_QUEUE_DESC_HIGH 0x084U
#define REG_QUEUE_DRIVER_LOW 0x090U
#define REG_QUEUE_DRIVER_HIGH 0x094U
#define REG_QUEUE_DEVICE_LOW 0x0a0U
#define REG_QUEUE_DEVICE_HIGH 0x0a4U
#define REG_CONFIG 0x100U

#define FEATURE_MAC (UINT64_C(1) << 5)
#define FEATURE_STATUS (UINT64_C(1) << 16)
#define FEATURE_VERSION_1 (UINT64_C(1) << 32)

struct fake_queue {
	uint32_t size;
	uint32_t ready;
	uint64_t descriptors;
	uint64_t available;
	uint64_t used;
};

struct fake_device {
	uint32_t magic;
	uint32_t version;
	uint32_t device_id;
	uint32_t vendor_id;
	uint64_t device_features;
	uint64_t driver_features;
	uint32_t device_features_sel;
	uint32_t driver_features_sel;
	uint32_t queue_sel;
	uint32_t status;
	uint32_t interrupt_status;
	uint8_t mac[6];
	uint64_t now_us;
	struct fake_queue queues[2];
};

static void require(bool condition, const char *message)
{
	if (!condition) {
		fprintf(stderr, "virtio-net-mmio-test: %s\n", message);
		exit(EXIT_FAILURE);
	}
}

static uint32_t fake_read32(void *context, uintptr_t address)
{
	struct fake_device *fake = context;
	uintptr_t offset = address - TEST_MMIO_BASE;
	struct fake_queue *queue = &fake->queues[fake->queue_sel];

	switch (offset) {
	case REG_MAGIC:
		return fake->magic;
	case REG_VERSION:
		return fake->version;
	case REG_DEVICE_ID:
		return fake->device_id;
	case REG_VENDOR_ID:
		return fake->vendor_id;
	case REG_DEVICE_FEATURES:
		return (uint32_t)(fake->device_features >>
				       (fake->device_features_sel * 32U));
	case REG_QUEUE_NUM_MAX:
		return IVC_VIRTIO_NET_QUEUE_SIZE;
	case REG_QUEUE_READY:
		return queue->ready;
	case REG_INTERRUPT_STATUS:
		return fake->interrupt_status;
	case REG_STATUS:
		return fake->status;
	case REG_CONFIG:
		return (uint32_t)fake->mac[0] | ((uint32_t)fake->mac[1] << 8) |
		       ((uint32_t)fake->mac[2] << 16) | ((uint32_t)fake->mac[3] << 24);
	case REG_CONFIG + 4U:
		return (uint32_t)fake->mac[4] | ((uint32_t)fake->mac[5] << 8);
	default:
		return 0U;
	}
}

static void set_address_half(uint64_t *address, uint32_t value, bool low)
{
	if (low) {
		*address = (*address & UINT64_C(0xffffffff00000000)) | value;
	} else {
		*address = (*address & UINT64_C(0x00000000ffffffff)) |
			   ((uint64_t)value << 32);
	}
}

static void fake_complete_transmit(struct fake_device *fake)
{
	struct fake_queue *queue = &fake->queues[1];
	struct ivc_virtq_descriptor *descriptors =
		(void *)(uintptr_t)queue->descriptors;
	struct ivc_virtq_available *available = (void *)(uintptr_t)queue->available;
	struct ivc_virtq_used *used = (void *)(uintptr_t)queue->used;
	uint16_t head = available->ring[(uint16_t)(available->index - 1U) %
					IVC_VIRTIO_NET_QUEUE_SIZE];
	uint16_t slot = used->index % IVC_VIRTIO_NET_QUEUE_SIZE;

	used->ring[slot].id = head;
	used->ring[slot].length = descriptors[head].length;
	used->index++;
	fake->interrupt_status = 1U;
}

static void fake_write32(void *context, uintptr_t address, uint32_t value)
{
	struct fake_device *fake = context;
	uintptr_t offset = address - TEST_MMIO_BASE;
	struct fake_queue *queue = &fake->queues[fake->queue_sel];

	switch (offset) {
	case REG_DEVICE_FEATURES_SEL:
		fake->device_features_sel = value;
		break;
	case REG_DRIVER_FEATURES_SEL:
		fake->driver_features_sel = value;
		break;
	case REG_DRIVER_FEATURES: {
		uint64_t mask = UINT64_C(0xffffffff) << (fake->driver_features_sel * 32U);

		fake->driver_features = (fake->driver_features & ~mask) |
					((uint64_t)value <<
					 (fake->driver_features_sel * 32U));
		break;
	}
	case REG_QUEUE_SEL:
		require(value < 2U, "driver selected an out-of-range queue");
		fake->queue_sel = value;
		break;
	case REG_QUEUE_NUM:
		queue->size = value;
		break;
	case REG_QUEUE_READY:
		queue->ready = value;
		break;
	case REG_QUEUE_DESC_LOW:
		set_address_half(&queue->descriptors, value, true);
		break;
	case REG_QUEUE_DESC_HIGH:
		set_address_half(&queue->descriptors, value, false);
		break;
	case REG_QUEUE_DRIVER_LOW:
		set_address_half(&queue->available, value, true);
		break;
	case REG_QUEUE_DRIVER_HIGH:
		set_address_half(&queue->available, value, false);
		break;
	case REG_QUEUE_DEVICE_LOW:
		set_address_half(&queue->used, value, true);
		break;
	case REG_QUEUE_DEVICE_HIGH:
		set_address_half(&queue->used, value, false);
		break;
	case REG_STATUS:
		fake->status = value;
		break;
	case REG_INTERRUPT_ACK:
		fake->interrupt_status &= ~value;
		break;
	case REG_QUEUE_NOTIFY:
		if (value == 1U) {
			fake_complete_transmit(fake);
		}
		break;
	default:
		break;
	}
}

static uint64_t fake_now_us(void *context)
{
	struct fake_device *fake = context;

	return fake->now_us++;
}

static struct fake_device valid_fake(void)
{
	struct fake_device fake = {
		.magic = UINT32_C(0x74726976),
		.version = 2U,
		.device_id = 1U,
		.vendor_id = UINT32_C(0x1af4),
		.device_features = FEATURE_MAC | FEATURE_STATUS | FEATURE_VERSION_1,
		.mac = {0x52, 0x54, 0x00, 0x00, 0x00, 0x02},
	};

	return fake;
}

static bool initialize(struct ivc_virtio_net *device, struct fake_device *fake)
{
	const struct ivc_virtio_net_io io = {
		.read32 = fake_read32,
		.write32 = fake_write32,
		.now_us = fake_now_us,
		.context = fake,
	};

	return ivc_virtio_net_init_with_io(device, TEST_MMIO_BASE, &io);
}

static void inject_receive(struct ivc_virtio_net *device, const uint8_t *frame,
			   size_t frame_length)
{
	struct ivc_virtio_net_queue *queue = &device->rx_queue;
	uint16_t slot = queue->used.index % IVC_VIRTIO_NET_QUEUE_SIZE;
	uint16_t descriptor = queue->available.ring[slot];

	memset(device->rx_buffers[descriptor], 0, IVC_VIRTIO_NET_HEADER_LENGTH);
	device->rx_buffers[descriptor][10] = 1U;
	memcpy(device->rx_buffers[descriptor] + IVC_VIRTIO_NET_HEADER_LENGTH,
	       frame, frame_length);
	queue->used.ring[slot].id = descriptor;
	queue->used.ring[slot].length =
		(uint32_t)(IVC_VIRTIO_NET_HEADER_LENGTH + frame_length);
	queue->used.index++;
}

static void test_happy_path(void)
{
	static struct ivc_virtio_net device;
	struct fake_device fake = valid_fake();
	const uint8_t tx_frame[] = {0x52, 0x54, 0x00, 0x00, 0x00, 0x01,
				    0x52, 0x54, 0x00, 0x00, 0x00, 0x02,
				    0x08, 0x00, 0xaa, 0x55};
	uint8_t received[sizeof(tx_frame)];

	require(initialize(&device, &fake), "valid device did not initialize");
	require(fake.queues[0].ready == 1U && fake.queues[1].ready == 1U,
		"both queues were not made ready");
	require(fake.queues[0].size == IVC_VIRTIO_NET_QUEUE_SIZE &&
		fake.queues[1].size == IVC_VIRTIO_NET_QUEUE_SIZE,
		"queue size was not programmed");
	require(fake.driver_features == fake.device_features,
		"minimal supported features were not negotiated");
	require(memcmp(ivc_virtio_net_mac(&device), fake.mac, sizeof(fake.mac)) == 0,
		"runtime MAC was decoded incorrectly");
	require(ivc_virtio_net_transmit(&device, tx_frame, sizeof(tx_frame)),
		"transmit did not complete");
	require(device.tx_last_used == 1U, "transmit used index did not advance");
	ivc_virtio_net_ack_interrupt(&device);
	require(fake.interrupt_status == 0U, "interrupt was not acknowledged");

	inject_receive(&device, tx_frame, sizeof(tx_frame));
	require(ivc_virtio_net_receive(&device, received, sizeof(received)) ==
		(int)sizeof(tx_frame), "receive did not return the frame length");
	require(memcmp(received, tx_frame, sizeof(tx_frame)) == 0,
		"received frame differs from injected frame");
	require(device.rx_queue.available.index ==
		IVC_VIRTIO_NET_QUEUE_SIZE + 1U,
		"receive descriptor was not recycled");
	require(ivc_virtio_net_receive(&device, received, sizeof(received)) == 0,
		"empty receive queue did not return zero");
}

static void test_probe_failures(void)
{
	static struct ivc_virtio_net device;
	struct fake_device fake = valid_fake();

	fake.magic = 0U;
	require(!initialize(&device, &fake) &&
		device.last_error == IVC_VIRTIO_NET_BAD_MAGIC,
		"bad magic was accepted");
	fake = valid_fake();
	fake.version = 1U;
	require(!initialize(&device, &fake) &&
		device.last_error == IVC_VIRTIO_NET_UNSUPPORTED_TRANSPORT,
		"legacy transport was accepted");
	fake = valid_fake();
	fake.device_features &= ~FEATURE_VERSION_1;
	require(!initialize(&device, &fake) &&
		device.last_error == IVC_VIRTIO_NET_MISSING_FEATURE,
		"device without VERSION_1 was accepted");
}

static void test_bounds(void)
{
	static struct ivc_virtio_net device;
	struct fake_device fake = valid_fake();
	uint8_t frame[IVC_VIRTIO_NET_MAX_FRAME_LENGTH + 1U] = {0};

	require(initialize(&device, &fake), "bounds fixture did not initialize");
	require(!ivc_virtio_net_transmit(&device, frame, sizeof(frame)) &&
		device.last_error == IVC_VIRTIO_NET_FRAME_TOO_LARGE,
		"oversized transmit frame was accepted");
	inject_receive(&device, frame, 16U);
	require(ivc_virtio_net_receive(&device, frame, 8U) < 0 &&
		device.last_error == IVC_VIRTIO_NET_RX_BUFFER_TOO_SMALL,
		"undersized receive destination was accepted");
}

int main(void)
{
	test_happy_path();
	test_probe_failures();
	test_bounds();
	puts("virtio-net-mmio-tests: PASS");
	return EXIT_SUCCESS;
}

/* SPDX-License-Identifier: Apache-2.0 */

#include "network.h"

#include "virtio_net_mmio.h"

#include <ioremap.h>
#include <lwip/netif.h>
#include <lwip/pbuf.h>
#include <netif/ethernetif.h>
#include <rtthread.h>

#include <string.h>

#define IVC_VIRTIO_MMIO_PHYSICAL_BASE UINT32_C(0x0b000000)
#define IVC_VIRTIO_MMIO_SIZE 0x200U
#define IVC_NETWORK_POLL_STACK_SIZE 4096U
#define IVC_NETWORK_POLL_PRIORITY 11U
#define IVC_NETWORK_POLL_TICK 1U

static const uint8_t expected_mac[6] = {0x52, 0x54, 0x00, 0x00, 0x00, 0x02};

struct ivc_rtthread_network {
	struct eth_device ethernet;
	struct ivc_virtio_net virtio;
	struct rt_thread poll_thread;
	uint8_t poll_stack[IVC_NETWORK_POLL_STACK_SIZE];
	uint8_t tx_frame[IVC_VIRTIO_NET_MAX_FRAME_LENGTH];
	uint8_t rx_frame[IVC_VIRTIO_NET_MAX_FRAME_LENGTH];
	bool fault_reported;
};

static struct ivc_rtthread_network network;

uint64_t ivc_rtthread_monotonic_us(void *context)
{
	uint64_t counter;
	uint64_t frequency;

	(void)context;
	__asm__ volatile("mrs %0, cntvct_el0" : "=r"(counter));
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
	if (frequency == 0U) {
		return 0U;
	}
	return (counter / frequency) * UINT64_C(1000000) +
	       ((counter % frequency) * UINT64_C(1000000)) / frequency;
}

static void cpu_relax(void *context)
{
	(void)context;
	__asm__ volatile("yield" ::: "memory");
}

static rt_err_t ethernet_control(rt_device_t device, int command, void *arguments)
{
	struct ivc_rtthread_network *adapter = (struct ivc_rtthread_network *)device;

	if (command != NIOCTL_GADDR || arguments == RT_NULL) {
		return -RT_EINVAL;
	}
	memcpy(arguments, ivc_virtio_net_mac(&adapter->virtio), sizeof(expected_mac));
	return RT_EOK;
}

static rt_err_t ethernet_transmit(rt_device_t device, struct pbuf *packet)
{
	struct ivc_rtthread_network *adapter = (struct ivc_rtthread_network *)device;

	if (packet == RT_NULL || packet->tot_len == 0U ||
	    packet->tot_len > sizeof(adapter->tx_frame) ||
	    pbuf_copy_partial(packet, adapter->tx_frame, packet->tot_len, 0U) !=
		    packet->tot_len ||
	    !ivc_virtio_net_transmit(&adapter->virtio, adapter->tx_frame,
				     packet->tot_len)) {
		rt_kprintf("IVC-RTOS-NET-ERROR rtos=rt-thread stage=tx reason=%s\n",
			   ivc_virtio_net_error_name(adapter->virtio.last_error));
		return -RT_ERROR;
	}
	return RT_EOK;
}

static struct pbuf *ethernet_receive(rt_device_t device)
{
	struct ivc_rtthread_network *adapter = (struct ivc_rtthread_network *)device;
	struct pbuf *packet;
	int length = ivc_virtio_net_receive(&adapter->virtio, adapter->rx_frame,
					    sizeof(adapter->rx_frame));

	if (length == 0) {
		return RT_NULL;
	}
	if (length < 0) {
		if (!adapter->fault_reported) {
			adapter->fault_reported = true;
			rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=rx reason=%s\n",
				   ivc_virtio_net_error_name(adapter->virtio.last_error));
		}
		return RT_NULL;
	}
	packet = pbuf_alloc(PBUF_RAW, (u16_t)length, PBUF_RAM);
	if (packet == RT_NULL || pbuf_take(packet, adapter->rx_frame, (u16_t)length) !=
						ERR_OK) {
		if (packet != RT_NULL) {
			pbuf_free(packet);
		}
		rt_kprintf("IVC-RTOS-NET-ERROR rtos=rt-thread stage=rx-allocate\n");
		return RT_NULL;
	}
	return packet;
}

static const struct rt_device_ops ethernet_ops = {
	RT_NULL,
	RT_NULL,
	RT_NULL,
	RT_NULL,
	RT_NULL,
	ethernet_control,
};

static void network_poll_entry(void *parameter)
{
	struct ivc_rtthread_network *adapter = parameter;

	for (;;) {
		ivc_virtio_net_ack_interrupt(&adapter->virtio);
		if (adapter->virtio.rx_queue.used.index != adapter->virtio.rx_last_used) {
			(void)eth_device_ready(&adapter->ethernet);
		}
		rt_thread_delay(IVC_NETWORK_POLL_TICK);
	}
}

bool ivc_rtthread_network_start(void)
{
	const uint8_t *mac;
	void *mmio_base;
	rt_err_t result;

	memset(&network, 0, sizeof(network));
	mmio_base = rt_ioremap((void *)(uintptr_t)IVC_VIRTIO_MMIO_PHYSICAL_BASE,
			      IVC_VIRTIO_MMIO_SIZE);
	if (mmio_base == RT_NULL) {
		rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=ioremap "
			   "physical=0x0b000000 size=0x200\n");
		return false;
	}
	if (!ivc_virtio_net_init(&network.virtio, (uintptr_t)mmio_base,
				 ivc_rtthread_monotonic_us, cpu_relax, RT_NULL)) {
		rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=virtio-init reason=%s\n",
			   ivc_virtio_net_error_name(network.virtio.last_error));
		return false;
	}
	mac = ivc_virtio_net_mac(&network.virtio);
	if (memcmp(mac, expected_mac, sizeof(expected_mac)) != 0) {
		rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=mac "
			   "actual=%02x:%02x:%02x:%02x:%02x:%02x\n",
			   mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
		return false;
	}
	network.ethernet.parent.ops = &ethernet_ops;
	network.ethernet.eth_tx = ethernet_transmit;
	network.ethernet.eth_rx = ethernet_receive;
	result = eth_device_init_with_flag(
		&network.ethernet, "e0",
		NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP | ETHIF_LINK_PHYUP);
	if (result != RT_EOK) {
		rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=eth-device result=%d\n",
			   result);
		return false;
	}
	result = rt_thread_init(&network.poll_thread, "ivcnet",
				 network_poll_entry, &network, network.poll_stack,
				 sizeof(network.poll_stack), IVC_NETWORK_POLL_PRIORITY,
				 1U);
	if (result != RT_EOK || rt_thread_startup(&network.poll_thread) != RT_EOK) {
		rt_kprintf("IVC-RTOS-FATAL rtos=rt-thread stage=network-poll\n");
		return false;
	}
	rt_kprintf("IVC-RTOS-NET rtos=rt-thread "
		   "mac=52:54:00:00:00:02 ip=10.0.0.2/24 mmio=0x0b000000\n");
	return true;
}

/* SPDX-License-Identifier: Apache-2.0 */

#ifndef FREERTOS_IP_CONFIG_H
#define FREERTOS_IP_CONFIG_H

/* This guest intentionally exposes only the IPv4/ARP/UDP surface needed by IVC. */
#define ipconfigBYTE_ORDER pdFREERTOS_LITTLE_ENDIAN
#define ipconfigIPv4_BACKWARD_COMPATIBLE 1
#define ipconfigUSE_IPv4 1
#define ipconfigUSE_IPv6 0
#define ipconfigUSE_RA 0

#define ipconfigDRIVER_INCLUDED_RX_IP_CHECKSUM 0
#define ipconfigDRIVER_INCLUDED_TX_IP_CHECKSUM 0
#define ipconfigETHERNET_DRIVER_FILTERS_FRAME_TYPES 0
#define ipconfigETHERNET_DRIVER_FILTERS_PACKETS 0
#define ipconfigFILTER_OUT_NON_ETHERNET_II_FRAMES 1
#define ipconfigNETWORK_MTU 1500U
#define ipconfigNUM_NETWORK_BUFFER_DESCRIPTORS 24U
#define ipconfigEVENT_QUEUE_LENGTH 32U
#define ipconfigZERO_COPY_RX_DRIVER 0
#define ipconfigZERO_COPY_TX_DRIVER 0
#define ipconfigUSE_LINKED_RX_MESSAGES 0

#define ipconfigIP_TASK_PRIORITY (configMAX_PRIORITIES - 2U)
#define ipconfigIP_TASK_STACK_SIZE_WORDS 2048U
#define ipconfigUSE_NETWORK_EVENT_HOOK 1
#define ipconfigSUPPORT_NETWORK_DOWN_EVENT 0

#define ipconfigUSE_TCP 0
#define ipconfigUSE_TCP_WIN 0
#define ipconfigUSE_DHCP 0
#define ipconfigUSE_DHCPv6 0
#define ipconfigUSE_DHCP_HOOK 0
#define ipconfigUSE_DNS 0
#define ipconfigUSE_DNS_CACHE 0
#define ipconfigDNS_USE_CALLBACKS 0
#define ipconfigUSE_LLMNR 0
#define ipconfigUSE_NBNS 0
#define ipconfigUSE_MDNS 0

#define ipconfigALLOW_SOCKET_SEND_WITHOUT_BIND 0
#define ipconfigSUPPORT_SELECT_FUNCTION 0
#define ipconfigSELECT_USES_NOTIFY 0
#define ipconfigSOCKET_HAS_USER_SEMAPHORE 0
#define ipconfigSOCKET_HAS_USER_WAKE_CALLBACK 0
#define ipconfigSUPPORT_SIGNALS 0
#define ipconfigUSE_CALLBACKS 0
#define ipconfigUDP_MAX_RX_PACKETS 8U
#define ipconfigUDP_MAX_SEND_BLOCK_TIME_TICKS pdMS_TO_TICKS(100U)
#define ipconfigSOCK_DEFAULT_RECEIVE_BLOCK_TIME pdMS_TO_TICKS(100U)
#define ipconfigSOCK_DEFAULT_SEND_BLOCK_TIME pdMS_TO_TICKS(100U)

#define ipconfigREPLY_TO_INCOMING_PINGS 1
#define ipconfigSUPPORT_OUTGOING_PINGS 0
#define ipconfigHAS_DEBUG_PRINTF 0
#define ipconfigHAS_PRINTF 0

#endif /* FREERTOS_IP_CONFIG_H */

# SPDX-License-Identifier: Apache-2.0

ifndef FREERTOS_PLUS_TCP_DIR
$(error FREERTOS_PLUS_TCP_DIR must point to the pinned FreeRTOS-Plus-TCP source)
endif

ifeq ($(wildcard $(FREERTOS_PLUS_TCP_DIR)/source/FreeRTOS_IP.c),)
$(error invalid FREERTOS_PLUS_TCP_DIR: $(FREERTOS_PLUS_TCP_DIR))
endif

src_c_srcs := main.c network.c protocol.c endpoint.c ivc_rtos_server.c \
	virtio_net_mmio.c

INC_DIRS += $(APP_SRC_DIR)
INC_DIRS += $(FREERTOS_PLUS_TCP_DIR)/source/include
INC_DIRS += $(FREERTOS_PLUS_TCP_DIR)/source/portable/Compiler/GCC
C_SRC += $(wildcard $(FREERTOS_PLUS_TCP_DIR)/source/*.c)
C_SRC += $(FREERTOS_PLUS_TCP_DIR)/source/portable/BufferManagement/BufferAllocation_2.c

ifneq ($(IVC_EXPECTED_COMMANDS),)
CPPFLAGS += -DIVC_EXPECTED_COMMANDS=$(IVC_EXPECTED_COMMANDS)
endif
ifneq ($(IVC_EXPECTED_PROTOCOL_ERRORS),)
CPPFLAGS += -DIVC_EXPECTED_PROTOCOL_ERRORS=$(IVC_EXPECTED_PROTOCOL_ERRORS)
endif
ifneq ($(IVC_DROP_ACK_EVERY),)
CPPFLAGS += -DIVC_DROP_ACK_EVERY=$(IVC_DROP_ACK_EVERY)
endif

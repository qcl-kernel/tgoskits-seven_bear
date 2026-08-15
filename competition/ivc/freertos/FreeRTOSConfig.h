/* SPDX-License-Identifier: Apache-2.0 */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include <stddef.h>
#include <stdint.h>

#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1
#define configUSE_16_BIT_TICKS 0
#define configTICK_RATE_HZ 1000U
#define configMAX_PRIORITIES 8
#define configMINIMAL_STACK_SIZE ((uint16_t)256)
#define configMAX_TASK_NAME_LEN 16
#define configIDLE_SHOULD_YIELD 1
#define configTASK_RETURN_ADDRESS NULL

#define configSUPPORT_STATIC_ALLOCATION 0
#define configSUPPORT_DYNAMIC_ALLOCATION 1
/* Bao startup reaches _stack_base with a signed 1 MiB AArch64 ADR. */
#define configTOTAL_HEAP_SIZE ((size_t)(256U * 1024U))
#define configAPPLICATION_ALLOCATED_HEAP 0

#define configUSE_MUTEXES 1
#define configUSE_RECURSIVE_MUTEXES 0
#define configUSE_COUNTING_SEMAPHORES 1
#define configUSE_QUEUE_SETS 0
#define configUSE_TASK_NOTIFICATIONS 1
#define configTASK_NOTIFICATION_ARRAY_ENTRIES 1
#define configQUEUE_REGISTRY_SIZE 0
#define configUSE_TIMERS 0
#define configUSE_CO_ROUTINES 0
#define configMAX_CO_ROUTINE_PRIORITIES 1

#define configUSE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 0
#define configUSE_MALLOC_FAILED_HOOK 1
#define configCHECK_FOR_STACK_OVERFLOW 2
#define configUSE_DAEMON_TASK_STARTUP_HOOK 0
#define configUSE_APPLICATION_TASK_TAG 0
#define configNUM_THREAD_LOCAL_STORAGE_POINTERS 0
#define configUSE_NEWLIB_REENTRANT 0
#define configUSE_TICKLESS_IDLE 0

#define configUSE_TRACE_FACILITY 0
#define configUSE_STATS_FORMATTING_FUNCTIONS 0
#define configGENERATE_RUN_TIME_STATS 0

#define INCLUDE_vTaskPrioritySet 0
#define INCLUDE_uxTaskPriorityGet 0
#define INCLUDE_vTaskDelete 0
#define INCLUDE_vTaskSuspend 1
#define INCLUDE_vTaskDelayUntil 0
#define INCLUDE_vTaskDelay 1
#define INCLUDE_eTaskGetState 0
#define INCLUDE_xTimerPendFunctionCall 0
#define INCLUDE_pcTaskGetTaskName 0
#define INCLUDE_xTaskGetIdleTaskHandle 0
#define INCLUDE_xTaskAbortDelay 0
#define INCLUDE_xTaskGetCurrentTaskHandle 1

#define configUSE_TASK_FPU_SUPPORT 1
#define configSTACK_DEPTH_TYPE uint32_t
#define configMESSAGE_BUFFER_LENGTH_TYPE size_t
#define portTICK_TYPE_IS_ATOMIC 1

#define configUNIQUE_INTERRUPT_PRIORITIES 16
#define configMAX_API_CALL_INTERRUPT_PRIORITY 9
#define configINTERRUPT_CONTROLLER_CPU_INTERFACE_OFFSET 0x10000

void FreeRTOS_SetupTickInterrupt(void);
#define configSETUP_TICK_INTERRUPT() FreeRTOS_SetupTickInterrupt()
void FreeRTOS_ClearTickInterrupt(void);
#define configCLEAR_TICK_INTERRUPT() FreeRTOS_ClearTickInterrupt()

void vApplicationAssert(const char *file, uint32_t line);
#define configASSERT(expression)                                      \
	do {                                                           \
		if ((expression) == 0) {                                 \
			vApplicationAssert(__FILE__, (uint32_t)__LINE__);   \
		}                                                      \
	} while (0)

#endif /* FREERTOS_CONFIG_H */

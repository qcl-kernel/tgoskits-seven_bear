/* SPDX-License-Identifier: Apache-2.0 */

#include <FreeRTOS.h>
#include <task.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include <sysregs.h>

#include "latency_stats.h"
#include "miss_accounting.h"

#define PERIOD_US 1000U
#define SAMPLE_COUNT 10000U
#define WARMUP_COUNT 100U
#define TOTAL_EXPIRATIONS (WARMUP_COUNT + SAMPLE_COUNT)
#define BENCHMARK_PRIORITY (configMAX_PRIORITIES - 1U)
#define STRESS_PRIORITY (tskIDLE_PRIORITY + 1U)
#define BENCHMARK_STACK_DEPTH 4096U
#define STRESS_STACK_DEPTH 1024U
#define STRESS_OPERATIONS_PER_BLOCK 1024U
#define STARTUP_DELAY_MS 10U

#if configTICK_RATE_HZ != 1000
#error "the FreeRTOS tick must equal the benchmark period"
#endif

#if configNUMBER_OF_CORES != 1
#error "the native FreeRTOS baseline must be single-core"
#endif

#if defined(RT_BASELINE_STRESS)
#define WORKLOAD_NAME "cpu-stress"
#else
#define WORKLOAD_NAME "idle"
#endif

struct load_snapshot {
	uint64_t idle_cycles;
	uint64_t benchmark_cycles;
	uint64_t stress_cycles;
	uint64_t cycle;
	uint64_t stress_blocks;
	uint64_t stress_checksum;
};

static TaskHandle_t benchmark_task;
#if defined(RT_BASELINE_STRESS)
static TaskHandle_t stress_task;
#endif
static uint64_t deadline_cycles[TOTAL_EXPIRATIONS];
static uint64_t callback_cycles[TOTAL_EXPIRATIONS];
static uint64_t wake_lateness_ns[SAMPLE_COUNT];
static uint64_t dispatch_latency_ns[SAMPLE_COUNT];
static uint64_t sort_scratch[SAMPLE_COUNT];
static uint64_t counter_frequency_hz;
static uint64_t counter_step;
static volatile uint64_t stress_blocks;
static volatile uint64_t stress_checksum;
static volatile uint32_t expiry_count;
static volatile bool sampling_active;
static volatile bool tick_contract_failed;

static void benchmark_entry(void *parameter);
#if defined(RT_BASELINE_STRESS)
static void stress_entry(void *parameter);
#endif
static bool begin_sampling(void);
static bool capture_load_snapshot(struct load_snapshot *snapshot);
static bool emit_latency_result(const char *metric, const uint64_t *samples,
				uint64_t actual_duration_us);
static bool emit_load_result(const struct load_snapshot *start,
			     const struct load_snapshot *end);
static uint64_t delta_u64(uint64_t end, uint64_t start);
static void benchmark_fatal(const char *stage, const char *reason)
	__attribute__((noreturn));
static void power_off(void) __attribute__((noreturn));

uint64_t rt_baseline_counter(void)
{
	return sysreg_cntvct_el0_read();
}

int main(void)
{
#if defined(RT_BASELINE_STRESS)
	if (xTaskCreate(stress_entry, "rtstress", STRESS_STACK_DEPTH, NULL,
			STRESS_PRIORITY, &stress_task) != pdPASS) {
		printf("RTOS_BASELINE_FATAL schema=1 stage=init reason=stress-task\n");
		power_off();
	}
#endif
	if (xTaskCreate(benchmark_entry, "rtperiod", BENCHMARK_STACK_DEPTH, NULL,
			BENCHMARK_PRIORITY, &benchmark_task) != pdPASS) {
		printf("RTOS_BASELINE_FATAL schema=1 stage=init reason=benchmark-task\n");
		power_off();
	}
	vTaskStartScheduler();
	printf("RTOS_BASELINE_FATAL schema=1 stage=scheduler reason=returned\n");
	power_off();
}

static void benchmark_entry(void *parameter)
{
	struct load_snapshot load_start;
	struct load_snapshot load_end;
	uint64_t last_observed_cycle = 0U;
	uint64_t duration_ns;
	uint32_t processed_expirations = 0U;
	uint32_t warmup_misses = 0U;
	uint32_t measured_misses = 0U;

	(void)parameter;
	counter_frequency_hz = sysreg_cntfrq_el0_read();
	if (counter_frequency_hz == 0U ||
	    counter_frequency_hz % configTICK_RATE_HZ != 0U) {
		benchmark_fatal("clock", "non-integral-tick");
	}
	counter_step = counter_frequency_hz / configTICK_RATE_HZ;
	printf(
		"RTOS_BASELINE_CONFIG schema=1 os=freertos kernel_version=V11.1.0+ "
		"kernel_commit=f1043c49d59944353291654c175852bd17b34f99 "
		"board=qemu_aarch64_virt cpu_model=cortex-a53 cpu_count=1 "
		"qemu_icount=false workload=%s period_us=%u samples=%u warmup=%u "
		"benchmark_priority=%u stress_priority=%u clock_hz=%llu "
		"ticks_per_sec=%u\n",
		WORKLOAD_NAME, PERIOD_US, SAMPLE_COUNT, WARMUP_COUNT,
		(unsigned int)BENCHMARK_PRIORITY, (unsigned int)STRESS_PRIORITY,
		(unsigned long long)counter_frequency_hz,
		(unsigned int)configTICK_RATE_HZ);

	vTaskDelay(pdMS_TO_TICKS(STARTUP_DELAY_MS));
#if defined(RT_BASELINE_STRESS)
	if (stress_blocks == 0U) {
		benchmark_fatal("workload", "stress-not-running");
	}
	printf(
		"RTOS_BASELINE_WORKLOAD_READY schema=1 kind=cpu-stress verified=true "
		"lower_priority=true benchmark_priority=%u stress_priority=%u "
		"blocks=%llu\n",
		(unsigned int)BENCHMARK_PRIORITY, (unsigned int)STRESS_PRIORITY,
		(unsigned long long)stress_blocks);
#else
	printf(
		"RTOS_BASELINE_WORKLOAD_READY schema=1 kind=idle verified=true "
		"lower_priority=false benchmark_priority=%u stress_priority=%u blocks=0\n",
		(unsigned int)BENCHMARK_PRIORITY, (unsigned int)STRESS_PRIORITY);
#endif
	if (!capture_load_snapshot(&load_start)) {
		benchmark_fatal("load-snapshot", "start-failed");
	}
	if (!begin_sampling()) {
		benchmark_fatal("timer-schedule", "unstable-counter-deadline");
	}

	while (processed_expirations < TOTAL_EXPIRATIONS) {
		uint64_t observed_cycle;
		uint32_t available_expirations;

		(void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
		taskENTER_CRITICAL();
		available_expirations = expiry_count;
		observed_cycle = rt_baseline_counter();
		taskEXIT_CRITICAL();
		if (tick_contract_failed ||
		    available_expirations > TOTAL_EXPIRATIONS) {
			benchmark_fatal("timestamp", "invalid-tick-observation");
		}
		if (available_expirations <= processed_expirations) {
			continue;
		}

		const struct coalesced_expirations coalesced =
			count_coalesced_expirations(processed_expirations,
						      available_expirations,
						      WARMUP_COUNT);

		warmup_misses += coalesced.warmup;
		measured_misses += coalesced.measured;
		while (processed_expirations < available_expirations) {
			const uint64_t deadline =
				deadline_cycles[processed_expirations];
			const uint64_t callback =
				callback_cycles[processed_expirations];

			if (callback < deadline || observed_cycle < callback) {
				benchmark_fatal("timestamp", "non-monotonic-or-early");
			}
			if (processed_expirations >= WARMUP_COUNT) {
				const uint32_t sample =
					processed_expirations - WARMUP_COUNT;

				if (!rt_baseline_cycles_to_ns(observed_cycle - deadline,
							      counter_frequency_hz,
							      &wake_lateness_ns[sample]) ||
				    !rt_baseline_cycles_to_ns(observed_cycle - callback,
							      counter_frequency_hz,
							      &dispatch_latency_ns[sample])) {
					benchmark_fatal("timestamp", "conversion-overflow");
				}
			}
			++processed_expirations;
		}
		last_observed_cycle = observed_cycle;
	}
	if (!capture_load_snapshot(&load_end)) {
		benchmark_fatal("load-snapshot", "end-failed");
	}
	if (last_observed_cycle < deadline_cycles[WARMUP_COUNT - 1U] ||
	    !rt_baseline_cycles_to_ns(
		    last_observed_cycle - deadline_cycles[WARMUP_COUNT - 1U],
		    counter_frequency_hz, &duration_ns)) {
		benchmark_fatal("duration", "invalid-measurement-window");
	}
	const uint64_t actual_duration_us = duration_ns / 1000U;

	if (!emit_latency_result("periodic_wake_lateness", wake_lateness_ns,
				 actual_duration_us) ||
	    !emit_latency_result("timer_to_task_dispatch", dispatch_latency_ns,
				 actual_duration_us)) {
		benchmark_fatal("statistics", "invalid-summary");
	}
	if (!emit_load_result(&load_start, &load_end)) {
		benchmark_fatal("load", "workload-not-sustained");
	}
	printf(
		"RTOS_BASELINE_COMPLETE schema=1 workload=%s status=pass "
		"timer_misses=%u warmup_timer_misses=%u early_wakes=0\n",
		WORKLOAD_NAME, measured_misses, warmup_misses);
	power_off();
}

void vApplicationTickHook(void)
{
	BaseType_t higher_priority_task_woken = pdFALSE;
	uint32_t expiration;
	uint64_t callback_cycle;

	if (!sampling_active) {
		return;
	}
	expiration = expiry_count;
	if (expiration >= TOTAL_EXPIRATIONS) {
		tick_contract_failed = true;
		sampling_active = false;
		return;
	}
	callback_cycle = rt_baseline_counter();
	callback_cycles[expiration] = callback_cycle;
	if (callback_cycle < deadline_cycles[expiration]) {
		tick_contract_failed = true;
	}
	if (expiration + 1U < TOTAL_EXPIRATIONS) {
		const uint64_t counter_before = rt_baseline_counter();
		const int32_t timer_value =
			(int32_t)(uint32_t)sysreg_cntv_tval_el0_read();

		if (timer_value <= 0 || (uint64_t)(uint32_t)timer_value > counter_step) {
			tick_contract_failed = true;
		} else {
			deadline_cycles[expiration + 1U] =
				counter_before + (uint32_t)timer_value;
		}
	}
	expiry_count = expiration + 1U;
	if (expiry_count == TOTAL_EXPIRATIONS) {
		sampling_active = false;
	}
	vTaskNotifyGiveFromISR(benchmark_task, &higher_priority_task_woken);
	portYIELD_FROM_ISR(higher_priority_task_woken);
}

static bool begin_sampling(void)
{
	for (uint32_t attempt = 0U; attempt < 3U; ++attempt) {
		int32_t timer_value;
		uint64_t counter_before;

		taskENTER_CRITICAL();
		counter_before = rt_baseline_counter();
		timer_value = (int32_t)(uint32_t)sysreg_cntv_tval_el0_read();
		if (timer_value > 0 && (uint64_t)(uint32_t)timer_value <= counter_step) {
			deadline_cycles[0] = counter_before + (uint32_t)timer_value;
			expiry_count = 0U;
			tick_contract_failed = false;
			sampling_active = true;
			taskEXIT_CRITICAL();
			return true;
		}
		taskEXIT_CRITICAL();
		vTaskDelay(1U);
	}
	return false;
}

static bool capture_load_snapshot(struct load_snapshot *snapshot)
{
	if (snapshot == NULL) {
		return false;
	}
	taskENTER_CRITICAL();
	snapshot->idle_cycles = ulTaskGetIdleRunTimeCounter();
	snapshot->benchmark_cycles = ulTaskGetRunTimeCounter(benchmark_task);
#if defined(RT_BASELINE_STRESS)
	snapshot->stress_cycles = ulTaskGetRunTimeCounter(stress_task);
#else
	snapshot->stress_cycles = 0U;
#endif
	snapshot->cycle = rt_baseline_counter();
	snapshot->stress_blocks = stress_blocks;
	snapshot->stress_checksum = stress_checksum;
	taskEXIT_CRITICAL();
	return true;
}

static bool emit_latency_result(const char *metric, const uint64_t *samples,
				uint64_t actual_duration_us)
{
	struct rt_baseline_latency_summary summary;

	if (!rt_baseline_summarize(samples, SAMPLE_COUNT, sort_scratch, &summary)) {
		return false;
	}
	printf(
		"RTOS_BASELINE_RESULT schema=1 workload=%s metric=%s unit=ns count=%u "
		"min_ns=%llu mean_ns=%llu p50_ns=%llu p90_ns=%llu p99_ns=%llu "
		"p999_ns=%llu max_ns=%llu actual_duration_us=%llu "
		"expected_duration_us=%llu\n",
		WORKLOAD_NAME, metric, SAMPLE_COUNT,
		(unsigned long long)summary.minimum_ns,
		(unsigned long long)summary.mean_ns,
		(unsigned long long)summary.p50_ns,
		(unsigned long long)summary.p90_ns,
		(unsigned long long)summary.p99_ns,
		(unsigned long long)summary.p999_ns,
		(unsigned long long)summary.maximum_ns,
		(unsigned long long)actual_duration_us,
		(unsigned long long)SAMPLE_COUNT * PERIOD_US);
	return true;
}

static bool emit_load_result(const struct load_snapshot *start,
			     const struct load_snapshot *end)
{
	const uint64_t total_cycles = delta_u64(end->cycle, start->cycle);
	const uint64_t idle_cycles = delta_u64(end->idle_cycles, start->idle_cycles);
	const uint64_t benchmark_cycles =
		delta_u64(end->benchmark_cycles, start->benchmark_cycles);
	const uint64_t stress_cycles =
		delta_u64(end->stress_cycles, start->stress_cycles);
	const uint64_t stress_block_delta =
		delta_u64(end->stress_blocks, start->stress_blocks);
	uint64_t window_ns;

	if (idle_cycles > total_cycles ||
	    !rt_baseline_cycles_to_ns(total_cycles, counter_frequency_hz,
				      &window_ns)) {
		return false;
	}
	const uint64_t window_us = window_ns / 1000U;
	const uint64_t non_idle_cycles = total_cycles - idle_cycles;
	const uint64_t idle_permille =
		rt_baseline_ratio_permille(idle_cycles, total_cycles);
	const uint64_t non_idle_permille =
		rt_baseline_ratio_permille(non_idle_cycles, total_cycles);
	const uint64_t benchmark_permille =
		rt_baseline_ratio_permille(benchmark_cycles, total_cycles);
	const uint64_t stress_permille =
		rt_baseline_ratio_permille(stress_cycles, total_cycles);
	const uint64_t stress_rate =
		window_us == 0U || stress_block_delta > UINT64_MAX / UINT64_C(1000000)
			? 0U
			: stress_block_delta * UINT64_C(1000000) / window_us;
	bool verified = total_cycles > 0U;

#if defined(RT_BASELINE_STRESS)
	verified = verified && stress_permille >= 900U &&
		   non_idle_permille >= 900U && stress_block_delta > 0U &&
		   stress_rate > 0U && end->stress_checksum != 0U;
#else
	verified = verified && idle_permille >= 900U && stress_cycles == 0U &&
		   stress_block_delta == 0U && end->stress_checksum == 0U;
#endif
	printf(
		"RTOS_BASELINE_LOAD schema=1 workload=%s verified=%s "
		"window_duration_us=%llu cpu_non_idle_permille=%llu "
		"cpu_idle_permille=%llu benchmark_permille=%llu stress_permille=%llu "
		"stress_blocks=%llu stress_blocks_per_second=%llu stress_checksum=%llu "
		"accounting=freertos-runtime-counter\n",
		WORKLOAD_NAME, verified ? "true" : "false",
		(unsigned long long)window_us,
		(unsigned long long)non_idle_permille,
		(unsigned long long)idle_permille,
		(unsigned long long)benchmark_permille,
		(unsigned long long)stress_permille,
		(unsigned long long)stress_block_delta,
		(unsigned long long)stress_rate,
		(unsigned long long)end->stress_checksum);
	return verified;
}

static uint64_t delta_u64(uint64_t end, uint64_t start)
{
	return end >= start ? end - start : 0U;
}

static void benchmark_fatal(const char *stage, const char *reason)
{
	sampling_active = false;
	printf("RTOS_BASELINE_FATAL schema=1 stage=%s reason=%s\n", stage, reason);
	power_off();
}

static void power_off(void)
{
	register uintptr_t operation __asm__("x0") = 0x18U;
	register uintptr_t reason __asm__("x1") = 0x20026U;

	__asm__ volatile("hlt #0xf000" : "+r"(operation) : "r"(reason) : "memory");
	for (;;) {
		__asm__ volatile("wfi");
	}
}

#if defined(RT_BASELINE_STRESS)
static void stress_entry(void *parameter)
{
	uint64_t state = UINT64_C(0x9e3779b97f4a7c15);
	(void)parameter;
	for (;;) {
		for (uint32_t operation = 0U;
		     operation < STRESS_OPERATIONS_PER_BLOCK; ++operation) {
			state ^= state << 13;
			state ^= state >> 7;
			state ^= state << 17;
		}
		stress_checksum = state;
		++stress_blocks;
	}
}
#endif

void vApplicationMallocFailedHook(void)
{
	printf("RTOS_BASELINE_FATAL schema=1 stage=hook reason=malloc-failed\n");
	power_off();
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *task_name)
{
	(void)task;
	(void)task_name;
	printf("RTOS_BASELINE_FATAL schema=1 stage=hook reason=stack-overflow\n");
	power_off();
}

void vApplicationAssert(const char *file, uint32_t line)
{
	(void)file;
	printf("RTOS_BASELINE_FATAL schema=1 stage=assert line=%u\n", line);
	power_off();
}

/* SPDX-License-Identifier: Apache-2.0 */

#include <gtimer.h>
#include <psci.h>
#include <rthw.h>
#include <rtthread.h>

#include <stdbool.h>
#include <stdint.h>

#include "latency_stats.h"
#include "miss_accounting.h"

#define PERIOD_US 1000U
#define SAMPLE_COUNT 10000U
#define WARMUP_COUNT 100U
#define TOTAL_EXPIRATIONS (WARMUP_COUNT + SAMPLE_COUNT)
#define BENCHMARK_PRIORITY 1U
#define STRESS_PRIORITY 20U
#define BENCHMARK_STACK_SIZE 8192U
#define STRESS_STACK_SIZE 4096U
#define STRESS_OPERATIONS_PER_BLOCK 1024U
#define STARTUP_DELAY_MS 10U

#if RT_TICK_PER_SECOND != 1000
#error "the RT-Thread tick must equal the benchmark period"
#endif

#ifdef RT_USING_SMP
#error "the native RT-Thread baseline must be single-core"
#endif

#if defined(RT_BASELINE_STRESS)
#define WORKLOAD_NAME "cpu-stress"
#else
#define WORKLOAD_NAME "idle"
#endif

struct load_snapshot {
	uint64_t total_ticks;
	uint64_t idle_ticks;
	uint64_t benchmark_ticks;
	uint64_t stress_ticks;
	uint64_t cycle;
	uint64_t stress_blocks;
	uint64_t stress_checksum;
};

static struct rt_semaphore expiry_semaphore;
static struct rt_thread benchmark_thread;
rt_align(RT_ALIGN_SIZE) static uint8_t benchmark_stack[BENCHMARK_STACK_SIZE];
#if defined(RT_BASELINE_STRESS)
static struct rt_thread stress_thread;
rt_align(RT_ALIGN_SIZE) static uint8_t stress_stack[STRESS_STACK_SIZE];
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
static volatile uint64_t accounting_total_ticks;
static volatile uint64_t accounting_idle_ticks;
static volatile uint64_t accounting_benchmark_ticks;
static volatile uint64_t accounting_stress_ticks;
static volatile uint32_t expiry_count;
static volatile bool sampling_active;
static volatile bool tick_contract_failed;
static struct rt_thread *idle_thread;

static void benchmark_entry(void *parameter);
#if defined(RT_BASELINE_STRESS)
static void stress_entry(void *parameter);
#endif
static void tick_observer(void);
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

int main(void)
{
	if (rt_sem_init(&expiry_semaphore, "rtbsem", 0U, RT_IPC_FLAG_PRIO) !=
	    RT_EOK) {
		rt_kprintf("RTOS_BASELINE_FATAL schema=1 stage=init reason=semaphore\n");
		return -RT_ERROR;
	}
	rt_tick_sethook(tick_observer);

#if defined(RT_BASELINE_STRESS)
	if (rt_thread_init(&stress_thread, "rtstress", stress_entry, RT_NULL,
			   stress_stack, sizeof(stress_stack), STRESS_PRIORITY, 1U) !=
	    RT_EOK ||
	    rt_thread_startup(&stress_thread) != RT_EOK) {
		rt_kprintf("RTOS_BASELINE_FATAL schema=1 stage=init reason=stress-thread\n");
		return -RT_ERROR;
	}
#endif
	if (rt_thread_init(&benchmark_thread, "rtperiod", benchmark_entry, RT_NULL,
			   benchmark_stack, sizeof(benchmark_stack), BENCHMARK_PRIORITY,
			   1U) != RT_EOK ||
	    rt_thread_startup(&benchmark_thread) != RT_EOK) {
		rt_kprintf("RTOS_BASELINE_FATAL schema=1 stage=init reason=benchmark-thread\n");
		return -RT_ERROR;
	}
	return RT_EOK;
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
	counter_frequency_hz = rt_hw_get_gtimer_frq();
	if (counter_frequency_hz == 0U ||
	    counter_frequency_hz % RT_TICK_PER_SECOND != 0U) {
		benchmark_fatal("clock", "non-integral-tick");
	}
	counter_step = counter_frequency_hz / RT_TICK_PER_SECOND;
	rt_kprintf(
		"RTOS_BASELINE_CONFIG schema=1 os=rt-thread rtthread_version=5.2.2 "
		"board=qemu_virt_aarch64 cpu_model=cortex-a53 cpu_count=1 "
		"qemu_icount=false workload=%s period_us=%u samples=%u warmup=%u "
		"benchmark_priority=%u stress_priority=%u clock_hz=%llu "
		"ticks_per_sec=%u\n",
		WORKLOAD_NAME, PERIOD_US, SAMPLE_COUNT, WARMUP_COUNT,
		BENCHMARK_PRIORITY, STRESS_PRIORITY,
		(unsigned long long)counter_frequency_hz, RT_TICK_PER_SECOND);

	rt_thread_mdelay(STARTUP_DELAY_MS);
#if defined(RT_BASELINE_STRESS)
	if (stress_blocks == 0U) {
		benchmark_fatal("workload", "stress-not-running");
	}
	rt_kprintf(
		"RTOS_BASELINE_WORKLOAD_READY schema=1 kind=cpu-stress verified=true "
		"lower_priority=true benchmark_priority=%u stress_priority=%u "
		"blocks=%llu\n",
		BENCHMARK_PRIORITY, STRESS_PRIORITY,
		(unsigned long long)stress_blocks);
#else
	rt_kprintf(
		"RTOS_BASELINE_WORKLOAD_READY schema=1 kind=idle verified=true "
		"lower_priority=false benchmark_priority=%u stress_priority=%u blocks=0\n",
		BENCHMARK_PRIORITY, STRESS_PRIORITY);
#endif
	if (!capture_load_snapshot(&load_start)) {
		benchmark_fatal("load-snapshot", "start-failed");
	}
	if (!begin_sampling()) {
		benchmark_fatal("timer-schedule", "unstable-counter-deadline");
	}

	while (processed_expirations < TOTAL_EXPIRATIONS) {
		rt_base_t interrupt_level;
		uint64_t observed_cycle;
		uint32_t available_expirations;

		if (rt_sem_take(&expiry_semaphore, RT_WAITING_FOREVER) != RT_EOK) {
			benchmark_fatal("semaphore", "wait-failed");
		}
		interrupt_level = rt_hw_interrupt_disable();
		available_expirations = expiry_count;
		observed_cycle = rt_hw_get_cntpct_val();
		rt_hw_interrupt_enable(interrupt_level);
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
	rt_kprintf(
		"RTOS_BASELINE_COMPLETE schema=1 workload=%s status=pass "
		"timer_misses=%u warmup_timer_misses=%u early_wakes=0\n",
		WORKLOAD_NAME, measured_misses, warmup_misses);
	power_off();
}

static void tick_observer(void)
{
	struct rt_thread *current_thread;
	uint32_t expiration;
	uint64_t callback_cycle;

	if (!sampling_active) {
		return;
	}
	expiration = expiry_count;
	callback_cycle = rt_hw_get_cntpct_val();
	current_thread = rt_thread_self();
	++accounting_total_ticks;
	if (current_thread == idle_thread) {
		++accounting_idle_ticks;
	} else if (current_thread == &benchmark_thread) {
		++accounting_benchmark_ticks;
	}
#if defined(RT_BASELINE_STRESS)
	else if (current_thread == &stress_thread) {
		++accounting_stress_ticks;
	}
#endif
	if (expiration >= TOTAL_EXPIRATIONS) {
		tick_contract_failed = true;
		sampling_active = false;
		return;
	}
	callback_cycles[expiration] = callback_cycle;
	if (callback_cycle < deadline_cycles[expiration]) {
		tick_contract_failed = true;
	}
	if (expiration + 1U < TOTAL_EXPIRATIONS) {
		const uint64_t counter_before = rt_hw_get_cntpct_val();
		const int32_t timer_value = (int32_t)(uint32_t)rt_hw_get_gtimer_val();

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
	(void)rt_sem_release(&expiry_semaphore);
}

static bool begin_sampling(void)
{
	idle_thread = rt_thread_idle_gethandler();
	if (idle_thread == RT_NULL) {
		return false;
	}
	for (uint32_t attempt = 0U; attempt < 3U; ++attempt) {
		const rt_base_t interrupt_level = rt_hw_interrupt_disable();
		const uint64_t counter_before = rt_hw_get_cntpct_val();
		const int32_t timer_value = (int32_t)(uint32_t)rt_hw_get_gtimer_val();

		if (timer_value > 0 && (uint64_t)(uint32_t)timer_value <= counter_step) {
			deadline_cycles[0] = counter_before + (uint32_t)timer_value;
			expiry_count = 0U;
			tick_contract_failed = false;
			sampling_active = true;
			rt_hw_interrupt_enable(interrupt_level);
			return true;
		}
		rt_hw_interrupt_enable(interrupt_level);
		rt_thread_mdelay(1U);
	}
	return false;
}

static bool capture_load_snapshot(struct load_snapshot *snapshot)
{
	rt_base_t interrupt_level;

	if (snapshot == RT_NULL) {
		return false;
	}
	interrupt_level = rt_hw_interrupt_disable();
	snapshot->total_ticks = accounting_total_ticks;
	snapshot->idle_ticks = accounting_idle_ticks;
	snapshot->benchmark_ticks = accounting_benchmark_ticks;
	snapshot->stress_ticks = accounting_stress_ticks;
	snapshot->cycle = rt_hw_get_cntpct_val();
	snapshot->stress_blocks = stress_blocks;
	snapshot->stress_checksum = stress_checksum;
	rt_hw_interrupt_enable(interrupt_level);
	return true;
}

static bool emit_latency_result(const char *metric, const uint64_t *samples,
				uint64_t actual_duration_us)
{
	struct rt_baseline_latency_summary summary;

	if (!rt_baseline_summarize(samples, SAMPLE_COUNT, sort_scratch, &summary)) {
		return false;
	}
	rt_kprintf(
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
	const uint64_t total_ticks = delta_u64(end->total_ticks, start->total_ticks);
	const uint64_t idle_ticks = delta_u64(end->idle_ticks, start->idle_ticks);
	const uint64_t benchmark_ticks =
		delta_u64(end->benchmark_ticks, start->benchmark_ticks);
	const uint64_t stress_ticks =
		delta_u64(end->stress_ticks, start->stress_ticks);
	const uint64_t stress_block_delta =
		delta_u64(end->stress_blocks, start->stress_blocks);
	uint64_t window_ns;

	if (end->cycle < start->cycle ||
	    !rt_baseline_cycles_to_ns(end->cycle - start->cycle,
				      counter_frequency_hz, &window_ns) ||
	    idle_ticks > total_ticks) {
		return false;
	}
	const uint64_t window_us = window_ns / 1000U;
	const uint64_t non_idle_ticks = total_ticks - idle_ticks;
	const uint64_t idle_permille =
		rt_baseline_ratio_permille(idle_ticks, total_ticks);
	const uint64_t non_idle_permille =
		rt_baseline_ratio_permille(non_idle_ticks, total_ticks);
	const uint64_t benchmark_permille =
		rt_baseline_ratio_permille(benchmark_ticks, total_ticks);
	const uint64_t stress_permille =
		rt_baseline_ratio_permille(stress_ticks, total_ticks);
	const uint64_t stress_rate =
		window_us == 0U || stress_block_delta > UINT64_MAX / UINT64_C(1000000)
			? 0U
			: stress_block_delta * UINT64_C(1000000) / window_us;
	bool verified = total_ticks >= SAMPLE_COUNT;

#if defined(RT_BASELINE_STRESS)
	verified = verified && stress_permille >= 900U &&
		   non_idle_permille >= 900U && stress_block_delta > 0U &&
		   stress_rate > 0U && end->stress_checksum != 0U;
#else
	verified = verified && idle_permille >= 900U && stress_ticks == 0U &&
		   stress_block_delta == 0U && end->stress_checksum == 0U;
#endif
	rt_kprintf(
		"RTOS_BASELINE_LOAD schema=1 workload=%s verified=%s "
		"window_duration_us=%llu cpu_non_idle_permille=%llu "
		"cpu_idle_permille=%llu benchmark_permille=%llu stress_permille=%llu "
		"stress_blocks=%llu stress_blocks_per_second=%llu stress_checksum=%llu "
		"accounting=rt-thread-tick-hook\n",
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
	rt_kprintf("RTOS_BASELINE_FATAL schema=1 stage=%s reason=%s\n", stage,
		   reason);
	power_off();
}

static void power_off(void)
{
	psci_system_off();
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

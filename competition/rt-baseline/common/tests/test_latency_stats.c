/* SPDX-License-Identifier: Apache-2.0 */

#include "latency_stats.h"

#include <assert.h>
#include <stdint.h>

static void test_cycle_conversion(void)
{
	uint64_t nanoseconds = 0U;

	assert(rt_baseline_cycles_to_ns(UINT64_C(62500000), UINT64_C(62500000),
					 &nanoseconds));
	assert(nanoseconds == UINT64_C(1000000000));
	assert(rt_baseline_cycles_to_ns(UINT64_C(62500), UINT64_C(62500000),
					 &nanoseconds));
	assert(nanoseconds == UINT64_C(1000000));
	assert(!rt_baseline_cycles_to_ns(1U, 0U, &nanoseconds));
}

static void test_summary(void)
{
	const uint64_t samples[] = {9U, 1U, 5U, 3U, 7U, 2U, 4U, 8U, 6U, 10U};
	uint64_t scratch[10];
	struct rt_baseline_latency_summary summary;

	assert(rt_baseline_summarize(samples, 10U, scratch, &summary));
	assert(summary.minimum_ns == 1U);
	assert(summary.mean_ns == 5U);
	assert(summary.p50_ns == 5U);
	assert(summary.p90_ns == 9U);
	assert(summary.p99_ns == 10U);
	assert(summary.p999_ns == 10U);
	assert(summary.maximum_ns == 10U);
	assert(!rt_baseline_summarize(samples, 0U, scratch, &summary));
}

static void test_permille(void)
{
	assert(rt_baseline_ratio_permille(9U, 10U) == 900U);
	assert(rt_baseline_ratio_permille(1U, 0U) == 0U);
}

int main(void)
{
	test_cycle_conversion();
	test_summary();
	test_permille();
	return 0;
}

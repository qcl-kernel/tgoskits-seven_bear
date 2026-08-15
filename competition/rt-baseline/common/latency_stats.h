/* SPDX-License-Identifier: Apache-2.0 */

#ifndef RT_BASELINE_LATENCY_STATS_H_
#define RT_BASELINE_LATENCY_STATS_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct rt_baseline_latency_summary {
	uint64_t minimum_ns;
	uint64_t mean_ns;
	uint64_t p50_ns;
	uint64_t p90_ns;
	uint64_t p99_ns;
	uint64_t p999_ns;
	uint64_t maximum_ns;
};

bool rt_baseline_cycles_to_ns(uint64_t cycles, uint64_t frequency_hz,
			      uint64_t *nanoseconds);

bool rt_baseline_summarize(const uint64_t *samples, size_t sample_count,
			   uint64_t *scratch,
			   struct rt_baseline_latency_summary *summary);

uint64_t rt_baseline_ratio_permille(uint64_t portion, uint64_t whole);

#endif /* RT_BASELINE_LATENCY_STATS_H_ */

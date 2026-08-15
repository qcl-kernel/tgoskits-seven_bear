/* SPDX-License-Identifier: Apache-2.0 */

#include "latency_stats.h"

#include <limits.h>

#define NANOSECONDS_PER_SECOND UINT64_C(1000000000)
#define PERMILLE_SCALE UINT64_C(1000)

static void heap_sort(uint64_t *values, size_t count);
static void sift_down(uint64_t *values, size_t root, size_t count);
static uint64_t nearest_rank(const uint64_t *sorted, size_t count,
			     uint32_t numerator, uint32_t denominator);

bool rt_baseline_cycles_to_ns(uint64_t cycles, uint64_t frequency_hz,
			      uint64_t *nanoseconds)
{
	uint64_t seconds;
	uint64_t remainder;

	if (frequency_hz == 0U || nanoseconds == NULL) {
		return false;
	}
	seconds = cycles / frequency_hz;
	remainder = cycles % frequency_hz;
	if (seconds > UINT64_MAX / NANOSECONDS_PER_SECOND ||
	    remainder > UINT64_MAX / NANOSECONDS_PER_SECOND) {
		return false;
	}
	*nanoseconds = seconds * NANOSECONDS_PER_SECOND +
		       remainder * NANOSECONDS_PER_SECOND / frequency_hz;
	return true;
}

bool rt_baseline_summarize(const uint64_t *samples, size_t sample_count,
			   uint64_t *scratch,
			   struct rt_baseline_latency_summary *summary)
{
	uint64_t sum = 0U;

	if (samples == NULL || scratch == NULL || summary == NULL ||
	    sample_count == 0U) {
		return false;
	}
	for (size_t index = 0U; index < sample_count; ++index) {
		scratch[index] = samples[index];
	}
	heap_sort(scratch, sample_count);
	for (size_t index = 0U; index < sample_count; ++index) {
		if (UINT64_MAX - sum < scratch[index]) {
			return false;
		}
		sum += scratch[index];
	}
	*summary = (struct rt_baseline_latency_summary){
		.minimum_ns = scratch[0],
		.mean_ns = sum / sample_count,
		.p50_ns = nearest_rank(scratch, sample_count, 50U, 100U),
		.p90_ns = nearest_rank(scratch, sample_count, 90U, 100U),
		.p99_ns = nearest_rank(scratch, sample_count, 99U, 100U),
		.p999_ns = nearest_rank(scratch, sample_count, 999U, 1000U),
		.maximum_ns = scratch[sample_count - 1U],
	};
	return true;
}

uint64_t rt_baseline_ratio_permille(uint64_t portion, uint64_t whole)
{
	if (whole == 0U || portion > UINT64_MAX / PERMILLE_SCALE) {
		return 0U;
	}
	return portion * PERMILLE_SCALE / whole;
}

static void heap_sort(uint64_t *values, size_t count)
{
	if (count < 2U) {
		return;
	}
	for (size_t parent = count / 2U; parent > 0U; --parent) {
		sift_down(values, parent - 1U, count);
	}
	for (size_t end = count; end > 1U; --end) {
		const uint64_t maximum = values[0];

		values[0] = values[end - 1U];
		values[end - 1U] = maximum;
		sift_down(values, 0U, end - 1U);
	}
}

static void sift_down(uint64_t *values, size_t root, size_t count)
{
	for (;;) {
		size_t child = root * 2U + 1U;
		size_t maximum = root;

		if (child >= count) {
			return;
		}
		if (values[child] > values[maximum]) {
			maximum = child;
		}
		if (child + 1U < count && values[child + 1U] > values[maximum]) {
			maximum = child + 1U;
		}
		if (maximum == root) {
			return;
		}
		const uint64_t value = values[root];

		values[root] = values[maximum];
		values[maximum] = value;
		root = maximum;
	}
}

static uint64_t nearest_rank(const uint64_t *sorted, size_t count,
			     uint32_t numerator, uint32_t denominator)
{
	const size_t quotient = count / denominator;
	const size_t remainder = count % denominator;
	const size_t rank = quotient * numerator +
			    (remainder * numerator + denominator - 1U) /
				    denominator;

	return sorted[rank - 1U];
}

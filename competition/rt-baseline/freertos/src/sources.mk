src_c_srcs := main.c latency_stats.c
INC_DIRS += $(APP_SRC_DIR)

ifeq ($(RT_BASELINE_STRESS),y)
CPPFLAGS += -DRT_BASELINE_STRESS
endif

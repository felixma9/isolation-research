# Builds every benchmark program and workload into build/.
#   make          build everything
#   make clean    remove build/
#
# A new benchmark is a folder benchmarkN/ with a main.c (and config.py); it is
# picked up here automatically and linked with everything in common/.

CC      = gcc
CFLAGS  = -O2 -Wall -Icommon

COMMON     = $(wildcard common/*.c)
BENCHMARKS = $(patsubst %/main.c,build/%,$(wildcard benchmark*/main.c))
WORKLOADS  = $(patsubst workloads/%.c,build/%,$(wildcard workloads/*.c))

all: $(BENCHMARKS) $(WORKLOADS)

build/benchmark%: benchmark%/main.c $(COMMON) $(wildcard common/*.h) | build
	$(CC) $(CFLAGS) -o $@ $< $(COMMON)

# Workloads are static, so their memory does not include shared libraries.
build/%: workloads/%.c | build
	$(CC) $(CFLAGS) -static -o $@ $<

build:
	mkdir -p build

clean:
	rm -rf build

.PHONY: all clean

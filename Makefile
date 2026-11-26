# Builds the workloads into build/ (build/small is the one the run scripts use).
#   make          build everything
#   make clean    remove build/

CC     = gcc
CFLAGS = -O2 -Wall

WORKLOADS = $(patsubst workloads/%.c,build/%,$(wildcard workloads/*.c))

all: $(WORKLOADS)

# Workloads are static, so their memory does not include shared libraries.
build/%: workloads/%.c | build
	$(CC) $(CFLAGS) -static -o $@ $<

build:
	mkdir -p build

clean:
	rm -rf build

.PHONY: all clean

.PHONY: all
all: locking

locking: locking.cpp
	clang++ -lpthread locking.cpp -o locking

clean:
	rm -rf locking

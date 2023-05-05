#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define LOCK(x) clang::annotate("LOCKING::" #x)

pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

int counter = 0;

[[LOCK(REQUIRED)]] void increment_counter() {
  counter++; }
[[LOCK(TAKES)]] void get_lock() { pthread_mutex_lock(&mutex); }
[[LOCK(RELEASES)]] void release_lock() { pthread_mutex_unlock(&mutex); }

void with_lock([[LOCK(REQUIRED)]]) {
  get_lock();
  increment_counter();
  usleep(rand() % 500);
}

void *worker(void *_arg) {
  for (size_t i = 0; i < 1000; i++) {
    if (rand() % 2 == 0) {
      do_work();
    }
    usleep(500);
  }
  return nullptr;
}

[[LOCK(SPAWNER)]] int main() {
  pthread_t tids[4];
  for (int i = 0; i < 4; i++) {
    pthread_create(&tids[i], nullptr, &worker, nullptr);
    printf("Created thread: %d\n", i);
  }

  for (int i = 0; i < 4; i++) {
    void *_res;
    pthread_join(tids[i], &_res);
    printf("Joined thread: %d\n", i);
  }
  printf("Final counter value: %d\n", counter);
}

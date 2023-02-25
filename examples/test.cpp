#include <stdio.h>

#define COLOR(x) clang::annotate("COLOR::" #x)

[[COLOR(BLUE)]] int ret0() { return 0; };

[[COLOR(RED)]] int main() {
  [[COLOR(GREEN)]] int r = 0;
  printf("!!! %d\n", r);
  return ret0();
}

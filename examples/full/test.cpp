#include <functional>
#include <stdio.h>

#define COLOR(x) clang::annotate("COLOR::" #x)

[[COLOR(PURPLE)]] int printf(char *fmt, ...);

[[COLOR(BLUE)]] int ret0() { return 0; };
// This is an uncolored function calling a BLUE function - RED functions cannot
// call this.
int ret0_indirect() { return ret0(); };
[[COLOR(PURPLE)]] int ret_wrapper() { return ret0(); };

[[COLOR(YELLOW)]] int ret1() { return 1; };

[[COLOR(RED)]] int main() {
  // This annotation should be ignored - it's not on a function
  [[COLOR(GREEN)]] int r = 0;
  printf("!!! %d\n", r);

  // (1) This block is invalid - Change ret0 to ret1 to make it valid
  {
    [[COLOR(YELLOW)]] auto WrapperFn1 = []() { return ret0(); };
    WrapperFn1();
  }

  if (true) {
    [[COLOR(PURPLE)]] auto WrapperFn = ({
      (void)0;
      []() { return ret0(); };
    });

    [[COLOR(PURPLE)]] auto WrapperFn1 = []() { return ret0(); };
    (void)WrapperFn1();

    // (2) To make this program valid - uncomment the following and remove the
    // original return statement.
    // return ret_wrapper() + WrapperFn1();
    return ret_wrapper() + ret0_indirect();
  }
  return 0;
}

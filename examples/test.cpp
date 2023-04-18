#include <functional>
#include <stdio.h>

#define COLOR(x) clang::annotate("COLOR::" #x)

[[COLOR(PURPLE)]] int printf(char *fmt, ...);

[[COLOR(BLUE)]] int ret0() { return 0; };
[[COLOR(YELLOW)]] int ret1() { return 0; };
[[COLOR(PURPLE)]] int ret_wrapper() { return ret0(); };

[[COLOR(RED)]] int main() {
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
    return ret_wrapper() + ret0();
  }
  return 0;
}

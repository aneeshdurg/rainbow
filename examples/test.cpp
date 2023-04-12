#include <functional>
#include <stdio.h>

#define COLOR(x) clang::annotate("COLOR::" #x)

[[COLOR(PURPLE)]] int printf(char *fmt, ...);

[[COLOR(BLUE)]] int ret0() { return 0; };
[[COLOR(PURPLE)]] int ret_wrapper() { return ret0(); };

typedef void (*VFn)(void);

// [[COLOR(RED)]] void unused([[COLOR(BLUE)]] std::function<void()> my_fn,
//                            [[COLOR(BLUE)]] VFn my_fn_2) {
//   my_fn();
//   my_fn_2();
// }

[[COLOR(BLUE)]] void idk() {}

[[COLOR(RED)]] int main() {
  [[COLOR(GREEN)]] int r = 0;
  printf("!!! %d\n", r);

  auto BlueFn = []() {};
  // unused(BlueFn, idk);

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

    return ret_wrapper() + ret0(); // + WrapperFn();
  }
  return 0;
}

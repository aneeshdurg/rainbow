# Rainbow as an LLVM pass

The python version of rainbow uses clang to walk the AST. This makes the
complexity of tracking annotations and usage across templates difficult, and the
large number of C++ features also makes potentially tracking control flow
(instead of only tracking calls) more difficult. It would likely be easier to
support a wider set of features (and potentially other languages that support
LLVM) by implementing this as an LLVM pass.

To run the pass, build [pyllvmpass](https://github.com/aneeshdurg/pyllvmpass)
and run with:

```bash
# either set LLVM_CONFIG to point to the llvm-config binary on your system, or
# ensure that `llvm-config` is on the PATH
opt --load-pass-plugin=/home/aneesh/pyllvmpass/target/release/libpyllvmpass.so \
    --passes=pyllvmpass[rainbow_llvm] in.ll -S -o out.ll
```

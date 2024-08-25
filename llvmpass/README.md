# Rainbow as an LLVM pass

The python version of rainbow uses clang to walk the AST. This makes the
complexity of tracking annotations and usage across templates difficult, and the
large number of C++ features also makes potentially tracking control flow
(instead of only tracking calls) more difficult. It would likely be easier to
support a wider set of features (and potentially other languages that support
LLVM) by implementing this as an LLVM pass.

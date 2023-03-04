# Rainbow - arbitrary function coloring in CPP

This project aims to implement arbitrary function coloring rules within CPP.
This is accomplished by using clang's Annotate Attribute, and allowing the user
to supply cypher patterns to reject call graphs that violate coloring
restrictions.

## Requirements
TODO write better instructions

+ Build [clang](https://github.com/llvm/llvm-project)
+ Include the clang python module in your `PYTHONPATH`
  + The module can be found at `$LLVM_PROJECT/clang/bindings/python/clang`


## Example

Let's walk through a simple example of how `rainbow` can be used.
First, let us look at `examples/config.json`.

```json
{
  "prefix": "COLOR::",
  "patterns": [
    "(:RED)-[:CALLS*]->(:BLUE)",
    "(:GREEN)-[:CALLS*]->(:RED)",
    "(:YELLOW)-->(x) WHERE NOT x:YELLOW"
  ]
}
```

Ignoring `prefix` for a moment, let's look at the values in `patterns`.

```cypher
(:RED)-[:CALLS*]->(:BLUE)
(:GREEN)-[:CALLS*]->(:RED)
(:YELLOW)-->(x) WHERE NOT x:YELLOW
```

Here we see fragments of patterns from the
[openCypher](https://github.com/opencypher/openCypher/) graph querying language.
There is one pattern per element, and each pattern specifies a call graph that must
be rejected. It is guaranteed that there is only one type of edge, and the type
is `CALLS` to denote that one function calls another. Here we see that it is
forbidden for a `RED` function to directory or indirectly call a `BLUE`
function, or for a `GREEN` function to directly or indirectly
call a `RED` function, or finally, for any `YELLOW` function to call any
function that isn't also `YELLOW`.

`prefix` gives us a prefix to prepend to every color required to tag a function
in `c++`. This helps prevent against collision if using multiple sets of colors
that all model different semantics.

Next, let us look at the contents of `examples/test.cpp`.

```cpp
#include <stdio.h>
#define COLOR(x) clang::annotate("COLOR::" #x)
                                               
[[COLOR(BLUE)]] int ret0() { return 0; };
                                               
[[COLOR(RED)]] int main() {
  [[COLOR(GREEN)]] int r = 0;
  printf("!!! %d\n", r);
  return ret0();
}
```

This defines a simple program that has two functions tagged with colors
`COLOR::BLUE` and `COLOR::RED`, as well as a variable incorrectly tagged with
the color `COLOR::GREEN` (only function colors are supported). Note that
functions are tagged by using the `clang::annotate` attribute. The argument to
`clang::annotate` must be in the format `{config.prefix}{color}`.

Now we can run `rainbow` to generate a cypher program that determines the
validity of this example. To run `rainbow`, use the command:

```bash
# You need to build `libclang.so` from https://github.com/llvm/llvm-project
# The path to the build library is stored in this variable for this example
LLVM_LIB_PATH= ~/llvm-project/build/lib/libclang.so
./rainbow.py examples/test.cpp examples/patterns.txt -c $LLVM_LIB_PATH
```

And it should output:

```cypher
CREATE
  (printf),
  (ret0 :BLUE),
  (main :RED),
  (main)-[:CALLs]->(printf),
  (main)-[:CALLs]->(ret0),
 (sentinel)
;
OPTIONAL MATCH (:RED)-[:CALLS*]->(:BLUE) WITH *, count(*) > 0 as invalidcalls0
OPTIONAL MATCH (:GREEN)-[:CALLS*]->(:RED) WITH *, count(*) > 1 as invalidcalls1
OPTIONAL MATCH (:YELLOW)-->(x) WHERE NOT x:YELLOW WITH *, count(*) > 1 as invalidcalls2
RETURN invalidcalls0 OR invalidcalls1 OR invalidcalls2 as invalidcalls
;
```

Here we see the call graph modelled as a `CREATE` statement, and our patterns
compiled together in a single `openCypher` query that will output a variable
that will store `true` if the program should be rejected and `false` otherwise.

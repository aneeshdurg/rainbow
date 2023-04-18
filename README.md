# Rainbow - arbitrary function coloring in CPP

![CI Status](https://github.com/aneeshdurg/rainbow/actions/workflows/test.yml/badge.svg)

This project aims to implement arbitrary function coloring rules within CPP.
This is accomplished by using clang's Annotate Attribute, and allowing the user
to supply cypher patterns to reject call graphs that violate coloring
restrictions.

## Installation

```bash
# Install clang-15
sudo apt update
sudo apt install clang-15

# Clone and install rainbow
git clone https://github.com/aneeshdurg/rainbow.git
cd rainbow
pip install .
```

## Example

Let's walk through a simple example of how `rainbow` can be used.
First, let us look at an exaple configuration.

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

Next, let us look at a sample program.

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
python3 -m rainbow <path_to_source>.cpp <path_to_config>.json -vvv
```

And it should output:

```
program is invalid: True
```

See the `examples/` directory for more examples of how to get
detailed error reporting from `rainbow`. For example, if you open
`examples/full/test.cpp` and `examples/full/config.json`, you will see a more
involved example for an invalid program (with comments detailing how to make the
program valid), and a more detailed configuration that includes custom error
reporting it make it easier to find errors in the source.

### Executors

Executors are backends that handle the openCypher execution. By default, the
executor is implemented as direct calls to [sPyCy](https://github.com/aneeshdurg/spycy).
However, the `examples` directory contains alternate executors such as a
[Neo4j](https://github.com/neo4j/neo4j) executor and a executor that echoes the
queries to stdout. Try using the `echo` executor with:

```bash
python3 -m rainbow examples/full/test.cpp examples/full/config_echo.json
```

and you should see:

```cypher
CREATE (`printf__1`:PURPLE {name: 'printf'}),
  ...
  (`ret_wrapper__3`) -[:CALLS]-> (`ret0__2`),
  (`main__4`) -[:CALLS]-> (`printf__1`),
  (`main__4`) -[:CALLS]-> (`WrapperFn1__38`),
  (`main__4`) -[:CALLS]-> (`WrapperFn1__39`),
  (`main__4`) -[:CALLS]-> (`ret_wrapper__3`),
  (`main__4`) -[:CALLS]-> (`ret0__2`),
  (`WrapperFn1__38`) -[:CALLS]-> (`ret0__2`),
  (`WrapperFn1__39`) -[:CALLS]-> (`ret0__2`)
MATCH p = (:RED)-[:CALLS*]->(:BLUE) WHERE NOT any(n in nodes(p) WHERE n:PURPLE) RETURN count(*) > 0 as invalidcalls;
MATCH (:GREEN)-[:CALLS*]->(:RED) RETURN count(*) > 0 as invalidcalls;
MATCH (:YELLOW)-->(x) WHERE NOT x:YELLOW RETURN count(*) > 0 as invalidcalls
program is invalid: UNKNOWN
```

Here you can see the call graph modeled as a `CREATE` statement, and the
patterns assembled into full queries.

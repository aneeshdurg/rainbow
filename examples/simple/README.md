# Simple example

This example covers how to create a config file that will reject all programs
containing any functions with a given tag.

## config.json

To start, we need to build a configuration file. The first step is to define
what our set of colors will be that we'd like `rainbow` to operate on.

For this example, we will only have a single color representing the tag we'd
like to disallow.

```json
{
  "prefix": "",
  "colors": ["DISALLOWED"]
}
```

next, we need to specify the pattern we're trying to reject:
```json
{
  ...,
  "patterns": ["(:DISALLOWED)"]
}
```

This tells rainbow, find all functions with the tag `DISALLOWED` and reject the
program if any are found.

## Setting up a source file

In order for rainbow to run it's analysis, we need to tag our functions with
annotations. Take a look at `source.cpp`.

```c++
[[clang::annotate("DISALLOWED")]] int disallowed() { return 0; }
[[clang::annotate("DISALLOWED")]] int also_disallowed() { return 0; }
int main() { return disallowed(); }
```

Here we see two functions tagged as `DISALLOWED`.

## Running rainbow

We can now run this program as:

```
python3 -m rainbow ./examples/simple/source.cpp ./<config dir>/config.json
```

This should output nothing to the console, but checking the exit code (`$?` in
bash or `$status` in fish), will reveal an exit code of 1, indicating an error.
We can re-run rainbow with increased verbosity to see:

```
$ python3 -m rainbow ./examples/simple/source.cpp ./<config dir>/config.json
WARNING:rainbow:Pattern 0 found errors
INFO:rainbow:program is invalid: True
```

This tells us which pattern failed. Other examples will show you how to
configure more detailed output messages which can tell you exactly how the
check failed.

## Rejecting function calls

Currently this configuration rejects all definitions of `DISALLOWED` functions,
but what if we just want to rejects *calls* to `DISALLOWED` functions? Since
`rainbow` provides us with an annotated call graph, this is very easy to
express, simply replace `"patterns"` your config with:

```json
{
  ...,
  "patterns": ["()-->(:DISALLOWED)"]
}
```

This can now be run with:

```
python3 -m rainbow ./examples/simple/source.cpp ./examples/simple/config.json
```

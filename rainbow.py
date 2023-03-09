#!/usr/bin/env python3
import json
import subprocess
import sys

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click

import clang.cindex


@dataclass
class Rainbow:
    tu: clang.cindex.TranslationUnit
    prefix: str

    _fns_to_tags: Dict[str, List[str]] = field(default_factory=dict)
    _call_graph: Dict[str, List[str]] = field(default_factory=dict)
    _fns_stack: List[Tuple[str, int]] = field(default_factory=list)

    def isFunction(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a function definition, and if so, return the name of the function called if possible"""
        if node.kind == clang.cindex.CursorKind.FUNCTION_DECL:
            return node.spelling
        for c in node.get_children():
            if c.kind == clang.cindex.CursorKind.LAMBDA_EXPR:
                raise Exception("Lambdas unsupported")
                # return "{node.spelling}[[{c.spelling}]]"
        return None

    def isCall(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a function call, and if so, return the name of the function called if possible"""
        if node.kind != clang.cindex.CursorKind.CALL_EXPR:
            return None
        if (spelling := node.spelling) != "operator()":
            return spelling

        for c in node.get_children():
            if c.kind == clang.cindex.CursorKind.UNEXPOSED_EXPR:
                if c.spelling == "operator()":
                    continue
                # We mangaled lambda names - need to track lambdas better
                return c.spelling
        return None

    def isColor(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a tag defining a color"""
        if node.kind == clang.cindex.CursorKind.ANNOTATE_ATTR:
            if node.spelling.startswith(self.prefix):
                return node.spelling[len(self.prefix) :]
        return None

    def _register_function(self, fnname: str, depth: int):
        if fnname not in self._fns_to_tags:
            self._fns_to_tags[fnname] = []
        if fnname not in self._call_graph:
            self._call_graph[fnname] = []
        self._fns_stack.append((fnname, depth))

    def _register_call(self, called_fn: str):
        fn, _ = self._fns_stack[-1]
        # TODO(aneesh) can lambdas shadow names of functions? This might need to also use the depth if so
        self._call_graph[fn].append(called_fn)

    def _try_tag_function(self, color: str, depth: int):
        fn, fdepth = self._fns_stack[-1]
        if fdepth == (depth - 1):
            self._fns_to_tags[fn].append(color)

    def _process(self, node: clang.cindex.Cursor, depth: int):
        indent = depth * 2
        # print(" " * indent, node.kind, node.spelling, file=sys.stderr)
        fnname = self.isFunction(node)
        if fnname:
            self._register_function(fnname, depth)
        elif called := self.isCall(node):
            self._register_call(called)
        elif color := self.isColor(node):
            self._try_tag_function(color, depth)
        for c in node.get_children():
            self._process(c, depth + 1)

        if fnname:
            self._fns_stack.pop()

    def process(self):
        """Process the input file and extract the call graph, and colors for every function"""
        self._process(self.tu.cursor, 0)
        assert len(self._fns_stack) == 0

    def toCypher(self) -> str:
        """Must only be called after `self.process`.
        Outputs the call graph as an openCypher CREATE query, tagging all functions with their colors"""
        if (
            len(self._fns_to_tags) == 0
            or max(len(t) for t in self._fns_to_tags.values()) == 0
        ):
            return "// no tagged functions\n;\n"
        output = []
        referenced_fns = set()
        for fn in self._call_graph:
            if len(self._call_graph[fn]) > 0:
                referenced_fns.add(fn)
                for callee in self._call_graph[fn]:
                    referenced_fns.add(callee)

        output.append("CREATE")
        for fn in self._fns_to_tags:
            if fn not in referenced_fns:
                continue
            tags = self._fns_to_tags[fn]
            tag = ""
            if len(tags):
                tag = f" :{tags[0]}"
            output.append(f"  ({fn}{tag}{{name: \"{fn}\"}}),")
        for i, caller in enumerate(self._call_graph):
            last_caller = i == (len(self._call_graph) - 1)
            callees = self._call_graph[caller]
            for j, callee in enumerate(callees):
                last_edge = last_caller and j == (len(callees) - 1)
                edge = f"  ({caller})-[:CALLS]->({callee})"
                if not last_edge:
                    edge += ","
                output.append(edge)
        output.append(";")
        return "\n".join(output)


def patternsToCypher(patterns: List[str]) -> List[str]:
    """Given a list of `patterns` output a cypher query combining them all"""
    output = []
    for pattern in patterns:
        output.append(
            f"MATCH {pattern.strip()} RETURN count(*) > 0 as invalidcalls\n;"
        )
    return output


@click.command(help="rainbow - arbitrary function coloring for c++!")
@click.argument("cpp_file")
@click.argument("config_file")
@click.option(
    "-c", "--clangLocation", type=Path, help="Path to libclang.so", required=True
)
def main(cpp_file: str, config_file: str, clanglocation: Optional[Path]):
    with open(config_file) as f:
        config = json.load(f)

    prefix = config.get("prefix", "COLOR::")
    patterns: List[str] = []
    if "patterns" not in config:
        raise Exception("Missing field 'patterns' from config file")
    else:
        assert isinstance(config["patterns"], list)
        patterns = config["patterns"]

    clang.cindex.Config.set_library_file(clanglocation)
    index = clang.cindex.Index.create()
    # TODO set compilation db if it exists
    rainbow = Rainbow(index.parse(cpp_file), prefix, colors)
    rainbow.process()
    create_query = rainbow.toCypher()
    validate_queries = patternsToCypher(patterns)
    validate_query = "\n".join(validate_queries)

    executor = config.get("executor", "executors/neo4j_adapter.py")
    p = subprocess.Popen([executor, config_file],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE)
    (res, _) = p.communicate((create_query + "\n" + validate_query).encode())
    output = [json.loads(l) for l in res.decode().strip().split("\n") if len(l)]
    exitcode = 0
    if len(output) == 0:
        invalidcalls = "UNKNOWN"
        exitcode = 2
    else:
        invalidcalls = any(output)
        if invalidcalls:
            exitcode = 1
    print("program is invalid:", invalidcalls, file=sys.stderr)
    sys.exit(exitcode)

if __name__ == "__main__":
    main()

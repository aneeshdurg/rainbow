#!/usr/bin/env python3
import json

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import click

import clang.cindex


@dataclass
class Rainbow:
    tu: clang.cindex.TranslationUnit
    prefix: str

    fns_to_tags = {}
    fns_stack = []
    call_graph = {}

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

    def _process(self, node: clang.cindex.Cursor, depth: int):
        indent = depth * 2
        # print(" " * indent, node.kind, node.spelling, file=sys.stderr)
        fnname = self.isFunction(node)
        if fnname:
            if fnname not in self.fns_to_tags:
                self.fns_to_tags[fnname] = []
            if fnname not in self.call_graph:
                self.call_graph[fnname] = []
            self.fns_stack.append((fnname, depth))
        elif called := self.isCall(node):
            fn, _ = self.fns_stack[-1]
            self.call_graph[fn].append(called)
        elif color := self.isColor(node):
            fn, fdepth = self.fns_stack[-1]
            if fdepth == (depth - 1):
                self.fns_to_tags[fn].append(color)
        for c in node.get_children():
            self._process(c, depth + 1)
        if fnname:
            self.fns_stack.pop()

    def process(self):
        """Process the input file and extract the call graph, and colors for every function"""
        self._process(self.tu.cursor, 0)
        assert len(self.fns_stack) == 0

    def toCypher(self) -> str:
        """Must only be called after `self.process`.
        Outputs the call graph as an openCypher CREATE query, tagging all functions with their colors"""
        if len(self.fns_to_tags) == 0 or max(len(t) for t in self.fns_to_tags.values()) == 0:
            return "// no tagged functions\n;\n"
        output = []
        referenced_fns = set()
        for fn in self.call_graph:
            if len(self.call_graph[fn]) > 0:
                referenced_fns.add(fn)
                for callee in self.call_graph[fn]:
                    referenced_fns.add(callee)

        output.append("CREATE")
        for fn in self.fns_to_tags:
            if fn not in referenced_fns:
                continue
            tags = self.fns_to_tags[fn]
            tag = ""
            if len(tags):
                tag = f" :{tags[0]}"
            output.append(f"  ({fn}{tag}),")
        for caller in self.call_graph:
            for callee in self.call_graph[caller]:
                output.append(f"  ({caller})-[:CALLs]->({callee}),")
        output.append(" (sentinel)")
        output.append(";")
        return "\n".join(output)


def patternsToCypher(patterns: List[str]) -> str:
    """Given a list of `patterns` output a cypher query combining them all"""
    output = []
    pcount = 0
    for i, pattern in enumerate(patterns):
        limit = 0 if i == 0 else 1
        output.append(
            f"OPTIONAL MATCH {pattern.strip()} WITH *, count(*) > {limit} as invalidcalls{i}"
        )
        pcount += 1
    output.append(
        "RETURN "
        + " OR ".join([f"invalidcalls{i}" for i in range(pcount)])
        + " as invalidcalls"
    )
    output.append(";")
    output.append("")
    return "\n".join(output)


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
    rainbow = Rainbow(index.parse(cpp_file), prefix)
    rainbow.process()
    print(rainbow.toCypher())
    print(patternsToCypher(patterns))


if __name__ == "__main__":
    main()

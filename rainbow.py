#!/usr/bin/env python3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click

import clang.cindex


@dataclass
class Rainbow:
    tu: clang.cindex.TranslationUnit

    fns_to_tags = {}
    fns_stack = []
    call_graph = {}

    def isFunction(self, node: clang.cindex.Cursor) -> Optional[str]:
        if node.kind == clang.cindex.CursorKind.FUNCTION_DECL:
            return node.spelling
        for c in node.get_children():
            if c.kind == clang.cindex.CursorKind.LAMBDA_EXPR:
                raise Exception("Lambdas unsupported")
                # return "{node.spelling}[[{c.spelling}]]"
        return None

    def isCall(self, node: clang.cindex.Cursor) -> Optional[str]:
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
        if node.kind == clang.cindex.CursorKind.ANNOTATE_ATTR:
            prefix = "COLOR::"
            if node.spelling.startswith(prefix):
                return node.spelling[len(prefix) :]
        return None

    def _explore(self, node: clang.cindex.Cursor, depth: int):
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
            self._explore(c, depth + 1)
        if fnname:
            self.fns_stack.pop()

    def explore(self):
        self._explore(self.tu.cursor, 0)
        assert len(self.fns_stack) == 0

    def toCypher(self) -> str:
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


def patternFileToCypher(pattern_filename: str) -> str:
    output = []
    pcount = 0
    with open(pattern_filename) as patternfile:
        for i, pattern in enumerate(patternfile.readlines()):
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


@click.command()
@click.argument("cpp_file")
@click.argument("pattern_file")
@click.option(
    "-c", "--clangLocation", type=Path, help="Path to libclang.so", required=True
)
def main(cpp_file: str, pattern_file: str, clanglocation: Optional[Path]):
    clang.cindex.Config.set_library_file(clanglocation)
    index = clang.cindex.Index.create()
    # TODO set compilation db if it exists
    rainbow = Rainbow(index.parse(cpp_file))
    rainbow.explore()
    print(rainbow.toCypher())
    print(patternFileToCypher(pattern_file))


if __name__ == "__main__":
    main()

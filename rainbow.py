import sys

from dataclasses import dataclass
from typing import Optional

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


clang.cindex.Config.set_library_file("/home/aneesh/llvm-project/build/lib/libclang.so")
index = clang.cindex.Index.create()
# TODO set compilation db if it exists
rainbow = Rainbow(index.parse(sys.argv[1]))
rainbow.explore()

referenced_fns = set()
for fn in rainbow.call_graph:
    if len(rainbow.call_graph[fn]) > 0:
        referenced_fns.add(fn)
        for callee in rainbow.call_graph[fn]:
            referenced_fns.add(callee)

print("CREATE")
for fn in rainbow.fns_to_tags:
    if fn not in referenced_fns:
        continue
    tags = rainbow.fns_to_tags[fn]
    tag = ""
    if len(tags):
        tag = f" :{tags[0]}"
    print(f"  ({fn}{tag}),")
for caller in rainbow.call_graph:
    for callee in rainbow.call_graph[caller]:
        print(f"  ({caller})-[:CALLs]->({callee}),")
print(" (sentinel)")
print(";")

pcount = 0
with open(sys.argv[2]) as patternfile:
    for i, pattern in enumerate(patternfile.readlines()):
        limit = 0 if i == 0 else 1
        print(
            f"OPTIONAL MATCH {pattern.strip()} WITH *, count(*) > {limit} as invalidcalls{i}"
        )
        pcount += 1
print(
    "RETURN ",
    " OR ".join([f"invalidcalls{i}" for i in range(pcount)]),
    "as invalidcalls",
)
print(";")
print("")

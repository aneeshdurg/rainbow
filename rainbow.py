import sys

from typing import Optional

import clang.cindex
clang.cindex.Config.set_library_file("/home/aneesh/llvm-project/build/lib/libclang.so")

index = clang.cindex.Index.create()
# TODO set compilation db if it exists

tu = index.parse(sys.argv[1])

fns_to_tags = {}
fns_stack = []
call_graph = {}

def isFunction(node) -> Optional[str]:
    if node.kind == clang.cindex.CursorKind.FUNCTION_DECL:
        return node.spelling
    for c in node.get_children():
        if c.kind == clang.cindex.CursorKind.LAMBDA_EXPR:
            raise Exception("Lambdas unsupported")
            return "{node.spelling}[[{c.spelling}]]"
    return None

def isCall(node) -> Optional[str]:
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

def isColor(node)->Optional[str]:
    if node.kind == clang.cindex.CursorKind.ANNOTATE_ATTR:
        prefix = "COLOR::"
        if node.spelling.startswith(prefix):
            return node.spelling[len(prefix):]
    return None

def explore(node, depth = 0):
    indent = depth * 2
    # print(" " * indent, node.kind, node.spelling, file=sys.stderr)
    fnname = isFunction(node)
    if fnname:
        if fnname not in fns_to_tags:
            fns_to_tags[fnname] = []
        if fnname not in call_graph:
            call_graph[fnname] = []
        fns_stack.append((fnname, depth))
    elif called := isCall(node):
        fn, _ = fns_stack[-1]
        call_graph[fn].append(called)
    elif color := isColor(node):
        fn, fdepth = fns_stack[-1]
        if fdepth == (depth - 1):
            fns_to_tags[fn].append(color)
    for c in node.get_children():
        explore(c, depth + 1)
    if fnname:
        fns_stack.pop()
explore(tu.cursor)
assert len(fns_stack) == 0

referenced_fns = set()
for fn in call_graph:
    if len(call_graph[fn]) > 0:
        referenced_fns.add(fn)
        for callee in call_graph[fn]:
            referenced_fns.add(callee)

print("CREATE")
for fn in fns_to_tags:
    if fn not in referenced_fns:
        continue;
    tags = fns_to_tags[fn]
    tag = ""
    if len(tags):
        tag = f" :{tags[0]}"
    print(f"  ({fn}{tag}),")
for caller in call_graph:
    for callee in call_graph[caller]:
        print(f"  ({caller})-[:CALLs]->({callee}),")
print(" (sentinel)")
print(";")
pcount = 0
with open(sys.argv[2]) as patternfile:
    for i, pattern in enumerate(patternfile.readlines()):
        limit = 0 if i == 0 else 1
        print(f"OPTIONAL MATCH {pattern.strip()} WITH *, count(*) > {limit} as invalidcalls{i}")
        pcount += 1
print("RETURN ", " OR ".join([f"invalidcalls{i}" for i in range(pcount)]), "as invalidcalls")
print(";")
print("")

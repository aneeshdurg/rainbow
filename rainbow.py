#!/usr/bin/env python3
import json
import subprocess
import sys

from dataclasses import dataclass, field, MISSING
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import click

import clang.cindex

@dataclass
class Scope:
    id_: int
    functions: Dict[str, 'Function'] = field(default_factory=dict)
    child_scopes: List['Scope'] = field(default_factory=list)
    called_functions: List[str] = field(default_factory=list)

    def empty(self):
        if len(self.functions) != 0:
            return False
        if len(self.called_functions) != 0:
            return False

        if len(self.child_scopes) == 0:
            return True
        if all([s.empty() for s in self.child_scopes]):
            return True


    def register_call(self, fnname: str):
        self.called_functions.append(fnname)

    def dump(self, level: int = 0):
        prefix = " " * (2 * level)
        print("{", self.id_)
        print(prefix, " ", "Functions")
        for f in self.functions:
            fn = self.functions[f]
            if fn.get_scope().empty() and fn.color is None:
                continue
            print(prefix, "  ", f, end=" ")
            fn.dump(level + 2)
        print(prefix, " ", "Called_functions")
        for f in self.called_functions:
            print(prefix, "   ", f)
        print(prefix, " ", "Child Scopes")
        for i, f in enumerate(self.child_scopes):
            if not f.empty():
                print(prefix, "  ", i, ":", end=" ")
                f.dump(level + 2)
        print(prefix + "}")


@dataclass
class Function:
    name: str
    color: Optional[str]
    params: Dict[str, str]
    parent_scope: Scope
    inner_scope_id: int
    inner_scope_: Scope = Scope(-1)

    def __post_init__(self):
        self.inner_scope_ = Scope(self.inner_scope_id)

    def alias(self) -> str:
        return f"{self.name}_{self.inner_scope_id}"

    def get_scope(self) -> Scope:
        return self.inner_scope_

    def dump(self, level: int):
        print("{")
        prefix = " " * (2 * level)
        print(prefix, " Color:", self.color)
        print(prefix, " Params:", self.params)
        print(prefix, " Scope:", end=" ")
        self.inner_scope_.dump(level + 1)
        print(prefix + "}")


@dataclass
class Rainbow:
    tu: clang.cindex.TranslationUnit
    prefix: str
    colors: List[str]

    _fns_to_tags: Dict[str, List[str]] = field(default_factory=dict)
    _call_graph: Dict[str, List[str]] = field(default_factory=dict)

    _global_scope: Scope = Scope(0)
    _scope_id_vendor: int = 0

    # Set of unsupported types we've already emitted warnings for
    _seen_unsupported_types: Set[clang.cindex.CursorKind] = field(default_factory=set)

    def _get_new_scope_id(self) -> int:
        self._scope_id_vendor += 1
        return self._scope_id_vendor

    def isLambda(self, node: clang.cindex.Cursor)-> bool:
        return node.kind == clang.cindex.CursorKind.LAMBDA_EXPR

    def isScope(self, node: clang.cindex.Cursor) -> bool:
        return node.kind == clang.cindex.CursorKind.COMPOUND_STMT

    def isVarDecl(self, node: clang.cindex.Cursor) -> bool:
        return node.kind == clang.cindex.CursorKind.VAR_DECL

    def isFunction(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a function definition, and if so, return the name of the function called if possible"""
        if node.kind in [clang.cindex.CursorKind.FUNCTION_DECL, clang.cindex.CursorKind.FUNCTION_TEMPLATE]:
            return node.spelling
        for c in node.get_children():
            if self.isLambda(c):
                parent = c.semantic_parent
                if self.isVarDecl(parent):
                    print("FOUND LAMBDA NAMED", parent.spelling)
                    return parent.spelling
                raise Exception("Unnamed lambda unsupported")
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

    def _process_function(self, fnname: str, node: clang.cindex.Cursor, scope: Scope):
        # TODO this should also include finding all the callable params
        # TODO Also need to do a pass verifing that all pass in params have the
        # right colors.
        params: Dict[str, str] = {}
        fn_color: Optional[str] = None
        body: Optional[clang.cindex.Cursor] = None
        if self.isLambda(node):
            parent = node.semantic_parent
            for c in parent.get_children():
                if color := self.isColor(c):
                    if fn_color is not None:
                        raise Exception(f"Multiple colors found for function {fnname}")
                    fn_color = color

        for c in node.get_children():
            if color := self.isColor(c):
                if fn_color is not None:
                    raise Exception(f"Multiple colors found for function {fnname}")
                fn_color = color
            elif c.kind == clang.cindex.CursorKind.PARM_DECL:
                param_name = c.spelling
                param_color = None
                for param_child in c.get_children():
                    if color := self.isColor(param_child):
                        if param_color is not None:
                            raise Exception(f"Multiple colors found for param {param_name} of function {fnname}")
                        param_color = color
                if param_color:
                    params[param_name] = param_color
            elif self.isScope(c):
                if body is not None:
                    raise Exception("?")
                body = c

        if fnname in scope.functions:
            fn = scope.functions[fnname]
            if fn_color and fn.color:
                if fn.color != fn_color:
                    raise Exception(f"Multiple colors found for function {fnname}")
            else:
                fn.color = fn_color

            for param_name in params:
                if param_name in fn.params:
                    if fn.params[param_name] != params[param_name]:
                        raise Exception(f"Multiple colors found for param {param_name} of function {fnname}")
                else:
                    fn.params[param_name] = params[param_name]
        else:
            scope_id = self._get_new_scope_id()
            fn = Function(fnname, fn_color, params, scope, scope_id)
            scope.functions[fnname] = fn

        # This might just be a declaration, so there might not be a function
        # body
        if body:
            self._process(body, fn.get_scope(), None);

    def isUnsupported(self, node: clang.cindex.Cursor):
        unsupported_types = [
            clang.cindex.CursorKind.CXX_METHOD,
            clang.cindex.CursorKind.StmtExpr,
        ]
        return node.kind in unsupported_types

    def _process(self, node: clang.cindex.Cursor, scope: Scope, decl_color: Optional[str]):
        if self.isUnsupported(node):
            if node.kind not in self._seen_unsupported_types:
                self._seen_unsupported_types.add(node.kind)
                print("Warning unsupported node type", node.kind, file=sys.stderr)
            return

        # TODO(aneesh) Support namespaces and namespaced functions

        if self.isScope(node):
            scope_id = self._get_new_scope_id()
            new_scope = Scope(scope_id)
            scope.child_scopes.append(new_scope)
            for c in node.get_children():
                self._process(c, new_scope, decl_color)
            return

        if fnname := self.isFunction(node):
            self._process_function(fnname, node, scope)
            return

        if called := self.isCall(node):
            scope.register_call(called)
            # TODO can lambdas shadow names of functions? This might need to also use the depth if so
            # TODO need to implement some kind of scope for the above
            #  self._call_graph[fn].append(called_fn)
            return

        for c in node.get_children():
            self._process(c, scope, decl_color)

    def process(self):
        """Process the input file and extract the call graph, and colors for every function"""
        self._process(self.tu.cursor, self._global_scope, None)

    def toCypher(self) -> str:
        """Must only be called after `self.process`.
        Outputs the call graph as an openCypher CREATE query, tagging all functions with their colors"""
        if (
            len(self._fns_to_tags) == 0
            or max(len(t) for t in self._fns_to_tags.values()) == 0
            or len(self._call_graph) == 0
            or max(len(t) for t in self._call_graph.values()) == 0
        ):
            return "// no tagged function calls\n;\n"
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
    colors = config.get("colors", [])
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
    rainbow._global_scope.dump()
    return

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

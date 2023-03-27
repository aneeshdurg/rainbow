#!/usr/bin/env python3
import json
import subprocess
import sys
from dataclasses import MISSING, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import click

import clang.cindex
from clang.cindex import CursorKind


@dataclass
class Scope:
    id_: int
    parent_scope: Optional["Scope"]
    functions: Dict[str, "Scope"] = field(default_factory=dict)
    child_scopes: List["Scope"] = field(default_factory=list)
    called_functions: List[str] = field(default_factory=list)

    # Fields that are only relevant if the Scope is a function
    name: Optional[str] = None
    color: Optional[str] = None
    params: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def create_root(cls) -> "Scope":
        return Scope(0, None)

    @classmethod
    def create_function(
        cls,
        id_: int,
        parent: "Scope",
        name: str,
        color: Optional[str],
        params: Dict[str, str],
    ) -> "Scope":
        fs = Scope(id_, parent)
        fs.name = name
        fs.color = color
        fs.params = params
        return fs

    def register_call(self, fnname: str):
        self.called_functions.append(fnname)

    def dump(self, level: int = 0):
        prefix = " " * (2 * level)
        print("{", self.id_)
        print(prefix, "  Color:", self.color)
        print(prefix, "  Params:", self.params)
        print(prefix, "  Functions")
        for f in self.functions:
            fn = self.functions[f]
            print(prefix, "  ", f, end=" ")
            fn.dump(level + 2)
        print(prefix, " ", "Called_functions")
        for f in self.called_functions:
            print(prefix, "   ", f)
        print(prefix, " ", "Child Scopes")
        for i, f in enumerate(self.child_scopes):
            print(prefix, "  ", i, ":", end=" ")
            f.dump(level + 2)
        print(prefix + "}")

    def alias(self) -> str:
        assert self.name
        return f"{self.name}__{self.id_}"

    def _scope_fns_to_cypher(self, first: bool, output: str) -> Tuple[bool, str]:
        def fn_to_cypher(fn: Scope) -> str:
            color = ""
            if fn.color:
                color = f":{fn.color}"
            return f"({fn.alias()}{color})"

        for f in self.functions:
            if not first:
                output += ",\n  "
            first = False

            fn = self.functions[f]
            output += fn_to_cypher(fn)
            first, output = fn._scope_fns_to_cypher(first, output)

        for c in self.child_scopes:
            first, output = c._scope_fns_to_cypher(first, output)
        return (first, output)

    def _calls_to_cypher(self):
        def resolve_called_functions(
            scope_stack: List[Scope], s: Scope, ret_val: List[Scope]
        ):
            for f in s.called_functions:
                defn: Optional[Scope] = None
                if f in s.functions:
                    defn = s.functions[f]
                else:
                    for rev_scope in scope_stack[::-1]:
                        if f in rev_scope.functions:
                            defn = rev_scope.functions[f]
                            break
                if not defn:
                    # print("COULD NOT RESOLVE", f)
                    continue
                ret_val.append(defn)
                # defn.dump(0)
            for cs in s.child_scopes:
                scope_stack.append(cs)
                resolve_called_functions(scope_stack, cs, ret_val)
                scope_stack.pop()

        def scope_calls_to_cypher(scope: Scope, fn: Scope, output: str) -> str:
            called = []
            resolve_called_functions([scope], fn, called)
            for c in called:
                output += ",\n  "
                output += f"({fn.alias()}) -[:CALLS]-> ({c.alias()})"
            return output

        output = ""
        for f in self.functions:
            fn = self.functions[f]
            output = scope_calls_to_cypher(self, fn, output)
        return output

    def toCypher(self) -> str:
        """Must only be called after `self.process`.
        Outputs the call graph as an openCypher CREATE query, tagging all functions with their colors"""

        _, output = self._scope_fns_to_cypher(True, "")
        output += self._calls_to_cypher()
        return "CREATE " + output


@dataclass
class Rainbow:
    tu: clang.cindex.TranslationUnit
    prefix: str
    colors: List[str]

    _fns_to_tags: Dict[str, List[str]] = field(default_factory=dict)
    _call_graph: Dict[str, List[str]] = field(default_factory=dict)

    _global_scope: Scope = Scope.create_root()
    _scope_id_vendor: int = 0

    # Set of unsupported types we've already emitted warnings for
    _seen_unsupported_types: Set[CursorKind] = field(default_factory=set)

    def _get_new_scope_id(self) -> int:
        self._scope_id_vendor += 1
        return self._scope_id_vendor

    def isLambda(self, kind: CursorKind) -> bool:
        return kind == CursorKind.LAMBDA_EXPR

    def isScope(self, kind: CursorKind) -> bool:
        return kind == CursorKind.COMPOUND_STMT

    def isVarDecl(self, kind: CursorKind) -> bool:
        return kind == CursorKind.VAR_DECL

    def isFunction(self, node: clang.cindex.Cursor, kind: CursorKind) -> Optional[str]:
        """Determine if `node` is a function definition, and if so, return the name of the function called if possible"""
        if kind in [CursorKind.FUNCTION_DECL, CursorKind.FUNCTION_TEMPLATE]:
            return node.spelling
        if self.isLambda(kind):
            parent = node.semantic_parent
            if self.isVarDecl(parent.kind):
                return parent.spelling
            raise Exception("Unnamed lambda unsupported")
        return None

    def isCall(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a function call, and if so, return the name of the function called if possible"""
        if node.kind != CursorKind.CALL_EXPR:
            return None
        if (spelling := node.spelling) != "operator()":
            return spelling

        for c in node.get_children():
            if c.kind == CursorKind.UNEXPOSED_EXPR:
                if c.spelling == "operator()":
                    continue
                # We mangaled lambda names - need to track lambdas better
                return c.spelling
        return None

    def isColor(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a tag defining a color"""
        if node.kind == CursorKind.ANNOTATE_ATTR:
            if node.spelling.startswith(self.prefix):
                color = node.spelling[len(self.prefix) :]
                if color not in self.colors:
                    raise Exception(f"Found unknown color {color}")
                return color
        return None

    def isUnsupported(self, kind: CursorKind):
        unsupported_types = [
            CursorKind.CLASS_TEMPLATE,
            CursorKind.CONVERSION_FUNCTION,
            CursorKind.CXX_METHOD,
            CursorKind.FUNCTION_TEMPLATE,
            CursorKind.StmtExpr,
        ]
        return kind in unsupported_types

    def isSkipped(self, kind: CursorKind):
        skipped_types = set(
            [
                CursorKind.ALIGNED_ATTR,
                CursorKind.ASM_LABEL_ATTR,
                CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
                CursorKind.CONSTRUCTOR,
                CursorKind.CONST_ATTR,
                CursorKind.DEFAULT_STMT,
                CursorKind.DESTRUCTOR,
                CursorKind.ENUM_CONSTANT_DECL,
                CursorKind.ENUM_DECL,
                CursorKind.FLOATING_LITERAL,
                CursorKind.INTEGER_LITERAL,
                CursorKind.NULL_STMT,
                CursorKind.PURE_ATTR,
                CursorKind.SIZE_OF_PACK_EXPR,
                CursorKind.STRING_LITERAL,
                CursorKind.TYPEDEF_DECL,
                CursorKind.TYPE_ALIAS_DECL,
                CursorKind.TYPE_ALIAS_TEMPLATE_DECL,
                CursorKind.UNEXPOSED_ATTR,
                CursorKind.UNEXPOSED_DECL,
                CursorKind.UNION_DECL,
                CursorKind.USING_DIRECTIVE,
                CursorKind.VISIBILITY_ATTR,
                CursorKind.WARN_UNUSED_RESULT_ATTR,
            ]
        )
        return kind in skipped_types

    def _process_function(
        self, fnname: str, node: clang.cindex.Cursor, scope: Scope
    ) -> Tuple[Optional[clang.cindex.Cursor], Scope]:
        # TODO this should also include finding all the callable params
        # TODO Also need to do a pass verifing that all pass in params have the
        # right colors.
        params: Dict[str, str] = {}
        fn_color: Optional[str] = None
        body: Optional[clang.cindex.Cursor] = None
        if self.isLambda(node.kind):
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
            elif c.kind == CursorKind.PARM_DECL:
                param_name = c.spelling
                param_color = None
                for param_child in c.get_children():
                    if color := self.isColor(param_child):
                        if param_color is not None:
                            raise Exception(
                                f"Multiple colors found for param {param_name} of function {fnname}"
                            )
                        param_color = color
                if param_color:
                    params[param_name] = param_color
            elif self.isScope(c.kind):
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
                        raise Exception(
                            f"Multiple colors found for param {param_name} of function {fnname}"
                        )
                else:
                    fn.params[param_name] = params[param_name]
        else:
            scope_id = self._get_new_scope_id()
            fn = Scope.create_function(scope_id, scope, fnname, fn_color, params)
            scope.functions[fnname] = fn

        # This might just be a declaration, so there might not be a function
        # body
        return (body, fn)

    def _append_to_frontier(
        self,
        node: clang.cindex.Cursor,
        scope: Scope,
        frontier: List[Tuple[clang.cindex.Cursor, Scope]],
    ):
        for c in list(node.get_children())[::-1]:
            frontier.append((c, scope))

    def _process(self, root: clang.cindex.Cursor, r_scope: Scope):
        frontier = [(root, r_scope)]
        while len(frontier) > 0:
            node, scope = frontier.pop()
            kind = node.kind
            if self.isUnsupported(kind):
                if kind not in self._seen_unsupported_types:
                    self._seen_unsupported_types.add(kind)
                    print("Warning unsupported node type", kind, file=sys.stderr)
                continue

            if self.isSkipped(kind):
                continue

            # TODO(aneesh) Support namespaces and namespaced functions

            # TODO - Are scopes not enough to resolve fn calls, do we also need line
            # numbers to handle shadowing?
            if self.isScope(kind):
                scope_id = self._get_new_scope_id()
                new_scope = Scope(scope_id, scope)
                scope.child_scopes.append(new_scope)
                self._append_to_frontier(node, new_scope, frontier)
                continue

            if fnname := self.isFunction(node, kind):
                fn_body, fn = self._process_function(fnname, node, scope)
                if fn_body:
                    self._append_to_frontier(fn_body, fn, frontier)
                continue

            if called := self.isCall(node):
                scope.register_call(called)
                continue

            self._append_to_frontier(node, scope, frontier)

    def process(self) -> Scope:
        """Process the input file and extract the call graph, and colors for every function"""
        self._process(self.tu.cursor, self._global_scope)
        return self._global_scope


def patternsToCypher(patterns: List[str]) -> List[str]:
    """Given a list of `patterns` output a cypher query combining them all"""
    output = []
    for pattern in patterns:
        output.append(f"MATCH {pattern.strip()} RETURN count(*) > 0 as invalidcalls\n;")
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
    tu = index.parse(cpp_file)
    # TODO set compilation db if it exists
    rainbow = Rainbow(tu, prefix, colors)
    scope = rainbow.process()

    create_query = scope.toCypher()
    validate_queries = patternsToCypher(patterns)
    validate_query = "\n".join(validate_queries)

    executor = config.get("executor", "executors/neo4j_adapter.py")
    p = subprocess.Popen(
        [executor, config_file], stdout=subprocess.PIPE, stdin=subprocess.PIPE
    )
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
    import os

    if "RAINBOW_PROFILE" in os.environ:
        import cProfile

        cProfile.run("main()")
        sys.exit(0)
    main()

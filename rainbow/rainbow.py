#!/usr/bin/env python3
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import clang.cindex
import click
from clang.cindex import CursorKind, Diagnostic

import rainbow.errors as errors
from rainbow.config import Config
from rainbow.scope import Scope


@dataclass
class Rainbow:
    tu: clang.cindex.TranslationUnit
    config: Config

    _global_scope: Scope = field(default_factory=Scope.create_root)
    _scope_id_vendor: int = 0

    # Set of unsupported types we've already emitted warnings for
    _seen_unsupported_types: Set[CursorKind] = field(default_factory=set)

    logger: logging.Logger = field(default_factory=lambda: logging.Logger("rainbow"))

    _hash_to_scope: Dict[int, Scope] = field(default_factory=dict)

    def _get_new_scope_id(self) -> int:
        self._scope_id_vendor += 1
        return self._scope_id_vendor

    def is_lambda(
        self, node: clang.cindex.Cursor, kind: CursorKind
    ) -> Optional[clang.cindex.Cursor]:
        if kind == CursorKind.LAMBDA_EXPR:
            return node
        if kind == CursorKind.UNEXPOSED_EXPR:
            # This is not needed in clang-16+, but that's not released yet.
            children = list(node.get_children())
            if len(children) != 1:
                return None
            if children[0].kind != CursorKind.CALL_EXPR:
                return None
            children = list(children[0].get_children())
            if len(children) != 1:
                return None
            if children[0].kind != CursorKind.UNEXPOSED_EXPR:
                return None
            children = list(children[0].get_children())
            if len(children) != 1:
                return None
            if children[0].kind != CursorKind.LAMBDA_EXPR:
                return None
            return children[0]

    def is_scope(self, kind: CursorKind) -> bool:
        return kind == CursorKind.COMPOUND_STMT

    def is_var_decl(self, kind: CursorKind) -> bool:
        return kind == CursorKind.VAR_DECL

    def is_assignment(
        self, node: clang.cindex.Cursor, kind: CursorKind
    ) -> Optional[Tuple[clang.cindex.Cursor, clang.cindex.Cursor]]:
        if kind == CursorKind.BINARY_OPERATOR:
            children = list(node.get_children())
            left_child_tokens = list(children[0].get_tokens())
            op_offset = len(left_child_tokens)

            # Get the token at op_offset
            op = None
            for _, token in zip(range(op_offset + 1), node.get_tokens()):
                op = token
            assert op

            if op.spelling == "=":
                return (children[0], children[1])
            return None
        return None

    def is_function(self, node: clang.cindex.Cursor, kind: CursorKind) -> Optional[Tuple[str, int]]:
        """Determine if `node` is a function definition, and if so, return the name of the function called if possible"""
        if kind in [CursorKind.FUNCTION_DECL, CursorKind.FUNCTION_TEMPLATE]:
            hash_ = node.hash
            if defn := node.get_definition():
                hash_ = defn.hash
            return node.spelling, hash_
        if self.is_lambda(node, kind):
            if not node.semantic_parent:
                return None
            parent = node.semantic_parent
            if self.is_var_decl(parent.kind):
                return (parent.spelling, parent.hash)
            raise Exception("Unnamed lambda unsupported")
        return None

    def is_call(self, node: clang.cindex.Cursor) -> Optional[Tuple[str, int]]:
        """Determine if `node` is a function call, and if so, return the name of the function called if possible"""
        if node.kind != CursorKind.CALL_EXPR:
            return None
        if (spelling := node.spelling) != "operator()":
            return spelling, node.hash

        for c in node.get_children():
            if c.kind == CursorKind.UNEXPOSED_EXPR:
                if c.spelling == "operator()":
                    continue
                return c.spelling, c.referenced.hash
        return None

    def is_color(self, node: clang.cindex.Cursor) -> Optional[str]:
        """Determine if `node` is a tag defining a color"""
        if node.kind == CursorKind.ANNOTATE_ATTR:
            if node.spelling.startswith(self.config.prefix):
                color = node.spelling[len(self.config.prefix) :]
                if color not in self.config.colors:
                    raise Exception(f"Found unknown color {color}")
                return color
        return None

    def is_unsupported(self, kind: CursorKind):
        unsupported_types = [
            CursorKind.CLASS_TEMPLATE,
            CursorKind.CONVERSION_FUNCTION,
            CursorKind.CXX_METHOD,
            CursorKind.FUNCTION_TEMPLATE,
            CursorKind.StmtExpr,
        ]
        return kind in unsupported_types

    def is_skipped(self, kind: CursorKind):
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
                CursorKind.TEMPLATE_TYPE_PARAMETER,
                CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
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

    def _process_alias_function(
        self, scope: Scope, alias: str, original_name: str
    ) -> bool:
        if resolved := scope.resolve_function(original_name):
            scope_id = self._get_new_scope_id()
            Scope.create_function(
                scope_id,
                scope,
                alias,
                resolved.color,
                resolved.params_to_colors,
            )
            return True
        return False

    def _process_alias_decl(self, node: clang.cindex.Cursor, scope: Scope) -> bool:
        children = list(node.get_children())
        if len(children) == 1:
            child = children[0]
            if child.kind == CursorKind.UNEXPOSED_EXPR:
                children = list(child.get_children())
                if len(children) == 1:
                    child = children[0]
                    if child.kind == CursorKind.DECL_REF_EXPR:
                        return self._process_alias_function(
                            scope, node.spelling, child.spelling
                        )
        return False

    def _process_alias_assign(
        self, lhs: clang.cindex.Cursor, rhs: clang.cindex.Cursor, scope: Scope
    ) -> bool:
        if lhs.kind != CursorKind.DECL_REF_EXPR:
            return False

        if rhs.kind == CursorKind.UNEXPOSED_EXPR:
            children = list(rhs.get_children())
            if len(children) == 1:
                child = children[0]
                if child.kind == CursorKind.DECL_REF_EXPR:
                    # Check that the left hand side is already defined with the
                    # same color as the right hand side - we know lhs_fn and
                    # rhs_fn must exist because if they didn't, this source file
                    # wouldn't have type checked.
                    lhs_fn = scope.resolve_function(lhs.spelling)
                    assert lhs_fn
                    rhs_fn = scope.resolve_function(child.spelling)
                    assert rhs_fn
                    if (
                        lhs_fn.color != rhs_fn.color
                        or lhs_fn.params_to_colors != rhs_fn.params_to_colors
                    ):
                        raise errors.InvalidAssignmentError(
                            lhs.location,
                            lhs.spelling,
                            lhs_fn.color,
                            rhs_fn.color,
                        )

                    return self._process_alias_function(
                        scope, lhs.spelling, child.spelling
                    )
        return False

    def _process_function(
        self, fnname: str, node: clang.cindex.Cursor, scope: Scope
    ) -> Tuple[Optional[clang.cindex.Cursor], Scope]:
        # TODO this should also include finding all the callable params
        # TODO Also need to do a pass verifing that all pass in params have the
        # right colors.
        params_to_colors: Dict[str, Optional[str]] = {}
        fn_color: Optional[str] = None
        body: Optional[clang.cindex.Cursor] = None
        if lambda_node := self.is_lambda(node, node.kind):
            parent = node.semantic_parent
            for c in parent.get_children():
                if color := self.is_color(c):
                    if fn_color is not None:
                        raise Exception(f"Multiple colors found for function {fnname}")
                    fn_color = color
            node = lambda_node

        for c in node.get_children():
            if color := self.is_color(c):
                if fn_color is not None:
                    raise Exception(f"Multiple colors found for function {fnname}")
                fn_color = color
            elif c.kind == CursorKind.PARM_DECL:
                param_name = c.spelling
                param_color = None
                for param_child in c.get_children():
                    if color := self.is_color(param_child):
                        if param_color is not None:
                            raise Exception(
                                f"Multiple colors found for param {param_name} of function {fnname}"
                            )
                        param_color = color
                if param_color:
                    # TODO
                    raise Exception(f"COLORED PARAMETER UNSUPPORTED")
                scope_id = self._get_new_scope_id()
                params_to_colors[param_name] = param_color
            elif self.is_scope(c.kind):
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

            for param_name, param_color in params_to_colors.items():
                if param_name in fn.params:
                    if fn.params[param_name].color != param_color:
                        raise Exception(
                            f"Multiple colors found for param {param_name} of function {fnname}"
                        )
                else:
                    raise Exception(
                        f"Mismatched parameter names for {fn.name}! {list(fn.params.keys())} vs {list(params_to_colors.keys())}"
                    )
        else:
            scope_id = self._get_new_scope_id()
            fn = Scope.create_function(
                scope_id, scope, fnname, fn_color, params_to_colors
            )

        # This might just be a declaration, so there might not be a function
        # body
        return (body, fn)

    def _process(self, root: clang.cindex.Cursor, r_scope: Scope):
        frontier = [(root, r_scope)]
        while len(frontier) > 0:
            node, scope = frontier.pop(0)
            kind = node.kind
            if self.is_unsupported(kind):
                if kind not in self._seen_unsupported_types:
                    self._seen_unsupported_types.add(kind)
                    self.logger.warning("unsupported node type %s" % kind)
                continue

            if self.is_skipped(kind):
                continue

            # TODO(aneesh) Support namespaces and namespaced functions

            # TODO - Are scopes not enough to resolve fn calls, do we also need line
            # numbers to handle shadowing?
            if self.is_scope(kind):
                scope_id = self._get_new_scope_id()
                new_scope = Scope(scope_id, scope)
                scope.child_scopes.append(new_scope)
                frontier = [(c, new_scope) for c in node.get_children()] + frontier
                continue

            if result := self.is_function(node, kind):
                fnname, hash_ = result
                fn_body, fn = self._process_function(fnname, node, scope)
                if fn_body:
                    frontier = [(c, fn) for c in fn_body.get_children()] + frontier
                self._hash_to_scope[hash_] = fn
                continue

            if self.is_var_decl(kind):
                if self._process_alias_decl(node, scope):
                    continue

            if operands := self.is_assignment(node, kind):
                lhs, rhs = operands
                if self._process_alias_assign(lhs, rhs, scope):
                    continue

            if called := self.is_call(node):
                fnname, hash_ = called
                try:
                    fn = self._hash_to_scope[hash_]
                except KeyError:
                    # fall back to name based resolution
                    try:
                        fn = scope.resolve_function(fnname)
                    except errors.FunctionResolutionError:
                        self.logger.warning("Could not resolve function call %s" % fnname)
                        continue
                assert fn
                scope.register_call_scope(fn)

            frontier = [(c, scope) for c in node.get_children()] + frontier

    def process(self) -> Scope:
        """Process the input file and extract the call graph, and colors for every function"""
        error_count = 0
        for diag in self.tu.diagnostics:
            if diag.severity == Diagnostic.Warning:
                self.logger.warning("Found warning diagnostic: %s" % diag.spelling)
            elif diag.severity == Diagnostic.Error:
                error_count += 1
                self.logger.warning("Found error diagnostic: %s" % diag.spelling)
        if error_count > 0:
            raise errors.CPPSyntaxErrors()

        self._process(self.tu.cursor, self._global_scope)
        return self._global_scope

    def should_reject(self) -> Optional[bool]:
        return self.config.run(self._global_scope)

    def run(self) -> Optional[bool]:
        """Returns True if the program should be rejected, False if it should be
        accepted, and None if the validity was not reported"""
        self.process()
        return self.should_reject()


@click.command(help="rainbow - arbitrary function coloring for c++!")
@click.argument("cpp_file")
@click.argument("config_file")
@click.option("-c", "--clangLocation", type=Path, help="Path to libclang.so")
def main(cpp_file: str, config_file: str, clanglocation: Optional[Path]):
    if not clanglocation:
        clanglocation = Path("/usr/lib/x86_64-linux-gnu/libclang-15.so.1")
    clang.cindex.Config.set_library_file(clanglocation)

    config = Config.from_json(Path(config_file))

    index = clang.cindex.Index.create()
    tu = index.parse(cpp_file)
    # TODO set compilation db if it exists
    rainbow = Rainbow(tu, config)
    try:
        found_invalid = rainbow.run()
    except Exception as e:
        rainbow.logger.error(str(e))
        sys.exit(1)

    if found_invalid is None:
        invalidcalls = "UNKNOWN"
        exitcode = 2
    else:
        invalidcalls = found_invalid
        exitcode = int(found_invalid)
    print("program is invalid:", invalidcalls, file=sys.stderr)
    sys.exit(exitcode)

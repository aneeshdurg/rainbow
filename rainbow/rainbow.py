#!/usr/bin/env python3
import logging
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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

    _frontier: List[Tuple[clang.cindex.Cursor, Scope]] = field(default_factory=list)

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
            if not op:
                return None

            if op.spelling == "=":
                return (children[0], children[1])
            return None
        return None

    def is_function(
        self, node: clang.cindex.Cursor, kind: CursorKind
    ) -> Optional[Tuple[str, int]]:
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
                    raise errors.UnknownColorError(node.location, color)
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
                CursorKind.UNION_DECL,
                CursorKind.USING_DIRECTIVE,
                CursorKind.VISIBILITY_ATTR,
                CursorKind.WARN_UNUSED_RESULT_ATTR,
            ]
        )
        return kind in skipped_types

    def _process_alias_function(
        self,
        scope: Scope,
        loc: clang.cindex.SourceLocation,
        alias: str,
        color: Optional[str],
        original_fn_node: clang.cindex.Cursor,
        original_name: str,
    ) -> bool:
        resolved = self._hash_to_scope.get(original_fn_node.hash)
        if not resolved:
            resolved = scope.resolve_function(original_name)

        if resolved is None:
            return False

        if resolved.color != color:
            raise errors.InvalidAssignmentError(loc, alias, color, resolved.color)

        scope_id = self._get_new_scope_id()
        Scope.create_function(
            scope_id,
            scope,
            alias,
            resolved.color,
            resolved.params_to_colors,
        )
        return True

    def _process_alias_decl(self, node: clang.cindex.Cursor, scope: Scope) -> bool:
        children = list(node.get_children())

        color = None
        for c in children[:-1]:
            if child_color := self.is_color(c):
                assert color is None
                color = child_color

        child = children[-1]
        kind = child.kind
        if kind == CursorKind.UNEXPOSED_EXPR:
            children = list(child.get_children())
            if len(children) == 1:
                child = children[0]
                if child.kind == CursorKind.DECL_REF_EXPR:
                    return self._process_alias_function(
                        scope,
                        node.location,
                        node.spelling,
                        color,
                        child.referenced,
                        child.spelling,
                    )
        elif kind == CursorKind.CALL_EXPR:
            if child.spelling == "":
                children = list(child.get_children())
                if len(children) == 1:
                    child = children[0]
                    if child.kind == CursorKind.UNEXPOSED_EXPR:
                        children = list(child.get_children())
                        if len(children) == 1:
                            child = children[0]
                            if child.kind == CursorKind.DECL_REF_EXPR:
                                return self._process_alias_function(
                                    scope,
                                    node.location,
                                    node.spelling,
                                    color,
                                    child.referenced,
                                    child.spelling,
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
                        scope,
                        lhs.location,
                        lhs.spelling,
                        lhs_fn.color,
                        child.referenced,
                        child.spelling,
                    )
        return False

    def _process_function(
        self, fnname: str, hash_: int, node: clang.cindex.Cursor, scope: Scope
    ) -> Tuple[Optional[clang.cindex.Cursor], Scope]:
        # TODO Also need to do a pass verifing that all passed in params have
        # the right colors.
        params_to_colors: Dict[str, Optional[str]] = {}
        fn_color: Optional[str] = None
        body: Optional[clang.cindex.Cursor] = None
        if lambda_node := self.is_lambda(node, node.kind):
            parent = node.semantic_parent
            if parent:
                for c in parent.get_children():
                    if color := self.is_color(c):
                        if fn_color is not None:
                            raise Exception(
                                f"Multiple colors found for function {fnname}"
                            )
                        fn_color = color
            node = lambda_node

        for c in node.get_children():
            if color := self.is_color(c):
                if fn_color is not None:
                    raise Exception(f"Multiple colors found for function {fnname}")
                fn_color = color
            elif c.kind == CursorKind.PARM_DECL:
                param_name = c.spelling
                if not param_name:
                    param_name = f"!unnamed_param{len(params_to_colors)}"
                param_color = None
                for param_child in c.get_children():
                    if color := self.is_color(param_child):
                        if param_color is not None:
                            raise Exception(
                                f"Multiple colors found for param {param_name} of function {fnname}"
                            )
                        param_color = color
                scope_id = self._get_new_scope_id()
                params_to_colors[param_name] = param_color
            elif self.is_scope(c.kind):
                if body is not None:
                    raise Exception("?")
                body = c

        if fn := self._hash_to_scope.get(hash_):
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
            self._hash_to_scope[hash_] = fn

        # This might just be a declaration, so there might not be a function
        # body
        return (body, fn)

    def _is_fn_param(self, scope: Scope, param: clang.cindex.Cursor) -> Optional[Scope]:
        if not param.kind == CursorKind.UNEXPOSED_EXPR:
            return None
        children = list(param.get_children())
        if len(children) != 1:
            return None
        child = children[0]

        if not child.kind == CursorKind.CALL_EXPR:
            return None
        if child.spelling != "":
            return None
        children = list(child.get_children())
        if len(children) != 1:
            return None
        child = children[0]

        if not child.kind == CursorKind.UNEXPOSED_EXPR:
            return None
        children = list(child.get_children())
        if len(children) != 1:
            return None
        child = children[0]

        if not child.kind == CursorKind.UNEXPOSED_EXPR:
            return None
        children = list(child.get_children())
        if len(children) != 1:
            return None
        child = children[0]

        if not child.kind == CursorKind.UNEXPOSED_EXPR:
            return None
        children = list(child.get_children())
        if len(children) != 1:
            return None
        child = children[0]

        if not child.kind == CursorKind.CALL_EXPR:
            return None
        if child.spelling != "function":
            return None
        children = list(child.get_children())
        if len(children) != 1:
            return None
        child = children[0]

        if child.kind == CursorKind.DECL_REF_EXPR:
            if child.referenced.hash not in self._hash_to_scope:
                try:
                    if fn := scope.resolve_function(child.spelling):
                        return fn
                except errors.FunctionResolutionError:
                    pass
                self.logger.warning(
                    f"Found functional parameter {child.spelling}, but could not lookup defn"
                )
                return None
            return self._hash_to_scope[child.referenced.hash]
        elif child.kind == CursorKind.UNEXPOSED_EXPR:
            # We might have an anonymous lambda passed in as a parameter - treat
            # it as an uncolored functions, but parse function calls within
            # TODO - just register this as a function
            children = list(child.get_children())
            if len(children) == 1:
                child = children[0]
                if child.kind == CursorKind.LAMBDA_EXPR:
                    fn_body, fn = self._process_function(
                        f"!unnamed_lambda{len(scope.functions)}",
                        child.hash,
                        child,
                        scope,
                    )
                    assert fn_body is not None
                    self._frontier = [
                        (c, fn) for c in fn_body.get_children()
                    ] + self._frontier
                    return fn
            return None

    def _process(self, root: clang.cindex.Cursor, r_scope: Scope):
        self._frontier = [(root, r_scope)]
        while len(self._frontier) > 0:
            node, scope = self._frontier.pop(0)
            kind = node.kind
            if self.is_unsupported(kind):
                if kind not in self._seen_unsupported_types:
                    self._seen_unsupported_types.add(kind)
                    self.logger.warning("unsupported node type %s" % kind)
                continue

            if self.is_skipped(kind):
                continue

            # TODO(aneesh) Support namespaces and namespaced functions

            if self.is_scope(kind):
                scope_id = self._get_new_scope_id()
                new_scope = Scope(scope_id, scope)
                scope.child_scopes.append(new_scope)
                self._frontier = [
                    (c, new_scope) for c in node.get_children()
                ] + self._frontier
                continue

            if result := self.is_function(node, kind):
                fnname, hash_ = result
                fn_body, fn = self._process_function(fnname, hash_, node, scope)
                if fn_body:
                    self._frontier = [
                        (c, fn) for c in fn_body.get_children()
                    ] + self._frontier
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
                        fn = None
                if fn:
                    scope.register_call_scope(fn)
                    params = list(node.get_children())[1:]
                    if (
                        len(params)
                        and params[0].kind == CursorKind.UNEXPOSED_EXPR
                        and params[0].spelling == "operator()"
                    ):
                        params = params[1:]
                    if len(params) != len(fn.params):
                        self.logger.warn(
                            f"Could not verify parameters passed into {fn.name} @ {node.location}"
                        )
                    else:
                        for i, c, param_scope in zip(
                            range(len(params)), params, fn.params.values()
                        ):
                            if param := self._is_fn_param(scope, c):
                                if param_scope.color:
                                    if (
                                        param.color is not None
                                        and param.color != param_scope.color
                                    ):
                                        raise errors.InvalidAssignmentError(
                                            node.location,
                                            f"(Parameter {i} of {fnname})",
                                            param_scope.color,
                                            param.color,
                                        )
                                param_scope.register_call_scope(param)
                            else:
                                assert (
                                    param_scope.color is None
                                ), f"{param_scope.name}, {param_scope.color}"
                                continue

                else:
                    if fnname == "":
                        fnname = "`???`"
                    self.logger.warning("Could not resolve function call %s" % fnname)
            self._frontier = [(c, scope) for c in node.get_children()] + self._frontier

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
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be supplied multiple times)",
)
@click.option("-q", "--quiet", is_flag=True, help="Suppress output")
def main(
    cpp_file: str,
    config_file: str,
    clanglocation: Optional[Path],
    verbose: int,
    quiet: bool,
):
    if not clanglocation:
        clanglocation = Path("/usr/lib/x86_64-linux-gnu/libclang-15.so.1")
    clang.cindex.Config.set_library_file(clanglocation)

    if quiet and verbose > 0:
        print("--quiet and --verbose cannot be supplied together", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.NOTSET)
    logger = logging.getLogger("rainbow")
    verbosity_map = {
        -1: logging.CRITICAL,
        0: logging.ERROR,
        1: logging.WARNING,
        2: logging.INFO,
        3: logging.DEBUG,
    }
    logger.setLevel(verbosity_map[min(verbose if not quiet else -1, 3)])

    if verbose < 3:
        warnings.filterwarnings("ignore")

    config = Config.from_json(Path(config_file), logger=logger)

    index = clang.cindex.Index.create()
    tu = index.parse(cpp_file)
    # TODO set compilation db if it exists
    rainbow = Rainbow(tu, config, logger=logger)
    try:
        found_invalid = rainbow.run()
    except Exception as e:
        rainbow.logger.error(str(e))
        raise e
        sys.exit(1)

    if found_invalid is None:
        invalidcalls = "UNKNOWN"
        exitcode = 2
    else:
        invalidcalls = found_invalid
        exitcode = int(found_invalid)
    logger.info(f"program is invalid: {invalidcalls}")
    sys.exit(exitcode)

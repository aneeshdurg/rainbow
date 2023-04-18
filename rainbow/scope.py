#!/usr/bin/env python3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from rainbow.errors import FunctionResolutionError


@dataclass
class Scope:
    id_: int
    parent_scope: Optional["Scope"]
    functions: Dict[str, "Scope"] = field(default_factory=dict)
    child_scopes: List["Scope"] = field(default_factory=list)
    called_functions: List["Scope"] = field(default_factory=list)

    # Fields that are only relevant if the Scope is a function
    name: Optional[str] = None
    color: Optional[str] = None
    params_to_colors: Dict[str, Optional[str]] = field(default_factory=dict)
    is_param: bool = False

    params: Dict[str, "Scope"] = field(init=False)

    def __post_init__(self):
        params = {}
        for param, pcolor in self.params_to_colors.items():
            params[param] = Scope.create_param(self.id_, self, param, pcolor)
        self.params = params

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
        params: Dict[str, Optional[str]],
    ) -> "Scope":
        fs = Scope(id_, parent, name=name, color=color, params_to_colors=params)
        parent.functions[name] = fs
        return fs

    @classmethod
    def create_param(
        cls, id_: int, parent: "Scope", name: str, color: Optional[str]
    ) -> "Scope":
        return Scope(id_, parent, name=name, color=color, is_param=True)

    def register_call_scope(self, fn: "Scope"):
        self.called_functions.append(fn)

    def register_call(self, fnname: str):
        resolved = self.resolve_function(fnname)
        if resolved is None:
            raise FunctionResolutionError()
        self.called_functions.append(resolved)

    def dump(self, level: int = 0):
        prefix = " " * (2 * level)
        print("{", self.id_)
        print(prefix, "  Color:", self.color)
        print(prefix, "  Params:")
        for param, pscope in self.params.items():
            print(prefix, f"  {param}:", end=" ")
            pscope.dump(level + 2)
        print(prefix, "  Functions")
        for f in self.functions:
            fn = self.functions[f]
            print(prefix, "  ", f, end=" ")
            fn.dump(level + 2)
        print(prefix, " ", "Called_functions")
        for f in self.called_functions:
            print(prefix, "   ", f.name)
        print(prefix, " ", "Child Scopes")
        for i, f in enumerate(self.child_scopes):
            print(prefix, "  ", i, ":", end=" ")
            f.dump(level + 2)
        print(prefix + "}")

    def alias(self) -> str:
        assert self.name
        if self.is_param:
            assert self.parent_scope
            return self.parent_scope._get_param_alias(self.name)
        return f"`{self.name}__{self.id_}`"

    def _get_param_alias(self, name: str) -> str:
        assert self.name
        return f"`{name}__param__{self.name}__{self.id_}`"

    def _scope_fns_to_cypher(self, first: bool, output: str) -> Tuple[bool, str]:
        def fn_to_cypher(fn: Scope) -> str:
            def cypher_node(alias, name, color) -> str:
                color_str = f":{color}" if color else ""
                return f"({alias}{color_str} {{name: '{name}'}})"

            output = cypher_node(fn.alias(), fn.name, fn.color)
            for param, param_scope in fn.params.items():
                if not param:
                    continue
                output += ", "
                output += fn_to_cypher(param_scope)
            return output

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

    def resolve_function(self, fnname: str) -> Optional["Scope"]:
        if self.name and self.name == fnname:
            return self

        if fnname in self.functions:
            return self.functions[fnname]

        if fnname in self.params:
            return self.params[fnname]

        if not self.parent_scope:
            return None
        return self.parent_scope.resolve_function(fnname)

    def _calls_to_cypher(self):
        def resolve_called_functions(s: Scope, ret_val: List[Scope]):
            ret_val += s.called_functions
            for cs in s.child_scopes:
                resolve_called_functions(cs, ret_val)

        def scope_calls_to_cypher(fn: Scope, output: str) -> str:
            called = []
            resolve_called_functions(fn, called)
            for c in called:
                output += ",\n  "
                output += f"({fn.alias()}) -[:CALLS]-> ({c.alias()})"
            for child_fn in fn.functions:
                fn_scope = fn.functions[child_fn]
                output = scope_calls_to_cypher(fn_scope, output)
            return output

        def scope_functions_to_cypher(scope: Scope, output: str) -> str:
            for fn_def in scope.functions.values():
                output = scope_calls_to_cypher(fn_def, output)
                output = scope_functions_to_cypher(fn_def, output)
            for child_scope in scope.child_scopes:
                output = scope_functions_to_cypher(child_scope, output)
            return output

        output = ""
        for fn in self.functions.values():
            output = scope_calls_to_cypher(fn, output)
            output = scope_functions_to_cypher(fn, output)
        return output

    def to_cypher(self) -> str:
        """Must only be called after `self.process`.
        Outputs the call graph as an openCypher CREATE query, tagging all functions with their colors"""

        _, output = self._scope_fns_to_cypher(True, "")
        output += self._calls_to_cypher()
        if output == "":
            return "RETURN 0"
        return "CREATE " + output

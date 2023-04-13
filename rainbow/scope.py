#!/usr/bin/env python3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


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
        return f"`{self.name}__{self.id_}`"

    def _scope_fns_to_cypher(self, first: bool, output: str) -> Tuple[bool, str]:
        def fn_to_cypher(fn: Scope) -> str:
            color = ""
            if fn.color:
                color = f":{fn.color}"
            return f"({fn.alias()}{color} {{name: '{fn.name}'}})"

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
        if fnname in self.functions:
            return self.functions[fnname]

        if fnname in self.params:
            return Scope.create_function(-2, self, fnname, self.params[fnname], {})

        if not self.parent_scope:
            return None
        return self.parent_scope.resolve_function(fnname)

    def _calls_to_cypher(self):
        def resolve_called_functions(s: Scope, ret_val: List[Scope]):
            for f in s.called_functions:
                defn = s.resolve_function(f)
                if not defn:
                    continue
                ret_val.append(defn)
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
        return "CREATE " + output + "\n;"

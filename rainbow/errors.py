from typing import Optional

import clang.cindex


class CPPSyntaxErrors(Exception):
    def __init__(self):
        super().__init__("Detected syntax errors in source")


class InvalidAssignmentError(Exception):
    def __init__(
        self,
        loc: clang.cindex.SourceLocation,
        var_name: str,
        color: Optional[str],
        new_color: Optional[str],
    ):
        msg = (
            f"Invalid assignment to {var_name} in {loc.file} @ {loc.line}:{loc.column}"
        )
        msg += f"\n  Original color {repr(color)}, new_color: {repr(new_color)}"
        super().__init__(msg)


class FunctionResolutionError(Exception):
    pass

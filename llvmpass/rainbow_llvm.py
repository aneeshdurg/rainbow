"""
Rainbow llvm pass - run via https://github.com/aneeshdurg/pyllvmpass
"""

from dataclasses import dataclass
import llvmcpy.llvm as cllvm
from lark import Lark


@dataclass
class GlobalFn:
    name: str
    filename: str
    lineno: int
    attributes: list[str]


def parse_annotations(annotations: str, m: cllvm.Module) -> list[GlobalFn]:
    annotations_parser = Lark(
        r"""
        annotations : types WS fields
        types : "[" NUMBER WS "x" WS tstruct "]"
        tstruct: "{" WS [(type ",")* type] WS "}"
        type : WORD NUMBER?
        fields : "[" (tstruct WS struct "," WS)* tstruct WS struct "]"
        struct : "{" WS [(type WS value "," WS)* type WS value] WS* "}"
        value : /(@|[0-9]|[a-zA-Z]|\.|%|_)+/

        %import common.NUMBER
        %import common.LETTER
        %import common.WORD
        %import common.WS
        %ignore WS
        """,
        start="annotations",
    )
    parsed = annotations_parser.parse(annotations)
    res = []
    for struct in parsed.find_data("struct"):
        attrs = [d.children[0].value for d in struct.find_data("value")]
        # Remove @ prefix
        fn_name = attrs[0][1:]

        filename_glbl, line_no, _ = attrs[-3:]
        filename_glbl = filename_glbl[1:]
        filename_glbl = (
            m.get_named_global(filename_glbl).get_initializer().get_as_string()[:-1]
        )
        line_no = int(line_no)

        attrs = attrs[1:-3]
        resolved_attrs = []
        for attr in attrs:
            if attr.startswith("@"):
                attr = (
                    m.get_named_global(attr[1:]).get_initializer().get_as_string()[:-1]
                )
            resolved_attrs.append(attr)

        res.append(GlobalFn(fn_name, filename_glbl, line_no, resolved_attrs))
    return res


def do_rainbow_analysis(m: cllvm.Module):
    annotations = m.get_named_global("llvm.global.annotations")
    if not annotations:
        return

    annotations = annotations.get_initializer().print_value_to_string().decode()
    global_fns = parse_annotations(annotations, m)
    for fn in global_fns:
        print(fn)
    return


def run_on_module(m: cllvm.Module) -> int:
    do_rainbow_analysis(m)
    return 0

"""
Rainbow llvm pass - run via https://github.com/aneeshdurg/pyllvmpass
"""

import os
import logging
from dataclasses import dataclass
from pathlib import Path

import llvmcpy.llvm as cllvm
from lark import Lark
import rainbow
from rainbow.config import Config
from rainbow.scope import Scope


@dataclass
class GlobalFn:
    name: str
    filename: str
    lineno: int
    attributes: list[str]



def const_str_glbl(m: cllvm.Module, glbl: str) -> str:
    return m.get_named_global(glbl).get_initializer().get_as_string()[:-1]


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
        filename_glbl = const_str_glbl(m, filename_glbl)
        line_no = int(line_no)

        attrs = attrs[1:-3]
        resolved_attrs = []
        for attr in attrs:
            if attr.startswith("@"):
                attr = const_str_glbl(m, attr[1:])
            resolved_attrs.append(attr)

        res.append(GlobalFn(fn_name, filename_glbl, line_no, resolved_attrs))
    return res


def do_rainbow_analysis(m: cllvm.Module):
    logging.basicConfig(level=logging.NOTSET)
    logger = logging.getLogger("rainbow")
    verbose = os.environ.get("RAINBOW_VERBOSITY", "error").lower()
    verbosity_map = {
        "quiet": logging.CRITICAL,
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG,
    }
    logger.setLevel(verbosity_map[verbose])

    config_file = os.environ.get("RAINBOW_CONFIG", "rainbow_config.json")
    config = Config.from_json(Path(config_file), logger=logger)

    root_scope = Scope.create_root()
    scope_id = 1

    annotations = m.get_named_global("llvm.global.annotations")
    if not annotations:
        return

    annotations = annotations.get_initializer().print_value_to_string().decode()
    global_fns = parse_annotations(annotations, m)
    for fn in global_fns:
        # TODO get param colors
        # TODO pass in filename/line numbers?
        Scope.create_function(
            scope_id,
            root_scope,
            fn.name,
            fn.attributes[0],
            {}
        )

    for fn in global_fns:
        fn_scope = root_scope.resolve_function(fn.name)
        assert fn_scope
        scope_id += 1
        llvm_fn = m.get_named_function(fn.name)
        print(fn)
        inst_to_color = {}
        for bb in llvm_fn.iter_basic_blocks():
            for inst in bb.iter_instructions():
                opcode = cllvm.Opcode[inst.instruction_opcode]
                if opcode == "Call":
                    called_fn =  inst.get_operand(inst.get_num_arg_operands())
                    if called_fn.name.decode().startswith('llvm.var.annotation'):
                        # llvm.var.annotation is a hint to analyzers to annotate a particular
                        # instruction
                        annotated_obj = inst.get_operand(0)
                        iptr = str(annotated_obj.ptr[0]).split()[-1][:-1]
                        annotation = inst.get_operand(1)
                        color = const_str_glbl(m, annotation.name.decode())
                        if iptr not in inst_to_color:
                            inst_to_color[iptr] = []
                        inst_to_color[iptr].append(color)
                        # TODO set parameter colors here
                    else:
                        for i in range(inst.get_num_arg_operands()):
                            iptr = str(inst.get_operand(i).ptr[0]).split()[-1][:-1]
                        callee_name = called_fn.name.decode()
                        callee = root_scope.resolve_function(callee_name)
                        if callee:
                            fn_scope.register_call_scope(callee)

    print()
    print(root_scope.to_cypher())
    print(config.run(root_scope))

    return


def run_on_module(m: cllvm.Module) -> int:
    do_rainbow_analysis(m)
    return 0

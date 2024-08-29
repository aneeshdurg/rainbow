"""
Rainbow as an llvm pass
"""

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import llvmcpy.llvm as cllvm
from lark import Lark
from rainbow.config import Config
from rainbow.scope import Scope


@dataclass
class AnnotatedFn:
    """Class modeling a function with global annotations"""
    name: str
    filename: str
    lineno: int
    attributes: list[str]

@dataclass
class RainbowLLVM:
    module: cllvm.Module
    config: Config
    logger: logging.Logger = field(default_factory=lambda: logging.Logger("rainbow"))

    def decode_name(self,  name: str):
        """Demangle C++ symbols"""
        p = subprocess.Popen(["c++filt"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        out = p.communicate(name.encode())
        return out[0].decode()


    def const_str_glbl(self, glbl: str, remove_prefix: bool=False) -> str:
        """Retrive the value of a constant global string"""
        a = self.module.get_named_global(glbl).get_initializer().get_as_string()[:-1]
        if remove_prefix and self.config.prefix in a:
            return a[len(self.config.prefix) :]
        return a


    def get_iptr(self, inst) -> str:
        """Get the hex representation of the underlying pointer for an
        instruction - this can be used as a UID for the instruction"""
        return str(inst.ptr[0]).split()[-1][:-1]


    def parse_annotations(self, annotations: str) -> dict[str, AnnotatedFn]:
        """Parse global annotations and return all functions that were
        annotated"""
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
        res = {}
        for struct in parsed.find_data("struct"):
            attrs = [d.children[0].value for d in struct.find_data("value")]
            # Remove @ prefix
            fn_name = attrs[0][1:]

            filename_glbl, line_no, _ = attrs[-3:]
            filename_glbl = filename_glbl[1:]
            filename_glbl = self.const_str_glbl(filename_glbl)
            line_no = int(line_no)

            attrs = attrs[1:-3]
            resolved_attrs = []
            for attr in attrs:
                if attr.startswith("@"):
                    attr = self.const_str_glbl(attr[1:], True)
                resolved_attrs.append(attr)

            res[fn_name] = AnnotatedFn(fn_name, filename_glbl, line_no, resolved_attrs)
        return res


    def run(self):
        root_scope = Scope.create_root()
        scope_id = 1

        annotations = self.module.get_named_global("llvm.global.annotations")
        if not annotations:
            return

        annotations = annotations.get_initializer().print_value_to_string().decode()
        annotated_module_fns = self.parse_annotations(annotations)
        for fn in self.module.iter_functions():
            # Need to check if the fn is linked in
            # TODO get param colors
            fn_name = fn.name.decode()
            # TODO pass in filename/line numbers?
            if fn_name in annotated_module_fns:
                Scope.create_function(
                    scope_id,
                    root_scope,
                    self.decode_name(fn_name),
                    annotated_module_fns[fn_name].attributes[0],
                    {},
                )
            else:
                Scope.create_function(scope_id, root_scope, self.decode_name(fn_name), None, {})

        for fn in self.module.iter_functions():
            fn_scope = root_scope.resolve_function(self.decode_name(fn.name.decode()))
            assert fn_scope
            scope_id += 1
            llvm_fn = self.module.get_named_function(fn.name.decode())
            inst_to_color = {}
            lambdas = set()
            for bb in llvm_fn.iter_basic_blocks():
                for inst in bb.iter_instructions():
                    opcode = cllvm.Opcode[inst.instruction_opcode]
                    if opcode == "Alloca":
                        parts = inst.print_value_to_string().decode().split()
                        if parts[3].startswith("%class.anon"):
                            lambdas.add(self.get_iptr(inst))
                    elif opcode == "Call":
                        called_fn = inst.get_operand(inst.get_num_arg_operands())
                        if called_fn.name.decode().startswith("llvm.var.annotation"):
                            # llvm.var.annotation is a hint to analyzers to annotate a particular
                            # instruction
                            annotated_obj = inst.get_operand(0)
                            iptr = self.get_iptr(annotated_obj)
                            annotation = inst.get_operand(1)
                            color = self.const_str_glbl(annotation.name.decode(), True)
                            assert iptr not in inst_to_color, "duplicate color"
                            inst_to_color[iptr] = color
                            # TODO set parameter colors here
                        else:
                            callee_name = self.decode_name(called_fn.name.decode())
                            callee = root_scope.resolve_function(callee_name)
                            if callee:
                                # This should be safe because it's a lambda defined
                                # in this method
                                if callee_name.endswith("::operator()() const"):
                                    nargs = inst.get_num_arg_operands()
                                    iptr = self.get_iptr(inst.get_operand(nargs - 1))
                                    if iptr in lambdas and iptr in inst_to_color:
                                        callee.color = inst_to_color[iptr]
                                fn_scope.register_call_scope(callee)

        if self.config.run(root_scope):
            print(root_scope.to_cypher())
            sys.exit(1)


def run_on_module(m: cllvm.Module) -> int:
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

    RainbowLLVM(m, config, logger).run()
    return 0

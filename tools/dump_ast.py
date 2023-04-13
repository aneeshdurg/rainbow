#!/usr/bin/env python3
from pathlib import Path
from typing import Optional

import clang.cindex
import click


def dump_ast(tu: clang.cindex.TranslationUnit):
    def _process(node: clang.cindex.Cursor, depth: int):
        indent = depth * 2
        print(" " * indent, node.kind, node.spelling)
        for c in node.get_children():
            _process(c, depth + 1)

    _process(tu.cursor, 0)


@click.command(help="dump C++ ast")
@click.argument("cpp_file")
@click.option(
    "-c", "--clangLocation", type=Path, help="Path to libclang.so", required=True
)
def main(cpp_file: str, clanglocation: Optional[Path]):
    clang.cindex.Config.set_library_file(clanglocation)
    index = clang.cindex.Index.create()
    dump_ast(index.parse(cpp_file))


if __name__ == "__main__":
    main()

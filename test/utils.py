import os
import tempfile
import unittest
from typing import List

import clang.cindex

from rainbow import rainbow


def createRainbow(input_: str, prefix: str, colors: List[str]) -> rainbow.Rainbow:
    with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
        f.write(input_.encode())
        f.flush()
        index = clang.cindex.Index.create()
        tu = index.parse(f.name)
        return rainbow.Rainbow(tu, prefix, colors)


def main():
    lib_path = "/usr/lib/x86_64-linux-gnu/libclang-15.so.1"
    clang.cindex.Config.set_library_file(os.environ.get("CLANG_LIB_PATH", lib_path))
    unittest.main()

import tempfile
from typing import List

import clang.cindex
from rainbow import Rainbow


def createRainbow(input_: str, prefix: str, colors: List[str]) -> Rainbow:
    with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
        f.write(input_.encode())
        f.flush()
        index = clang.cindex.Index.create()
        return Rainbow(index.parse(f.name), prefix, colors)

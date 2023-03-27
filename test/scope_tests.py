import os
import tempfile
import textwrap
import unittest
from unittest.mock import MagicMock

from neo4j import GraphDatabase

import clang.cindex
import rainbow
from executors.neo4j_adapter import execute_query


class UnitTestScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert "CLANG_LIB_PATH" in os.environ
        clang.cindex.Config.set_library_file(os.environ["CLANG_LIB_PATH"])

    def testBasicCallGraph(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(
                textwrap.dedent(
                    """\
                void fn1() {}
                void fn2() {}
                void fn3() {}
                int main() {
                    fn1();
                    fn2();
                    fn3();
                    return 0;
                }
            """
                ).encode()
            )
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "", [])
        scope = sut.process()

        assert "main" in scope.functions
        assert scope.color is None
        assert len(scope.params) == 0
        assert len(scope.functions) == 4
        assert len(scope.called_functions) == 0

        main_fn = scope.functions["main"]
        assert main_fn.color is None
        assert len(main_fn.params) == 0
        assert len(main_fn.functions) == 0
        assert len(main_fn.child_scopes) == 0
        assert main_fn.called_functions == ["fn1", "fn2", "fn3"]


if __name__ == "__main__":
    unittest.main()

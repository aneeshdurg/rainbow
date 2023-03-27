import os
import textwrap
import unittest
from test.utils import createRainbow

import clang.cindex


class UnitTestScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert "CLANG_LIB_PATH" in os.environ
        clang.cindex.Config.set_library_file(os.environ["CLANG_LIB_PATH"])

    def testTrivial(self):
        sut = createRainbow(
            textwrap.dedent(
                """\
            int main() {
                return 0
            }
        """
            ),
            "",
            [],
        )
        scope = sut.process()

        assert scope.color is None
        assert len(scope.params) == 0
        assert len(scope.functions) == 1

        main_fn = scope.functions["main"]
        assert main_fn.color is None
        assert len(main_fn.called_functions) == 0

    def testRecursiveCallGraph(self):
        sut = createRainbow(
            textwrap.dedent(
                """\
            int main() {
                return main();
            }
        """
            ),
            "",
            [],
        )
        scope = sut.process()

        assert len(scope.functions) == 1
        main_fn = scope.functions["main"]
        assert main_fn.called_functions == ["main"]

    def testBasicCallGraph(self):
        sut = createRainbow(
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
            ),
            "",
            [],
        )
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

    def testBasicColor(self):
        sut = createRainbow(
            """[[clang::annotate("TEST")]] int main() { return 0; }""", "", ["TEST"]
        )
        scope = sut.process()
        assert scope.functions["main"].color == "TEST"


if __name__ == "__main__":
    unittest.main()

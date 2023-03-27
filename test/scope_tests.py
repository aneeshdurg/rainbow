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
        src = textwrap.dedent(
            """\
            int main() {
                return 0
            }
        """
        )
        sut = createRainbow(src, "", [])
        scope = sut.process()

        assert scope.color is None
        assert len(scope.params) == 0
        assert len(scope.functions) == 1

        main_fn = scope.functions["main"]
        assert main_fn.color is None
        assert len(main_fn.called_functions) == 0

    def testRecursiveCallGraph(self):
        src = textwrap.dedent(
            """\
            int main() {
                return main();
            }
        """
        )
        sut = createRainbow(src, "", [])
        scope = sut.process()

        assert len(scope.functions) == 1
        main_fn = scope.functions["main"]
        assert main_fn.called_functions == ["main"]

    def testBasicCallGraph(self):
        src = textwrap.dedent(
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
        )
        sut = createRainbow(src, "", [])
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

    def testColors(self):
        src = textwrap.dedent(
            """\
            #define COLOR(X) [[clang::annotate(#X)]]
            COLOR(RED) int ret0() { return 0; }
            COLOR(BLUE) int main() {
                COLOR(GREEN) int notafunction = 0;
                return ret0() + notafunction;
            }
        """
        )
        sut = createRainbow(src, "", ["RED", "BLUE", "GREEN"])
        scope = sut.process()

        assert scope.functions["main"].color == "BLUE"
        assert len(scope.functions["main"].functions) == 0
        assert scope.functions["main"].called_functions == ["ret0"]
        assert len(scope.functions["main"].child_scopes) == 0

        assert scope.functions["ret0"].color == "RED"
        assert len(scope.functions) == 2

    def testLambdaNameShadowing(self):
        src = textwrap.dedent(
            """\
            #define COLOR(X) [[clang::annotate(#X)]]
            COLOR(RED) int ret0() { return 0; }
            COLOR(BLUE) int main() {
                COLOR(GREEN) auto ret0 = []() { return 0; };
                return ret0();
            }
        """
        )
        sut = createRainbow(src, "", ["RED", "BLUE", "GREEN"])
        scope = sut.process()

        assert len(scope.functions) == 2

        main_fn = scope.functions["main"]
        assert main_fn.color == "BLUE"
        assert len(main_fn.functions) == 1
        assert main_fn.called_functions == ["ret0"]
        assert len(main_fn.child_scopes) == 0

        global_ret0 = scope.functions["ret0"]
        assert global_ret0.color == "RED"

        lambda_ret0 = main_fn.functions["ret0"]
        assert lambda_ret0.color == "GREEN"

        resolved_ret0 = main_fn.resolve_function("ret0")
        assert resolved_ret0
        assert resolved_ret0 != global_ret0
        assert resolved_ret0 == lambda_ret0


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import textwrap
import unittest
from unittest.mock import MagicMock

from spycy import spycy

import clang.cindex
from rainbow import rainbow

assert "CLANG_LIB_PATH" in os.environ
clang.cindex.Config.set_library_file(os.environ["CLANG_LIB_PATH"])


class UnitTestRainbow(unittest.TestCase):
    def testIsFunction(self):
        sut = rainbow.Rainbow(MagicMock(), "", [])

        node = MagicMock()
        assert sut.isFunction(node, node.kind) is None

        node = MagicMock(kind=clang.cindex.CursorKind.FUNCTION_DECL)
        assert sut.isFunction(node, node.kind) == node.spelling

    def testNoPrefix(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(
                textwrap.dedent(
                    """\
                    [[clang::annotate("foo")]] int main() {
                        return 0;
                    }
            """
                ).encode()
            )
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "", ["foo"])
            sut.process()

    def testUnexpectedColors(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(
                textwrap.dedent(
                    """\
                    [[clang::annotate("Test::foo")]] int main() {
                        return 0;
                    }
            """
                ).encode()
            )
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "Test::", [])
            with self.assertRaisesRegex(Exception, ".*unknown color.*"):
                sut.process()

    # def testNoTaggedFunctions(self):
    #     with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
    #         f.write(textwrap.dedent("""\
    #                 int ret1 { return 1; }
    #                 int main() { return 0; }
    #         """).encode())
    #         f.flush()

    #         index = clang.cindex.Index.create()
    #         sut = rainbow.Rainbow(index.parse(f.name), "COLOR::", ["RED", "BLUE"])
    #         sut.process()
    #         expected = "// no tagged function calls\n;\n"
    #         self.assertEqual(expected, sut.toCypher())

    # def testNoTaggedFunctionCalls(self):
    #     with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
    #         f.write(textwrap.dedent("""\
    #                 int ret0() { return 0; }
    #                 int main() { return ret0(); }
    #         """).encode())
    #         f.flush()

    #         index = clang.cindex.Index.create()
    #         sut = rainbow.Rainbow(index.parse(f.name), "COLOR::", ["RED", "BLUE"])
    #         sut.process()
    #         expected = "// no tagged function calls\n;\n"
    #         self.assertEqual(expected, sut.toCypher())


class CypherTests(unittest.TestCase):
    def setUp(self):
        self.executor = spycy.CypherExecutor()

    def tearDown(self):
        del self.executor

    def testCallGraph(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(
                textwrap.dedent(
                    """\
                    [[clang::annotate("COLOR::BLUE")]] int ret0() { return 0; }
                    [[clang::annotate("COLOR::RED")]] int main() { return ret0(); }
            """
                ).encode()
            )
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "COLOR::", ["RED", "BLUE"])
            scope = sut.process()
            create_query = scope.toCypher()
            self.executor.exec(create_query)
            result = self.executor.exec(
                "MATCH (a)-->(b) return a.name, labels(a), b.name, labels(b)",
            )
            self.assertEqual(result["a.name"][0], "main")
            self.assertEqual(result["labels(a)"][0], ["RED"])
            self.assertEqual(result["b.name"][0], "ret0")
            self.assertEqual(result["labels(b)"][0], ["BLUE"])


if __name__ == "__main__":
    unittest.main()

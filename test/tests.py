import os
import unittest
import textwrap
import tempfile

from unittest.mock import MagicMock

import rainbow
import clang.cindex

from neo4j import GraphDatabase


class UnitTestRainbow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert 'CLANG_LIB_PATH' in os.environ
        clang.cindex.Config.set_library_file(os.environ['CLANG_LIB_PATH'])

    def testIsFunction(self):
        sut = rainbow.Rainbow(MagicMock(), "", [])

        node = MagicMock()
        assert sut.isFunction(node) is None

        node = MagicMock(kind=clang.cindex.CursorKind.FUNCTION_DECL)
        assert sut.isFunction(node) == node.spelling

        try:
            node = MagicMock(
                get_children=lambda: [MagicMock(kind=clang.cindex.CursorKind.LAMBDA_EXPR)]
            )
            sut.isFunction(node)
        except Exception as e:
            assert 'Lambdas unsupported' in str(e)

    def testNoPrefix(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(textwrap.dedent("""\
                    [[clang::annotate("foo")]] int main() {
                        return 0;
                    }
            """).encode())
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "", ["foo"])
            sut.process()

    def testUnexpectedColors(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(textwrap.dedent("""\
                    [[clang::annotate("Test::foo")]] int main() {
                        return 0;
                    }
            """).encode())
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "Test::", [])
            with self.assertRaisesRegex(Exception, ".*unknown color.*"):
                sut.process()

    def testNoTaggedFunctions(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(textwrap.dedent("""\
                    int ret1 { return 1; }
                    int main() { return 0; }
            """).encode())
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "COLOR::", ["RED", "BLUE"])
            sut.process()
            expected = "// no tagged function calls\n;\n"
            self.assertEqual(expected, sut.toCypher())

    def testNoTaggedFunctionCalls(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(textwrap.dedent("""\
                    int ret0() { return 0; }
                    int main() { return ret0(); }
            """).encode())
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "COLOR::", ["RED", "BLUE"])
            sut.process()
            expected = "// no tagged function calls\n;\n"
            self.assertEqual(expected, sut.toCypher())

if __name__ == "__main__":
    unittest.main()

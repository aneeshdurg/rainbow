import os
import tempfile
import textwrap
import unittest
from unittest.mock import MagicMock

import clang.cindex
import utils
from spycy import spycy

from rainbow import rainbow


class UnitTestRainbow(unittest.TestCase):
    def testIsFunction(self):
        sut = rainbow.Rainbow(MagicMock(), "", [])

        node = MagicMock()
        assert sut.is_function(node, node.kind) is None

        node = MagicMock(kind=clang.cindex.CursorKind.FUNCTION_DECL)
        assert sut.is_function(node, node.kind) == node.spelling

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
            create_query = scope.to_cypher()
            self.executor.exec(create_query)
            result = self.executor.exec(
                "MATCH (a)-->(b) return a.name, labels(a), b.name, labels(b)",
            )
            self.assertEqual(result["a.name"][0], "main")
            self.assertEqual(result["labels(a)"][0], ["RED"])
            self.assertEqual(result["b.name"][0], "ret0")
            self.assertEqual(result["labels(b)"][0], ["BLUE"])


if __name__ == "__main__":
    utils.main()

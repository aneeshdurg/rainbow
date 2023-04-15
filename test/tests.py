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
        sut = utils.createRainbow("", "", [], [])

        node = MagicMock()
        assert sut.is_function(node, node.kind) is None

        node = MagicMock(kind=clang.cindex.CursorKind.FUNCTION_DECL)
        assert sut.is_function(node, node.kind) == node.spelling

    def testNoPrefix(self):
        src = textwrap.dedent(
            """\
                [[clang::annotate("foo")]] int main() {
                    return 0;
                }
        """
        )
        sut = utils.createRainbow(src, "", ["foo"], [])
        sut.process()

    def testUnexpectedColors(self):
        src = textwrap.dedent(
            """\
                [[clang::annotate("Test::foo")]] int main() {
                    return 0;
                }
        """
        )
        sut = utils.createRainbow(src, "Test::", [""], [])
        with self.assertRaisesRegex(Exception, ".*unknown color.*"):
            sut.process()


class CypherTests(unittest.TestCase):
    def setUp(self):
        self.executor = spycy.CypherExecutor()

    def tearDown(self):
        del self.executor

    def testCallGraph(self):
        src = textwrap.dedent(
            """\
                [[clang::annotate("COLOR::BLUE")]] int ret0() { return 0; }
                [[clang::annotate("COLOR::RED")]] int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "COLOR::", ["RED", "BLUE"], [])
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

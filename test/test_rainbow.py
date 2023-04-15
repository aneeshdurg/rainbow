import textwrap
import unittest
from unittest.mock import MagicMock

import clang.cindex
import utils
from spycy import spycy


class UnitTestRainbow(unittest.TestCase):
    def test_is_function(self):
        sut = utils.createRainbow("", "", [], [])

        node = MagicMock()
        assert sut.is_function(node, node.kind) is None

        node = MagicMock(kind=clang.cindex.CursorKind.FUNCTION_DECL)
        assert sut.is_function(node, node.kind) == node.spelling

    def test_no_prefix(self):
        src = textwrap.dedent(
            """\
                [[clang::annotate("foo")]] int main() {
                    return 0;
                }
        """
        )
        sut = utils.createRainbow(src, "", ["foo"], [])
        sut.process()

    def test_unexpected_colors(self):
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


if __name__ == "__main__":
    utils.main()

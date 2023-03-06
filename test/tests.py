import unittest

from unittest.mock import MagicMock

import rainbow
import clang.cindex


class TestRainbow(unittest.TestCase):
    def testIsFunction(self):
        sut = rainbow.Rainbow(MagicMock(), "COLOR::")

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


if __name__ == "__main__":
    unittest.main()

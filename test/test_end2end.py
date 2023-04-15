import textwrap
import unittest

import utils


class End2EndTests(unittest.TestCase):
    def test_no_annotations(self):
        src = textwrap.dedent(
            """\
                int ret0() { return 0; }
                int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-->(:BLUE)"])
        # Should always accept
        assert not sut.run()

    def test_basic_accept(self):
        src = textwrap.dedent(
            """\
                #define COLOR(X) [[clang::annotate(#X)]]
                int ret0() { return 0; }
                COLOR(RED) int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-->(:BLUE)"])
        assert not sut.run()

    def test_basic_reject(self):
        src = textwrap.dedent(
            """\
                #define COLOR(X) [[clang::annotate(#X)]]
                COLOR(BLUE) int ret0() { return 0; }
                COLOR(RED) int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-->(:BLUE)"])
        assert sut.run()


if __name__ == "__main__":
    utils.main()

import textwrap
import unittest

import utils


class End2EndTests(unittest.TestCase):
    def testNoAnnotations(self):
        src = textwrap.dedent(
            """\
                int ret0() { return 0; }
                int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-->(:BLUE)"])
        # Should always accept
        assert not sut.run()

    def testBasicAccept(self):
        src = textwrap.dedent(
            """\
                #define COLOR(X) [[clang::annotate(#X)]]
                int ret0() { return 0; }
                COLOR(RED) int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-->(:BLUE)"])
        assert not sut.run()

    def testBasicReject(self):
        src = textwrap.dedent(
            """\
                #define COLOR(X) [[clang::annotate(#X)]]
                COLOR(BLUE) int ret0() { return 0; }
                COLOR(RED) int main() { return ret0(); }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-->(:BLUE)"])
        assert sut.run()

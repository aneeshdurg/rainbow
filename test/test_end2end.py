import textwrap
import unittest

import utils

from rainbow import errors


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

    def test_reject_parameter_mismatch(self):
        src = textwrap.dedent(
            """\
                #include <functional>

                #define COLOR(X) [[clang::annotate(#X)]]
                int ret0(COLOR(RED) std::function<int(void)> cb) { return cb(); }
                int main() {
                    COLOR(BLUE) auto cb = []() { return 0; };
                    return ret0(cb);
                }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], [])
        with self.assertRaises(errors.InvalidAssignmentError):
            sut.run()


if __name__ == "__main__":
    utils.main()

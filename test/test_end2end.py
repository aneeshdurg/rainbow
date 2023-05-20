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

    def test_reject_indirect_uncolored_parameter(self):
        src = textwrap.dedent(
            """\
                #include <functional>

                #define COLOR(X) [[clang::annotate(#X)]]
                COLOR(RED) int ret0(std::function<int(void)> cb) { return cb(); }
                int main() {
                    COLOR(BLUE) auto cb = []() { return 0; };
                    return ret0(cb);
                }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-[*]->(:BLUE)"])
        assert sut.run()

    def test_reject_indirect_colored_parameter(self):
        src = textwrap.dedent(
            """\
                #include <functional>

                #define COLOR(X) [[clang::annotate(#X)]]
                int ret0(COLOR(RED) std::function<int(void)> cb) { return cb(); }
                int main() {
                    COLOR(BLUE) auto cb = []() { return 0; };
                    auto cb_wrapper = [&]() { return cb(); };
                    return ret0(cb_wrapper);
                }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-[*]->(:BLUE)"])
        assert sut.run()

    def test_invalid_alias(self):
        src = textwrap.dedent(
            """\
                #include <functional>

                #define COLOR(X) [[clang::annotate(#X)]]
                int ret0(COLOR(RED) std::function<int(void)> cb) { return cb(); }
                int main() {
                    COLOR(BLUE) auto cb = []() { return 0; };
                    COLOR(RED) auto cb_alias = cb;
                    return ret0(cb_alias);
                }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-[*]->(:BLUE)"])
        with self.assertRaises(errors.InvalidAssignmentError):
            sut.run()

    def test_reject_indirect_aliased_parameter(self):
        src = textwrap.dedent(
            """\
                #include <functional>

                #define COLOR(X) [[clang::annotate(#X)]]
                int ret0(COLOR(RED) std::function<int(void)> cb) { return cb(); }
                int main() {
                    COLOR(BLUE) auto cb = []() { return 0; };
                    auto cb_wrapper = [&]() { return cb(); };
                    auto cb_wrapper_alias = cb_wrapper;
                    return ret0(cb_wrapper_alias);
                }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], ["(:RED)-[*]->(:BLUE)"])
        assert sut.run()


if __name__ == "__main__":
    utils.main()

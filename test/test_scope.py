import textwrap
import unittest

import utils
from spycy import spycy

from rainbow.scope import Scope


class UnitTestScope(unittest.TestCase):
    """Unit tests of Scope"""

    def test_create_root(self):
        scope = Scope.create_root()
        assert scope.parent_scope is None
        assert scope.id_ == 0

    def test_create_function(self):
        root = Scope.create_root()
        scope = Scope.create_function(1, root, "fnname", None, {})
        assert scope.parent_scope is root
        assert scope.id_ == 1

    def test_register_call(self):
        root = Scope.create_root()
        call1 = Scope.create_function(1, root, "call1", None, {})
        call2 = Scope.create_function(1, root, "call2", None, {})
        call3 = Scope.create_function(1, root, "call3", None, {})
        root.register_call("call1")
        root.register_call("call2")
        root.register_call("call3")
        assert root.called_functions == [call1, call2, call3]

    def test_alias(self):
        with self.assertRaises(AssertionError):
            scope = Scope.create_root()
            scope.alias()
        root = Scope.create_root()
        fn1 = Scope.create_function(1, root, "fnname", None, {})
        fn2 = Scope.create_function(2, root, "fnname", None, {})
        assert fn1.alias() == "`fnname__1`"
        assert fn2.alias() == "`fnname__2`"

    def test_resolve_function(self):
        root = Scope.create_root()
        assert root.resolve_function("fnname") is None

        fn1 = Scope.create_function(1, root, "fnname", None, {})
        assert fn1.resolve_function("fnname") is fn1
        assert root.resolve_function("fnname") is fn1

        fn2 = Scope.create_function(1, root, "fnname", None, {})
        assert fn1.resolve_function("fnname") is fn1
        assert fn2.resolve_function("fnname") is fn2
        assert root.resolve_function("fnname") is fn2

    def test_resolve_function_nested(self):
        """
        Construct the following scope
        root
         |- fn1()
         |  |- fn3()
         |  |- fn1_scope1
         |     |- fn1_scope2
         |- fn2()
        """
        root = Scope.create_root()
        fn1 = Scope.create_function(1, root, "fn1", None, {})
        fn2 = Scope.create_function(2, root, "fn2", None, {})
        fn3 = Scope.create_function(3, fn1, "fn3", None, {})
        fn1_scope1 = Scope(4, fn1)
        fn1_scope2 = Scope(5, fn1_scope1)

        def assert_all_functions_resolve(scope):
            assert scope.resolve_function("fn1") is fn1
            assert scope.resolve_function("fn2") is fn2
            assert scope.resolve_function("fn3") is fn3

        assert_all_functions_resolve(fn3)
        assert_all_functions_resolve(fn1_scope1)
        assert_all_functions_resolve(fn1_scope2)

        # fn3 is only resolvable from within fn1
        assert root.resolve_function("fn3") is None
        assert fn2.resolve_function("fn3") is None
        assert fn1.resolve_function("fn3") is fn3

    def test_resolve_parameter(self):
        root = Scope.create_root()
        fn1 = Scope.create_function(1, root, "fn1", None, {"param0": "RED"})

        assert "param0" in fn1.params
        assert fn1.params["param0"].is_param == True
        assert fn1.resolve_function("param0") is fn1.params["param0"]


class TestScopeToCypher(unittest.TestCase):
    """Test generating openCypher queries from Scope"""

    def setUp(self):
        self.executor = spycy.CypherExecutor()

    def tearDown(self):
        del self.executor

    def test_trivial(self):
        root = Scope.create_root()
        self.executor.exec(root.to_cypher())
        query = "MATCH (a) RETURN count(a) as result"
        num_nodes = self.executor.exec(query)["result"][0]
        assert num_nodes == 0

    def test_function(self):
        root = Scope.create_root()
        Scope.create_function(1, root, "fn1", None, {})
        Scope.create_function(2, root, "fn2", "RED", {})
        self.executor.exec(root.to_cypher())
        result = self.executor.exec(
            "MATCH (a) RETURN a.name as name, labels(a) as colors ORDER BY name"
        )

        assert result["name"][0] == "fn1"
        assert result["colors"][0] == []

        assert result["name"][1] == "fn2"
        assert result["colors"][1] == ["RED"]

    def test_function_nested(self):
        root = Scope.create_root()
        fn1 = Scope.create_function(1, root, "fn1", "GREEN", {})
        fn2 = Scope.create_function(2, root, "fn2", "GREEN", {})
        Scope.create_function(3, fn1, "fn3", "RED", {})
        Scope.create_function(4, root, "fn3", "BLUE", {})

        fn1.register_call("fn3")  # should resolve to scope 3
        fn2.register_call("fn3")  # should resolve to scope 4

        self.executor.exec(root.to_cypher())
        result = self.executor.exec(
            "MATCH (a) RETURN a.name as name, labels(a)[0] as color ORDER BY name, color"
        )

        assert len(result) == 4

        assert result["name"][0] == "fn1"
        assert result["color"][0] == "GREEN"

        assert result["name"][1] == "fn2"
        assert result["color"][1] == "GREEN"

        assert result["name"][2] == "fn3"
        assert result["color"][2] == "BLUE"

        assert result["name"][3] == "fn3"
        assert result["color"][3] == "RED"

        result = self.executor.exec(
            """MATCH (a)-->(b)
            RETURN a.name, b.name, labels(b)[0] as bcolor
            ORDER BY a.name"""
        )

        assert len(result) == 2

        assert result["a.name"][0] == "fn1"
        assert result["b.name"][0] == "fn3"
        assert result["bcolor"][0] == "RED"

        assert result["a.name"][1] == "fn2"
        assert result["b.name"][1] == "fn3"
        assert result["bcolor"][1] == "BLUE"

    def test_params(self):
        root = Scope.create_root()
        fn1 = Scope.create_function(1, root, "fn1", "GREEN", {"fn2": None})
        Scope.create_function(2, root, "fn2", "GREEN", {})
        fn1.register_call("fn2")  # should resolve to parameter

        self.executor.exec(root.to_cypher())
        result = self.executor.exec(
            "MATCH (a)-->(b {name: 'fn2'}) RETURN a.name, b.name, labels(b) as bcolors"
        )

        assert len(result) == 1
        assert result["a.name"][0] == "fn1"
        assert result["b.name"][0] == "fn2"
        assert result["bcolors"][0] == []


class TestRainbowScopeConstruction(unittest.TestCase):
    """Test that Rainbow correctly models C++ as Scope"""

    def test_trivial(self):
        src = textwrap.dedent(
            """\
            int main() {
                return 0
            }
        """
        )
        sut = utils.createRainbow(src, "", [], [])
        scope = sut.process()

        assert scope.color is None
        assert len(scope.params) == 0
        assert len(scope.functions) == 1

        main_fn = scope.functions["main"]
        assert main_fn.color is None
        assert len(main_fn.called_functions) == 0

    def test_recursive_call_graph(self):
        src = textwrap.dedent(
            """\
            int main() {
                return main();
            }
        """
        )
        sut = utils.createRainbow(src, "", [], [])
        scope = sut.process()

        assert len(scope.functions) == 1
        main_fn = scope.functions["main"]
        assert main_fn.called_functions == [main_fn]

    def test_basic_call_Graph(self):
        src = textwrap.dedent(
            """\
            void fn1() {}
            void fn2() {}
            void fn3() {}
            int main() {
                fn1();
                fn2();
                fn3();
                return 0;
            }
        """
        )
        sut = utils.createRainbow(src, "", [], [])
        scope = sut.process()

        assert "main" in scope.functions
        assert scope.color is None
        assert len(scope.params) == 0
        assert len(scope.functions) == 4
        assert len(scope.called_functions) == 0

        main_fn = scope.functions["main"]
        assert main_fn.color is None
        assert len(main_fn.params) == 0
        assert len(main_fn.functions) == 0
        assert len(main_fn.child_scopes) == 0
        assert main_fn.called_functions == [
            scope.functions[f] for f in ["fn1", "fn2", "fn3"]
        ]

    def test_basic_color(self):
        sut = utils.createRainbow(
            """[[clang::annotate("TEST")]] int main() { return 0; }""", "", ["TEST"], []
        )
        scope = sut.process()
        assert scope.functions["main"].color == "TEST"

    def test_colors(self):
        src = textwrap.dedent(
            """\
            #define COLOR(X) [[clang::annotate(#X)]]
            COLOR(RED) int ret0() { return 0; }
            COLOR(BLUE) int main() {
                COLOR(GREEN) int notafunction = 0;
                return ret0() + notafunction;
            }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE", "GREEN"], [])
        scope = sut.process()

        assert scope.functions["main"].color == "BLUE"
        assert len(scope.functions["main"].functions) == 0
        assert scope.functions["main"].called_functions == [scope.functions["ret0"]]
        assert len(scope.functions["main"].child_scopes) == 0

        assert scope.functions["ret0"].color == "RED"
        assert len(scope.functions) == 2

    def test_lambda_name_shadowing(self):
        src = textwrap.dedent(
            """\
            #define COLOR(X) [[clang::annotate(#X)]]
            COLOR(RED) int ret0() { return 0; }
            COLOR(BLUE) int main() {
                COLOR(GREEN) auto ret0 = []() { return 0; };
                return ret0();
            }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE", "GREEN"], [])
        scope = sut.process()

        assert len(scope.functions) == 2

        main_fn = scope.functions["main"]
        assert main_fn.color == "BLUE"
        assert len(main_fn.functions) == 1
        assert main_fn.called_functions == [scope.functions["ret0"]]
        assert len(main_fn.child_scopes) == 0

        global_ret0 = scope.functions["ret0"]
        assert global_ret0.color == "RED"

        lambda_ret0 = main_fn.functions["ret0"]
        assert lambda_ret0.color == "GREEN"

        resolved_ret0 = main_fn.resolve_function("ret0")
        assert resolved_ret0
        assert resolved_ret0 != global_ret0
        assert resolved_ret0 == lambda_ret0

    # Expected failure because conflicting references aren't tracked correctly
    def test_lambda_name_shadowing_after_reference(self):
        src = textwrap.dedent(
            """\
            #define COLOR(X) [[clang::annotate(#X)]]
            COLOR(RED) int ret0() { return 0; }
            int main() {
                int x = ret0();
                COLOR(BLUE) auto ret0 = []() { return 0; };
                return x + ret0();
            }
        """
        )
        sut = utils.createRainbow(src, "", ["RED", "BLUE"], [])
        scope = sut.process()

        assert len(scope.functions) == 2

        main_fn = scope.functions["main"]
        assert len(main_fn.called_functions) == 2
        # First call is to the function in global scope
        assert main_fn.called_functions[0] is scope.functions["ret0"]
        # Second call is to the shadowing lambda
        assert main_fn.called_functions[1] is main_fn.functions["ret0"]


if __name__ == "__main__":
    utils.main()

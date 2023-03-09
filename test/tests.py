import os
import unittest
import textwrap
import tempfile

from unittest.mock import MagicMock

import rainbow
import clang.cindex

from executors.neo4j_adapter import execute_query

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

def deleteAllNodes(session):
    execute_query(session, "MATCH (a) DETACH DELETE a")

class CypherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert 'CLANG_LIB_PATH' in os.environ
        clang.cindex.Config.set_library_file(os.environ['CLANG_LIB_PATH'])

    def setUp(self):
        assert 'NEO4J_ADDRESS' in os.environ
        uri = os.environ['NEO4J_ADDRESS']

        assert 'NEO4J_USERNAME' in os.environ
        username = os.environ['NEO4J_USERNAME']

        assert 'NEO4J_PASSWORD' in os.environ
        password = os.environ['NEO4J_PASSWORD']

        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        with self.driver.session() as session:
            deleteAllNodes(session);

    def tearDown(self):
        with self.driver.session() as session:
            deleteAllNodes(session);
        self.driver.close()
        del self.driver

    def testCallGraph(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp") as f:
            f.write(textwrap.dedent("""\
                    [[clang::annotate("COLOR::BLUE")]] int ret0() { return 0; }
                    [[clang::annotate("COLOR::RED")]] int main() { return ret0(); }
            """).encode())
            f.flush()

            index = clang.cindex.Index.create()
            sut = rainbow.Rainbow(index.parse(f.name), "COLOR::", ["RED", "BLUE"])
            sut.process()
            create_query = sut.toCypher()
            with self.driver.session() as session:
                execute_query(session, create_query)
                result = execute_query(session, "MATCH (a)-->(b) return a.name, labels(a), b.name, labels(b)")
                self.assertEqual(result["a.name"][0], "main")
                self.assertEqual(result["labels(a)"][0], ["RED"])
                self.assertEqual(result["b.name"][0], "ret0")
                self.assertEqual(result["labels(b)"][0], ["BLUE"])

if __name__ == "__main__":
    unittest.main()

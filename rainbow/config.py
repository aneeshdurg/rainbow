import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from spycy import spycy

from rainbow.scope import Scope


def patterns_to_cypher(patterns: List[str]) -> List[str]:
    """Given a list of `patterns` output a cypher query combining them all"""
    output = []
    for pattern in patterns:
        output.append(f"MATCH {pattern.strip()} RETURN count(*) > 0 as invalidcalls")
    return output


def get_list_of_strings(config: Dict[str, Any], key: str) -> List[str]:
    if key not in config:
        raise AssertionError(f"Expected list of {key} in config")
    result = config[key]
    if not isinstance(result, list):
        raise AssertionError(f"Expected list of {key} in config")
    for value in result:
        if not isinstance(value, str):
            raise AssertionError(f"{key} must be a list of strings")

    return result


def get_string(config: Dict[str, Any], key: str) -> str:
    assert key in config
    result = config[key]
    if not isinstance(result, str):
        raise AssertionError(f"Expected parameter {key} to be string")

    return result


@dataclass
class Config:
    source: Path
    colors: List[str]
    validate_queries: List[str]
    prefix: str = "COLOR::"
    executor: Optional[Path] = None

    @classmethod
    def from_dict(cls, source: Path, config: Dict[str, Any]) -> "Config":
        """Convert a dictionary to a config"""
        colors = get_list_of_strings(config, "colors")
        patterns = get_list_of_strings(config, "patterns")

        result = Config(source, colors, patterns_to_cypher(patterns))

        if "prefix" in config:
            result.prefix = get_string(config, "prefix")
        if "executor" in config:
            executor = Path(get_string(config, "executor"))
            if not executor.exists() or not shutil.which(executor):
                raise AssertionError(f"Could not find executable at {executor}")
            result.executor = executor

        return result

    @classmethod
    def from_json(cls, source: Path) -> "Config":
        """Convert a JSON file to a config"""
        with source.open() as f:
            config = json.load(f)
        return Config.from_dict(source, config)

    def spycy_executor(self, create_query: str) -> bool:
        """Evaluate queries using sPyCy"""
        exe = spycy.CypherExecutor()
        exe.exec(create_query)
        invalid = False
        for vquery in self.validate_queries:
            invalid = invalid | exe.exec(vquery)["invalidcalls"][0]
            if invalid:
                return True
        return False

    def generic_executor(self, create_query: str) -> Optional[bool]:
        """Evaluate queries using a subprocess"""
        assert self.executor
        p = subprocess.Popen(
            [self.executor, self.source], stdout=subprocess.PIPE, stdin=subprocess.PIPE
        )
        validate_query = ";\n".join(self.validate_queries)
        (res, _) = p.communicate((create_query + "\n" + validate_query).encode())
        output = [json.loads(l) for l in res.decode().strip().split("\n") if len(l)]
        if len(output) == 0:
            return None
        return any(output)

    def run(self, scope: Scope) -> Optional[bool]:
        """Run the config against the passed in Scope"""
        create_query = scope.to_cypher()
        if self.executor:
            return self.generic_executor(create_query)
        return self.spycy_executor(create_query)

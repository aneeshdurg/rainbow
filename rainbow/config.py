import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from spycy import spycy

from rainbow.scope import Scope


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


class Pattern:
    match_pattern: str
    on_match: Optional[Dict[str, str]]
    error_msg: Optional[str]

    def __init__(self, pattern: str, on_match=None, error_msg=None):
        self.match_pattern = pattern
        self.on_match = on_match
        self.error_msg = error_msg

    def _assemble_query(self) -> str:
        projections = "count(*) > 0 as invalidcalls"
        if self.on_match:
            projection_frags = []
            for k, v in self.on_match.items():
                projection_frags.append(f"{v} as {k}")
            projections = "DISTINCT " + ", ".join(projection_frags)
        elif self.error_msg:
            projections = "*"
        return f"MATCH {self.match_pattern} RETURN {projections}"

    def run(self, logger, executor):
        result = executor(self._assemble_query())
        return self.error_handler(logger, result)

    def error_handler(
        self, logger: logging.Logger, table: List[Dict[str, Any]]
    ) -> Optional[bool]:
        if table is None:
            return None

        if self.error_msg:
            for row in table:
                msg = self.error_msg
                for var, value in row.items():
                    msg = msg.replace(f"%{var}", str(value))
                logger.error(msg)
            return len(table) > 0
        return table[0]["invalidcalls"]


@dataclass
class Config:
    source: Path
    colors: List[str]
    patterns: List[Pattern]
    prefix: str = "COLOR::"
    executor: Optional[Path] = None
    logger: logging.Logger = field(default_factory=lambda: logging.Logger("confifg"))

    @classmethod
    def from_dict(
        cls,
        source: Path,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ) -> "Config":
        """Convert a dictionary to a config"""
        colors = get_list_of_strings(config, "colors")

        # TODO error checking
        patterns_raw = config["patterns"]
        patterns = []
        for pattern_obj in patterns_raw:
            if type(pattern_obj) == str:
                patterns.append(Pattern(pattern_obj))
            else:
                match_pattern = pattern_obj["pattern"]
                on_match = pattern_obj.get("on_match")
                error_msg = pattern_obj.get("msg")
                if on_match:
                    assert error_msg
                patterns.append(Pattern(match_pattern, on_match, error_msg))

        result = Config(source, colors, patterns)
        if logger:
            result.logger = logger

        if "prefix" in config:
            result.prefix = get_string(config, "prefix")
        if "executor" in config:
            executor = Path(get_string(config, "executor"))
            if not executor.exists() or not shutil.which(executor):
                raise AssertionError(f"Could not find executable at {executor}")
            result.executor = executor

        return result

    @classmethod
    def from_json(
        cls, source: Path, logger: Optional[logging.Logger] = None
    ) -> "Config":
        """Convert a JSON file to a config"""
        with source.open() as f:
            config = json.load(f)
        return Config.from_dict(source, config, logger)

    def execute_queries(self, create_query: str, executor) -> Optional[bool]:
        executor(create_query)
        invalid = []
        for i, pattern in enumerate(self.patterns):
            result = pattern.run(self.logger.getChild(f"Pattern{i}"), executor)
            invalid.append(result)
            if result is None:
                self.logger.warning("Pattern %d returned unknown" % i)
            elif result:
                self.logger.warning("Pattern %d found errors" % i)
            else:
                self.logger.debug("Pattern %d passed!" % i)
        return any(invalid) if None not in invalid else None

    def spycy_executor(self, create_query: str) -> Optional[bool]:
        """Evaluate queries using sPyCy"""
        exe = spycy.CypherExecutor()
        spycy_exec = lambda q: exe.exec(q).to_dict("records")
        return self.execute_queries(create_query, spycy_exec)

    def generic_executor(self, create_query: str) -> Optional[bool]:
        """Evaluate queries using a subprocess"""
        assert self.executor
        p = subprocess.Popen(
            [self.executor, self.source], stdout=subprocess.PIPE, stdin=subprocess.PIPE
        )

        def run_query(q: str):
            p.stdin.write(q.encode())
            p.stdin.write("\n--\n".encode())
            p.stdin.flush()
            output = p.stdout.readline()
            return json.loads(output.decode())

        result = self.execute_queries(create_query, run_query)
        self.logger.debug("Finished query execution, shutting down")
        p.stdin.close()
        p.wait()
        return result

    def run(self, scope: Scope) -> Optional[bool]:
        """Run the config against the passed in Scope"""
        create_query = scope.to_cypher()
        if self.executor:
            return self.generic_executor(create_query)
        return self.spycy_executor(create_query)

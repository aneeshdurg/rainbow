#!/usr/bin/env python3
import json
import sys

from neo4j import GraphDatabase


def execute_query(session, query):
    def run_q(tx):
        result = tx.run(query)
        return result.to_df()

    return session.execute_write(run_q)


def readUntilDelim(delim: str) -> str:
    data = ""
    while (line := input()).strip() != delim:
        data += line + "\n"
    return data


if __name__ == "__main__":
    config_file = sys.argv[1]
    with open(config_file) as f:
        config = json.load(f).get("neo4j_config", {})
    uri = config.get("uri", "bolt://localhost:7687")
    username = config.get("username", "neo4j")
    password = config.get("password", "admin")
    driver = GraphDatabase.driver(uri, auth=(username, password))

    with driver.session() as session:
        try:
            execute_query(session, "match (a) detach delete (a)")
            create_query = readUntilDelim("--") + ";"
            execute_query(session, create_query)
            print(json.dumps(None))
            while True:
                validate_query = readUntilDelim("--") + ";"
                result = execute_query(session, validate_query)
                print(json.dumps(result.to_dict("records")))
        except EOFError:
            pass
        finally:
            execute_query(session, "match (a) detach delete (a)")
            driver.close()

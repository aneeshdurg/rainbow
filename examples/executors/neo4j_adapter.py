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
        config_file = json.load(f)
    uri = "bolt://localhost:7687"
    username = "neo4j"
    password = "admin"
    driver = GraphDatabase.driver(uri, auth=(username, password))

    create_query = readUntilDelim(";")
    try:
        while True:
            validate_query = readUntilDelim(";")
            with driver.session() as session:
                execute_query(session, "match (a) detach delete (a)")
                try:
                    execute_query(session, create_query)
                    result = execute_query(session, validate_query)
                    result = result["invalidcalls"][0]
                    print(json.dumps(bool(result)))
                finally:
                    execute_query(session, "match (a) detach delete (a)")
    except EOFError:
        pass
    finally:
        driver.close()

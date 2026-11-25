from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def initialize_schema(connection: sqlite3.Connection, statements: Iterable[str]) -> None:
    with write_transaction(connection):
        for statement in statements:
            connection.execute(statement)

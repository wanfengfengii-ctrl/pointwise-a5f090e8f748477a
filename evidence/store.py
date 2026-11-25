import sqlite3

from ledger_db import initialize_schema, write_transaction


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS issued_parcels (
        issue_id TEXT PRIMARY KEY NOT NULL,
        revision_id TEXT NOT NULL REFERENCES observation_revisions(revision_id),
        body TEXT NOT NULL
    )''',
    '''CREATE INDEX IF NOT EXISTS issued_parcels_revision
       ON issued_parcels(revision_id)''',
)


class IssueStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def insert(self, issue_id: str, revision_id: str, body: str) -> None:
        with write_transaction(self.connection):
            self.connection.execute(
                'INSERT INTO issued_parcels (issue_id, revision_id, body) VALUES (?, ?, ?)',
                (issue_id, revision_id, body),
            )

    def get(self, issue_id: str) -> tuple[str, str]:
        row = self.connection.execute(
            'SELECT revision_id, body FROM issued_parcels WHERE issue_id = ?', (issue_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown issue: {issue_id}')
        return row

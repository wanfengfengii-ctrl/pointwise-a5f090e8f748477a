import sqlite3
from uuid import uuid4

from ledger_db import initialize_schema, write_transaction


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS accepted_parcels (
        receipt_id TEXT PRIMARY KEY NOT NULL,
        issue_id TEXT NOT NULL UNIQUE,
        body TEXT NOT NULL,
        ack_id TEXT NOT NULL UNIQUE
    )''',
)


class ReceiptStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def accept_once(self, issue_id: str, body: str) -> tuple[str, str]:
        with write_transaction(self.connection):
            existing = self.connection.execute(
                'SELECT receipt_id, ack_id, body FROM accepted_parcels WHERE issue_id = ?',
                (issue_id,),
            ).fetchone()
            if existing is not None:
                receipt_id, ack_id, original_body = existing
                if original_body != body:
                    raise ValueError('issue ID already received with a different body')
                return receipt_id, ack_id
            receipt_id = f'receipt-{uuid4().hex}'
            ack_id = f'receipt-ack-{uuid4().hex}'
            self.connection.execute(
                'INSERT INTO accepted_parcels (receipt_id, issue_id, body, ack_id) VALUES (?, ?, ?, ?)',
                (receipt_id, issue_id, body, ack_id),
            )
        return receipt_id, ack_id

    def get(self, receipt_id: str) -> tuple[str, str, str]:
        row = self.connection.execute(
            'SELECT issue_id, ack_id, body FROM accepted_parcels WHERE receipt_id = ?',
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown receipt: {receipt_id}')
        return row

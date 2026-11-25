from dataclasses import dataclass
from fractions import Fraction
import sqlite3
from uuid import uuid4

from ledger_db import initialize_schema, write_transaction
from reports.analysis import StabilityResult


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS stability_reports (
        report_id TEXT PRIMARY KEY NOT NULL,
        round_id TEXT NOT NULL,
        width INTEGER NOT NULL CHECK (width IN (2, 4)),
        pair_count INTEGER NOT NULL CHECK (pair_count >= 0),
        status TEXT NOT NULL,
        numerator TEXT,
        denominator TEXT,
        CHECK (
            (pair_count = 0 AND status = 'insufficient' AND numerator IS NULL AND denominator IS NULL)
            OR (pair_count > 0 AND status = 'measured' AND numerator IS NOT NULL AND denominator IS NOT NULL)
        )
    )''',
    '''CREATE TABLE IF NOT EXISTS report_parents (
        report_id TEXT NOT NULL REFERENCES stability_reports(report_id),
        position INTEGER NOT NULL,
        receipt_id TEXT NOT NULL REFERENCES accepted_parcels(receipt_id),
        issue_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        PRIMARY KEY (report_id, position),
        UNIQUE (report_id, receipt_id)
    )''',
    '''CREATE TABLE IF NOT EXISTS report_acknowledgments (
        report_id TEXT PRIMARY KEY NOT NULL REFERENCES stability_reports(report_id),
        ack_id TEXT NOT NULL UNIQUE
    )''',
)


@dataclass(frozen=True)
class ReportParent:
    receipt_id: str
    issue_id: str
    revision_id: str
    segment_id: str


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    round_id: str
    width: int
    result: StabilityResult
    parents: tuple[ReportParent, ...]
    ack_id: str

    @property
    def receipt_ids(self) -> tuple[str, ...]:
        return tuple(parent.receipt_id for parent in self.parents)


class ReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def save(
        self, round_id: str, width: int, result: StabilityResult, parents: tuple[ReportParent, ...],
    ) -> ReportRecord:
        report_id = f'report-{uuid4().hex}'
        ack_id = f'report-ack-{uuid4().hex}'
        value = result.value
        numerator = str(value.numerator) if value is not None else None
        denominator = str(value.denominator) if value is not None else None
        with write_transaction(self.connection):
            self.connection.execute(
                '''INSERT INTO stability_reports
                   (report_id, round_id, width, pair_count, status, numerator, denominator)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (report_id, round_id, width, result.pair_count, result.status, numerator, denominator),
            )
            self.connection.executemany(
                '''INSERT INTO report_parents
                   (report_id, position, receipt_id, issue_id, revision_id, segment_id)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    (report_id, position, parent.receipt_id, parent.issue_id, parent.revision_id, parent.segment_id)
                    for position, parent in enumerate(parents)
                ),
            )
            self.connection.execute(
                'INSERT INTO report_acknowledgments (report_id, ack_id) VALUES (?, ?)',
                (report_id, ack_id),
            )
        return ReportRecord(report_id, round_id, width, result, parents, ack_id)

    def get(self, report_id: str) -> ReportRecord:
        row = self.connection.execute(
            '''SELECT r.round_id, r.width, r.pair_count, r.status, r.numerator, r.denominator, a.ack_id
               FROM stability_reports AS r LEFT JOIN report_acknowledgments AS a USING (report_id)
               WHERE r.report_id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown report: {report_id}')
        round_id, width, pair_count, status, numerator, denominator, ack_id = row
        value = Fraction(int(numerator), int(denominator)) if numerator is not None else None
        result = StabilityResult(pair_count, value)
        if result.status != status or ack_id is None:
            raise sqlite3.DatabaseError('stored report does not have a valid result and acknowledgment')
        parent_rows = self.connection.execute(
            '''SELECT receipt_id, issue_id, revision_id, segment_id FROM report_parents
               WHERE report_id = ? ORDER BY position''',
            (report_id,),
        )
        parents = tuple(ReportParent(*parent) for parent in parent_rows)
        if not parents:
            raise sqlite3.DatabaseError('stored report has no source receipts')
        return ReportRecord(report_id, round_id, width, result, parents, ack_id)

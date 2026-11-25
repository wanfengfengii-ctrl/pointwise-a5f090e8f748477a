from dataclasses import dataclass
from fractions import Fraction
import sqlite3
from uuid import uuid4

from ledger_db import initialize_schema, write_transaction
from reports.analysis import StabilityResult
from reports.calibration_analysis import CalibrationRangeResult
from reports.domain import Point


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
    '''CREATE TABLE IF NOT EXISTS calibration_reports (
        report_id TEXT PRIMARY KEY NOT NULL,
        round_id TEXT NOT NULL,
        width INTEGER NOT NULL CHECK (width IN (2, 4)),
        calibration_id TEXT NOT NULL,
        pair_count INTEGER NOT NULL CHECK (pair_count >= 0),
        status TEXT NOT NULL CHECK (status IN ('measured', 'insufficient', 'infeasible')),
        lower_numerator TEXT,
        lower_denominator TEXT,
        upper_numerator TEXT,
        upper_denominator TEXT,
        lower_a_num TEXT,
        lower_a_den TEXT,
        lower_b_num TEXT,
        lower_b_den TEXT,
        upper_a_num TEXT,
        upper_a_den TEXT,
        upper_b_num TEXT,
        upper_b_den TEXT,
        CHECK (
            (status = 'measured' AND pair_count > 0
             AND lower_numerator IS NOT NULL AND lower_denominator IS NOT NULL
             AND upper_numerator IS NOT NULL AND upper_denominator IS NOT NULL
             AND lower_a_num IS NOT NULL AND lower_a_den IS NOT NULL
             AND lower_b_num IS NOT NULL AND lower_b_den IS NOT NULL
             AND upper_a_num IS NOT NULL AND upper_a_den IS NOT NULL
             AND upper_b_num IS NOT NULL AND upper_b_den IS NOT NULL)
            OR (status <> 'measured'
             AND lower_numerator IS NULL AND lower_denominator IS NULL
             AND upper_numerator IS NULL AND upper_denominator IS NULL
             AND lower_a_num IS NULL AND lower_a_den IS NULL
             AND lower_b_num IS NULL AND lower_b_den IS NULL
             AND upper_a_num IS NULL AND upper_a_den IS NULL
             AND upper_b_num IS NULL AND upper_b_den IS NULL)
        )
    )''',
    '''CREATE TABLE IF NOT EXISTS calibration_report_parents (
        report_id TEXT NOT NULL REFERENCES calibration_reports(report_id),
        position INTEGER NOT NULL,
        receipt_id TEXT NOT NULL REFERENCES accepted_parcels(receipt_id),
        issue_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        PRIMARY KEY (report_id, position),
        UNIQUE (report_id, receipt_id)
    )''',
    '''CREATE TABLE IF NOT EXISTS calibration_report_acknowledgments (
        report_id TEXT PRIMARY KEY NOT NULL REFERENCES calibration_reports(report_id),
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


@dataclass(frozen=True)
class CalibrationReportRecord:
    report_id: str
    round_id: str
    width: int
    calibration_id: str
    result: CalibrationRangeResult
    parents: tuple[ReportParent, ...]
    ack_id: str

    @property
    def receipt_ids(self) -> tuple[str, ...]:
        return tuple(parent.receipt_id for parent in self.parents)


def _fraction_cell(value: Fraction | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    return str(value.numerator), str(value.denominator)


def _fraction_from_cells(numerator: str | None, denominator: str | None) -> Fraction | None:
    if numerator is None:
        if denominator is not None:
            raise sqlite3.DatabaseError('corrupt rational endpoint')
        return None
    return Fraction(int(numerator), int(denominator))


def _point_cells(point: Point | None) -> tuple[str | None, ...]:
    if point is None:
        return (None, None, None, None)
    a, b = point
    return (str(a.numerator), str(a.denominator), str(b.numerator), str(b.denominator))


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

    def save_calibrated(
        self,
        round_id: str,
        width: int,
        calibration_id: str,
        result: CalibrationRangeResult,
        parents: tuple[ReportParent, ...],
    ) -> CalibrationReportRecord:
        report_id = f'calibration-report-{uuid4().hex}'
        ack_id = f'calibration-report-ack-{uuid4().hex}'
        lower_num, lower_den = _fraction_cell(result.lower)
        upper_num, upper_den = _fraction_cell(result.upper)
        point_cells = (*_point_cells(result.lower_at), *_point_cells(result.upper_at))
        with write_transaction(self.connection):
            self.connection.execute(
                '''INSERT INTO calibration_reports
                   (report_id, round_id, width, calibration_id, pair_count, status,
                    lower_numerator, lower_denominator, upper_numerator, upper_denominator,
                    lower_a_num, lower_a_den, lower_b_num, lower_b_den,
                    upper_a_num, upper_a_den, upper_b_num, upper_b_den)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    report_id, round_id, width, calibration_id, result.pair_count, result.status,
                    lower_num, lower_den, upper_num, upper_den, *point_cells,
                ),
            )
            self.connection.executemany(
                '''INSERT INTO calibration_report_parents
                   (report_id, position, receipt_id, issue_id, revision_id, segment_id)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    (report_id, position, parent.receipt_id, parent.issue_id, parent.revision_id, parent.segment_id)
                    for position, parent in enumerate(parents)
                ),
            )
            self.connection.execute(
                'INSERT INTO calibration_report_acknowledgments (report_id, ack_id) VALUES (?, ?)',
                (report_id, ack_id),
            )
        return CalibrationReportRecord(
            report_id, round_id, width, calibration_id, result, parents, ack_id,
        )

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

    def get_calibrated(self, report_id: str) -> CalibrationReportRecord:
        row = self.connection.execute(
            '''SELECT r.round_id, r.width, r.calibration_id, r.pair_count, r.status,
                      r.lower_numerator, r.lower_denominator, r.upper_numerator, r.upper_denominator,
                      r.lower_a_num, r.lower_a_den, r.lower_b_num, r.lower_b_den,
                      r.upper_a_num, r.upper_a_den, r.upper_b_num, r.upper_b_den,
                      a.ack_id
               FROM calibration_reports AS r
               LEFT JOIN calibration_report_acknowledgments AS a USING (report_id)
               WHERE r.report_id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown report: {report_id}')
        (
            round_id, width, calibration_id, pair_count, status,
            lower_num, lower_den, upper_num, upper_den,
            la_num, la_den, lb_num, lb_den,
            ua_num, ua_den, ub_num, ub_den, ack_id,
        ) = row
        if ack_id is None:
            raise sqlite3.DatabaseError('stored calibration report is missing its acknowledgment')
        lower = _fraction_from_cells(lower_num, lower_den)
        upper = _fraction_from_cells(upper_num, upper_den)
        lower_at = self._point_from_cells(la_num, la_den, lb_num, lb_den)
        upper_at = self._point_from_cells(ua_num, ua_den, ub_num, ub_den)
        parent_rows = self.connection.execute(
            '''SELECT receipt_id, issue_id, revision_id, segment_id
               FROM calibration_report_parents WHERE report_id = ? ORDER BY position''',
            (report_id,),
        )
        parents = tuple(ReportParent(*parent) for parent in parent_rows)
        if not parents:
            raise sqlite3.DatabaseError('stored calibration report has no source receipts')
        result = CalibrationRangeResult(
            pair_count, status, lower, upper, lower_at, upper_at,
        )
        return CalibrationReportRecord(
            report_id, round_id, width, calibration_id, result, parents, ack_id,
        )

    @staticmethod
    def _point_from_cells(
        a_num: str | None, a_den: str | None, b_num: str | None, b_den: str | None,
    ) -> Point | None:
        a = _fraction_from_cells(a_num, a_den)
        if a is None:
            return None
        b = _fraction_from_cells(b_num, b_den)
        return a, b

    def get_any(self, report_id: str):
        row = self.connection.execute(
            'SELECT 1 FROM calibration_reports WHERE report_id = ?', (report_id,),
        ).fetchone()
        if row is not None:
            return self.get_calibrated(report_id)
        return self.get(report_id)

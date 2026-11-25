import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evidence.encode import encode_parcel
from evidence.freeze import freeze_revision
from evidence.store import IssueStore
from ledger_db import connect
from observations.ingest import record_segment
from observations.store import ObservationStore
from receipts.accept import accept_parcel
from receipts.store import ReceiptStore
from reports.publish import publish_report
from reports.retrieve import export_report
from reports.store import ReportStore
from rounds.registry import open_round
from rounds.store import RoundStore


class LedgerCase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='ledger-test-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source_path = root / 'station.sqlite'
        self.center_path = root / 'center.sqlite'
        directory_db = connect(root / 'directory.sqlite')
        self.addCleanup(directory_db.close)
        self.directory = RoundStore(directory_db)
        self.source = connect(self.source_path)
        self.addCleanup(self.source.close)
        self.station = ObservationStore(self.source)
        self.issues = IssueStore(self.source)
        self.open_center()
        for store in (self.directory, self.station, self.issues, self.receipts, self.reports):
            store.initialize()

    def open_center(self):
        self.center = connect(self.center_path)
        self.addCleanup(self.center.close)
        self.receipts = ReceiptStore(self.center)
        self.reports = ReportStore(self.center)

    def close_source(self):
        self.source.close()
        self.source_path.unlink()

    def segment(self, round_id, segment_id, first, values):
        return record_segment(
            self.directory, self.station, round_id, segment_id, first, first + len(values) - 1,
            enumerate(values, first),
        )

    def freeze(self, revision):
        return freeze_revision(self.directory, self.station, self.issues, revision.revision_id)

    def accept(self, parcel):
        return accept_parcel(self.directory, self.receipts, encode_parcel(parcel))

    def receive(self, revision):
        return self.accept(self.freeze(revision))

    def prepare(self, round_id, values, cut, first=1):
        open_round(self.directory, round_id, first, first + len(values) - 1)
        segments = (
            self.segment(round_id, 'day', first, values[:cut]),
            self.segment(round_id, 'night', first + cut, values[cut:]),
        )
        return tuple(self.receive(revision).receipt_id for revision in segments)

    def publish(self, round_id, width, receipt_ids):
        return publish_report(self.directory, self.receipts, self.reports, round_id, width, receipt_ids)

    def publication_counts(self):
        return (
            self.center.execute('SELECT count(*) FROM stability_reports').fetchone()[0],
            self.center.execute('SELECT count(*) FROM report_parents').fetchone()[0],
            self.center.execute('SELECT count(*) FROM report_acknowledgments').fetchone()[0],
        )

    def exported(self, report):
        return json.loads(export_report(self.reports, report.report_id))


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': paths,
        'oracle': oracle,
    }, sort_keys=True, ensure_ascii=False))

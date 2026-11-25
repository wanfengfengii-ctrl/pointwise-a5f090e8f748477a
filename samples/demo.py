from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from evidence.encode import encode_parcel
from evidence.freeze import freeze_revision
from evidence.store import IssueStore
from ledger_db import connect
from observations.corrections import amend_revision
from observations.ingest import record_segment
from observations.store import ObservationStore
from receipts.accept import accept_parcel
from receipts.store import ReceiptStore
from reports.publish import publish_report
from reports.retrieve import export_report, load_report
from reports.store import ReportStore
from rounds.registry import open_round
from rounds.store import RoundStore


def main() -> None:
    with TemporaryDirectory(prefix='instrument-check-') as workspace:
        root = Path(workspace)
        source_path = root / 'station.sqlite'
        center_path = root / 'center.sqlite'
        with closing(connect(root / 'directory.sqlite')) as directory_db:
            directory = RoundStore(directory_db)
            directory.initialize()
            round_id = 'reference-demo'
            open_round(directory, round_id, 1, 6)
            with closing(connect(center_path)) as center:
                receipts = ReceiptStore(center)
                reports = ReportStore(center)
                receipts.initialize()
                reports.initialize()
                with closing(connect(source_path)) as source:
                    station = ObservationStore(source)
                    issues = IssueStore(source)
                    station.initialize()
                    issues.initialize()
                    day = record_segment(directory, station, round_id, 'day', 1, 3, [(1, 0), (2, 0), (3, 2)])
                    night = record_segment(directory, station, round_id, 'night', 4, 6, [(4, 2), (5, 4), (6, 4)])
                    original_receipts = tuple(
                        accept_parcel(directory, receipts, encode_parcel(
                            freeze_revision(directory, station, issues, revision.revision_id),
                        )).receipt_id
                        for revision in (day, night)
                    )
                    corrected = amend_revision(station, day.revision_id, 3, 6)
                    corrected_parcel = freeze_revision(directory, station, issues, corrected.revision_id)
                    corrected_receipt = accept_parcel(directory, receipts, encode_parcel(corrected_parcel))
                source_path.unlink()

                original = publish_report(directory, receipts, reports, round_id, 2, original_receipts)
                actual = (original.result.pair_count, original.result.value)
                if actual != (2, Fraction(2)):
                    raise SystemExit(
                        f'STABILITY_MISMATCH round={round_id} width=2 '
                        f'expected_pairs=2 expected_value=2 actual_pairs={actual[0]} actual_value={actual[1]}'
                    )
                updated = publish_report(
                    directory, receipts, reports, round_id, 2,
                    (corrected_receipt.receipt_id, original_receipts[1]),
                )
                if (updated.result.pair_count, updated.result.value) != (2, Fraction(4)):
                    raise SystemExit('CORRECTION_MISMATCH: expected two pairs and 4 μm²')
            with closing(connect(center_path)) as center:
                reports = ReportStore(center)
                for label, record in (('original', original), ('corrected', updated)):
                    if load_report(reports, record.report_id) != record:
                        raise SystemExit(f'HISTORY_MISMATCH: {label}')
                    print(json.dumps(
                        {'edition': label, 'report': json.loads(export_report(reports, record.report_id))},
                        ensure_ascii=False,
                    ))


if __name__ == '__main__':
    main()

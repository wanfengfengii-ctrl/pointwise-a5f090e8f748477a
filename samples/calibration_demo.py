"""Calibration range demo: station freeze, center acceptance, close-down signing
and reopen retrieval for the shared ``(a, b)`` calibration parameters.

Run from the repository root with::

    python3 -B -m samples.calibration_demo
"""
from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from evidence.encode import encode_parcel
from evidence.freeze import freeze_calibrated_revision
from evidence.retrieve import load_issued_parcel
from evidence.store import IssueStore
from ledger_db import connect
from observations.ingest import record_segment
from observations.store import ObservationStore
from receipts.accept import accept_parcel
from receipts.retrieve import load_accepted
from receipts.selection import select_calibrated_receipts
from receipts.store import ReceiptStore
from reports.calibration_analysis import (
    _quadratic_parts,
    calibrated_differences,
    evaluate,
    qualify_calibrated_boxes,
)
from reports.publish import publish_calibrated_report
from reports.retrieve import export_report, load_report
from reports.store import ReportStore
from rounds.registry import load_round, open_round
from rounds.store import RoundStore

FIXTURE_PATH = Path(__file__).resolve().parent / 'calibration_ranges.json'


def _halfplanes(rows):
    return [tuple(Fraction(str(number)) for number in row) for row in rows]


def _build_scenario(root: Path, case: dict):
    round_id = f"calibration-{case['id']}"
    first = case['first']
    cut = case['cut']
    values = case['values']
    last = first + len(values) - 1
    calibration_id = f"calibration-{case['id']}"

    directory_db = connect(root / f'{case["id"]}-directory.sqlite')
    center_db = connect(root / f'{case["id"]}-center.sqlite')
    station_db = connect(root / f'{case["id"]}-station.sqlite')
    directory = RoundStore(directory_db)
    center = ReceiptStore(center_db)
    reports = ReportStore(center_db)
    station = ObservationStore(station_db)
    issues = IssueStore(station_db)
    for store in (directory, center, reports, station, issues):
        store.initialize()
    open_round(directory, round_id, first, last)

    def segment(segment_id, lo, hi, planes):
        entries = [
            (beat, None if values[beat - first] is None else Fraction(values[beat - first]))
            for beat in range(lo, hi + 1)
        ]
        revision = record_segment(directory, station, round_id, segment_id, lo, hi, entries)
        coefficients = {
            beat: (
                Fraction(case['coefficients'][beat - first][0]),
                Fraction(case['coefficients'][beat - first][1]),
            )
            for beat in range(lo, hi + 1)
            if case['coefficients'][beat - first] is not None
            and values[beat - first] is not None
        }
        parcel = freeze_calibrated_revision(
            directory, station, issues, revision.revision_id,
            calibration_id, coefficients, _halfplanes(planes),
        )
        # The issued fixed parcel can be re-claimed from the station library.
        assert load_issued_parcel(issues, parcel.issue_id).issue_id == parcel.issue_id
        return parcel

    day = segment('day', first, first + cut - 1, case['day'])
    night = segment('night', first + cut, last, case['night'])
    station_db.close()

    accepted = [
        accept_parcel(directory, center, encode_parcel(day)),
        accept_parcel(directory, center, encode_parcel(night)),
    ]
    receipt_ids = [item.receipt_id for item in accepted]
    report = publish_calibrated_report(
        directory, center, reports, round_id, case['width'], receipt_ids,
    )

    # The same receipts can also be signed at the other frozen box width when
    # the round grid qualifies.  Each width keeps its own report.
    alternate = None
    other_width = 4 if case['width'] == 2 else 2
    if (last - first + 1) % other_width == 0:
        alternate = publish_calibrated_report(
            directory, center, reports, round_id, other_width, receipt_ids,
        )

    # Independent substitution check for every measured witness.
    for signed in (report, alternate):
        if signed is None or signed.result.status != 'measured':
            continue
        spec = load_round(directory, round_id)
        selection = select_calibrated_receipts(center, spec, receipt_ids)
        boxes = qualify_calibrated_boxes(selection, signed.width)
        constant, linear, hessian = _quadratic_parts(calibrated_differences(boxes))
        for point, endpoint in (
            (signed.result.lower_at, signed.result.lower),
            (signed.result.upper_at, signed.result.upper),
        ):
            if not signed.result.domain.contains(point):
                raise SystemExit(f"WITNESS_DOMAIN {case['id']}: witness outside shared domain")
            if evaluate(point, constant, linear, hessian) != endpoint:
                raise SystemExit(f"WITNESS_VALUE {case['id']}: witness fails substitution check")

    paths = {
        'directory': root / f'{case["id"]}-directory.sqlite',
        'center': center_db,
        'center_path': root / f'{case["id"]}-center.sqlite',
    }
    directory_db.close()
    center_db.close()
    return round_id, calibration_id, accepted, report, alternate, paths


def _check_case(case: dict, report) -> None:
    result = report.result
    if result.status != case['status'] or result.pair_count != case['pairs']:
        raise SystemExit(
            f"CALIBRATION_MISMATCH {case['id']}: status/pair "
            f"{result.status}/{result.pair_count} != {case['status']}/{case['pairs']}"
        )
    if case['range'] is None:
        if (result.lower, result.upper, result.lower_at, result.upper_at) != (None, None, None, None):
            raise SystemExit(f"CALIBRATION_MISMATCH {case['id']}: null endpoints expected")
        return
    expected_lower = Fraction(case['range'][0])
    expected_upper = Fraction(case['range'][1])
    if result.lower != expected_lower or result.upper != expected_upper:
        raise SystemExit(
            f"CALIBRATION_MISMATCH {case['id']}: range "
            f"[{result.lower}, {result.upper}] != [{expected_lower}, {expected_upper}]"
        )


def _result_summary(report) -> dict:
    result = report.result
    return {
        'report_id': report.report_id,
        'width': report.width,
        'status': result.status,
        'pair_count': result.pair_count,
        'lower': str(result.lower) if result.lower is not None else None,
        'upper': str(result.upper) if result.upper is not None else None,
        'lower_at': (
            [str(result.lower_at[0]), str(result.lower_at[1])]
            if result.lower_at is not None else None
        ),
        'upper_at': (
            [str(result.upper_at[0]), str(result.upper_at[1])]
            if result.upper_at is not None else None
        ),
        'ack_id': report.ack_id,
    }


def main() -> None:
    cases = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='calibration-demo-') as workspace:
        root = Path(workspace)
        summaries = []
        for case in cases:
            round_id, calibration_id, accepted, report, alternate, paths = _build_scenario(root, case)
            _check_case(case, report)
            provenance = [
                {
                    'receipt_id': item.receipt_id,
                    'issue_id': item.parcel.issue_id,
                    'revision_id': item.parcel.revision_id,
                    'segment_id': item.parcel.segment_id,
                }
                for item in accepted
            ]
            summaries.append({
                'case': case['id'],
                'round_id': round_id,
                'calibration_id': calibration_id,
                'primary': _result_summary(report),
                'alternate_width': _result_summary(alternate) if alternate is not None else None,
                'provenance': provenance,
                'center_path': str(paths['center_path']),
            })

        # Reopen every center after close-down and retrieve finalized reports.
        for summary, case in zip(summaries, cases):
            with closing(connect(summary['center_path'])) as reopened_center:
                receipts = ReceiptStore(reopened_center)
                reports = ReportStore(reopened_center)
                receipts.initialize()
                reports.initialize()
                for key in ('primary', 'alternate_width'):
                    signed = summary[key]
                    if signed is None:
                        continue
                    reopened = load_report(reports, signed['report_id'])
                    exported = json.loads(export_report(reports, signed['report_id']))
                    if reopened.ack_id != signed['ack_id']:
                        raise SystemExit(f"REOPEN_MISMATCH {case['id']}: acknowledgment changed")
                    if exported['report_id'] != signed['report_id']:
                        raise SystemExit(f"REOPEN_MISMATCH {case['id']}: report ID changed")
                    if exported['calibration_id'] != summary['calibration_id']:
                        raise SystemExit(f"REOPEN_MISMATCH {case['id']}: calibration ID changed")
                    # Calibration evidence remains traceable through accepted receipts.
                    for parent in exported['parents']:
                        accepted_parcel = load_accepted(receipts, parent['receipt_id'])
                        if accepted_parcel.parcel.calibration_id != summary['calibration_id']:
                            raise SystemExit(
                                f"REOPEN_MISMATCH {case['id']}: receipt calibration lineage broken",
                            )
                    signed['reopened_export'] = exported

        for summary in summaries:
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        measured = sum(item['primary']['status'] == 'measured' for item in summaries)
        infeasible = sum(item['primary']['status'] == 'infeasible' for item in summaries)
        insufficient = sum(item['primary']['status'] == 'insufficient' for item in summaries)
        print(
            f'CALIBRATION_DEMO scenarios={len(summaries)} measured={measured} '
            f'infeasible={infeasible} insufficient={insufficient} result=PASS'
        )


if __name__ == '__main__':
    main()

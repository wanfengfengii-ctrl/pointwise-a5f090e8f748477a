from collections.abc import Iterable

from evidence.calibration import CalibratedFrozenParcel
from receipts.selection import select_calibrated_receipts, select_receipts
from receipts.store import ReceiptStore
from reports.analysis import analyze_stability
from reports.calibration_analysis import analyze_calibrated_range
from reports.store import (
    CalibrationReportRecord,
    ReportParent,
    ReportRecord,
    ReportStore,
)
from rounds.protocol import require_box_width
from rounds.registry import load_round
from rounds.store import RoundStore


def _parents(selection) -> tuple[ReportParent, ...]:
    return tuple(
        ReportParent(
            item.receipt_id, item.parcel.issue_id,
            item.parcel.revision_id, item.parcel.segment_id,
        )
        for item in selection.accepted
    )


def publish_report(
    directory: RoundStore,
    receipts: ReceiptStore,
    reports: ReportStore,
    round_id: str,
    width: int,
    receipt_ids: Iterable[str],
) -> ReportRecord:
    specification = load_round(directory, round_id)
    require_box_width(specification.protocol, width)
    selection = select_receipts(receipts, specification, receipt_ids)
    if any(isinstance(item.parcel, CalibratedFrozenParcel) for item in selection.accepted):
        raise ValueError('point reports require version 1 receipts')
    result = analyze_stability(selection, width)
    return reports.save(round_id, width, result, _parents(selection))


def publish_calibrated_report(
    directory: RoundStore,
    receipts: ReceiptStore,
    reports: ReportStore,
    round_id: str,
    width: int,
    receipt_ids: Iterable[str],
) -> CalibrationReportRecord:
    specification = load_round(directory, round_id)
    require_box_width(specification.protocol, width)
    selection = select_calibrated_receipts(receipts, specification, receipt_ids)
    calibration_id = selection.accepted[0].parcel.calibration_id
    result = analyze_calibrated_range(selection, width)
    return reports.save_calibrated(
        round_id, width, calibration_id, result, _parents(selection),
    )

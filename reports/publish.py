from collections.abc import Iterable

from receipts.selection import select_receipts
from receipts.store import ReceiptStore
from reports.analysis import analyze_stability
from reports.store import ReportParent, ReportRecord, ReportStore
from rounds.protocol import require_box_width
from rounds.registry import load_round
from rounds.store import RoundStore


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
    result = analyze_stability(selection, width)
    parents = tuple(
        ReportParent(item.receipt_id, item.parcel.issue_id, item.parcel.revision_id, item.parcel.segment_id)
        for item in selection.accepted
    )
    return reports.save(round_id, width, result, parents)

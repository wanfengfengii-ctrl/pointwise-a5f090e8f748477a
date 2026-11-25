from collections.abc import Iterable
from dataclasses import dataclass

from evidence.calibration import CalibratedFrozenParcel
from receipts.retrieve import AcceptedParcel, load_accepted_sequence
from receipts.store import ReceiptStore
from rounds.grid import BeatRange
from rounds.validation import RoundSpec, require_matching_round


@dataclass(frozen=True)
class ReceiptSelection:
    round_spec: RoundSpec
    accepted: tuple[AcceptedParcel, ...]


def require_exact_coverage(whole: BeatRange, ranges: Iterable[BeatRange]) -> None:
    next_beat = whole.first
    for coverage in sorted(ranges, key=lambda item: item.first):
        if not whole.contains_range(coverage):
            raise ValueError('receipt coverage lies outside the round')
        if coverage.first < next_beat:
            raise ValueError(f'overlapping receipt coverage at beat {coverage.first}')
        if coverage.first > next_beat:
            raise ValueError(f'receipt coverage gap at beat {next_beat}')
        next_beat = coverage.last + 1
    if next_beat <= whole.last:
        raise ValueError(f'receipt coverage gap at beat {next_beat}')


def select_receipts(
    receipts: ReceiptStore, specification: RoundSpec, receipt_ids: Iterable[str],
) -> ReceiptSelection:
    accepted = load_accepted_sequence(receipts, receipt_ids)
    for item in accepted:
        require_matching_round(specification, item.parcel.round_spec)
    require_exact_coverage(specification.beats, (item.parcel.coverage for item in accepted))
    return ReceiptSelection(specification, accepted)


def select_calibrated_receipts(
    receipts: ReceiptStore, specification: RoundSpec, receipt_ids: Iterable[str],
) -> ReceiptSelection:
    accepted = load_accepted_sequence(receipts, receipt_ids)
    calibration_ids = set()
    for item in accepted:
        parcel = item.parcel
        if not isinstance(parcel, CalibratedFrozenParcel):
            raise ValueError('calibrated reports require version 2 receipts')
        require_matching_round(specification, parcel.round_spec)
        calibration_ids.add(parcel.calibration_id)
    if len(calibration_ids) != 1:
        raise ValueError('all calibrated receipts must share one calibration ID')
    require_exact_coverage(specification.beats, (item.parcel.coverage for item in accepted))
    return ReceiptSelection(specification, accepted)

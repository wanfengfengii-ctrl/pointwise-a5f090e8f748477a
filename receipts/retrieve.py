from collections.abc import Iterable
from dataclasses import dataclass
import sqlite3

from evidence.encode import FrozenParcel, decode_parcel
from receipts.store import ReceiptStore
from rounds.validation import require_identifier


@dataclass(frozen=True)
class AcceptedParcel:
    receipt_id: str
    ack_id: str
    parcel: FrozenParcel
    body: str


def load_accepted(receipts: ReceiptStore, receipt_id: str) -> AcceptedParcel:
    require_identifier(receipt_id, 'receipt ID')
    issue_id, ack_id, body = receipts.get(receipt_id)
    parcel = decode_parcel(body)
    if parcel.issue_id != issue_id:
        raise sqlite3.DatabaseError('stored receipt identity does not match its body')
    return AcceptedParcel(receipt_id, ack_id, parcel, body)


def load_accepted_sequence(
    receipts: ReceiptStore, receipt_ids: Iterable[str],
) -> tuple[AcceptedParcel, ...]:
    if isinstance(receipt_ids, (str, bytes)) or not isinstance(receipt_ids, Iterable):
        raise ValueError('receipt IDs must be given as an ordered sequence')
    if isinstance(receipt_ids, (set, frozenset, dict)):
        raise ValueError('receipt IDs must be given as an ordered sequence')
    return tuple(load_accepted(receipts, receipt_id) for receipt_id in receipt_ids)

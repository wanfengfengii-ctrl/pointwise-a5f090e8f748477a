from evidence.encode import encode_parcel
from receipts.retrieve import AcceptedParcel
from receipts.store import ReceiptStore
from receipts.verify import verify_parcel
from rounds.store import RoundStore


def accept_parcel(directory: RoundStore, receipts: ReceiptStore, body: str) -> AcceptedParcel:
    parcel = verify_parcel(directory, body)
    canonical_body = encode_parcel(parcel)
    receipt_id, ack_id = receipts.accept_once(parcel.issue_id, canonical_body)
    return AcceptedParcel(receipt_id, ack_id, parcel, canonical_body)

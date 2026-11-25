import sqlite3

from evidence.encode import FrozenParcel, decode_parcel
from evidence.store import IssueStore
from rounds.validation import require_identifier


def load_issued_parcel(issues: IssueStore, issue_id: str) -> FrozenParcel:
    require_identifier(issue_id, 'issue ID')
    revision_id, body = issues.get(issue_id)
    parcel = decode_parcel(body)
    if parcel.issue_id != issue_id or parcel.revision_id != revision_id:
        raise sqlite3.DatabaseError('stored issue identity does not match its body')
    return parcel

from uuid import uuid4

from evidence.coverage import project_revision_coverage
from evidence.encode import FrozenParcel, encode_parcel
from evidence.store import IssueStore
from observations.read import load_revision
from observations.store import ObservationStore
from rounds.store import RoundStore


def freeze_revision(
    directory: RoundStore, station: ObservationStore, issues: IssueStore, revision_id: str,
) -> FrozenParcel:
    snapshot = load_revision(directory, station, revision_id)
    revision = snapshot.revision
    missing, contributions = project_revision_coverage(snapshot)
    parcel = FrozenParcel(
        f'issue-{uuid4().hex}', revision.revision_id, revision.segment_id,
        snapshot.round_spec, revision.coverage, missing, contributions,
    )
    issues.insert(parcel.issue_id, parcel.revision_id, encode_parcel(parcel))
    return parcel

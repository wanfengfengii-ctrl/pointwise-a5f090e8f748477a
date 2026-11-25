from dataclasses import dataclass

from observations.revisions import Revision
from observations.store import ObservationStore
from rounds.registry import load_round
from rounds.store import RoundStore
from rounds.validation import RoundSpec, require_identifier


@dataclass(frozen=True)
class RevisionSnapshot:
    round_spec: RoundSpec
    revision: Revision


def load_revision(
    directory: RoundStore, station: ObservationStore, revision_id: str,
) -> RevisionSnapshot:
    require_identifier(revision_id, 'revision ID')
    revision = station.get_revision(revision_id)
    return RevisionSnapshot(load_round(directory, revision.round_id), revision)

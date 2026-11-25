from observations.revisions import Reading, Revision, build_next_revision
from observations.store import ObservationStore
from rounds.validation import require_identifier


def amend_revision(
    station: ObservationStore, base_revision_id: str, beat: int, value: Reading,
) -> Revision:
    require_identifier(base_revision_id, 'base revision ID')
    base = station.get_revision(base_revision_id)
    revised = build_next_revision(base, beat, value)
    return station.append_if_current(revised)

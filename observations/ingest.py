from collections.abc import Iterable

from observations.revisions import (
    Observation, Reading, Revision, build_initial_revision, normalize_observation,
)
from observations.store import ObservationStore
from rounds.grid import BeatRange
from rounds.registry import load_round
from rounds.store import RoundStore
from rounds.validation import require_identifier


def validate_segment_entries(
    coverage: BeatRange, entries: Iterable[tuple[int, Reading]],
) -> tuple[Observation, ...]:
    observations = {}
    try:
        iterator = iter(entries)
    except TypeError as error:
        raise ValueError('entries must be an iterable of beat and reading pairs') from error
    for entry in iterator:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError('each entry must contain one beat and one reading')
        beat, value = entry
        if beat not in coverage:
            raise ValueError(f'beat {beat!r} is outside the segment')
        if beat in observations:
            raise ValueError(f'duplicate beat: {beat}')
        observations[beat] = normalize_observation(beat, value)
    if len(observations) != coverage.length:
        raise ValueError('entries do not cover every beat in the segment')
    return tuple(observations[beat] for beat in sorted(observations))


def record_segment(
    directory: RoundStore,
    station: ObservationStore,
    round_id: str,
    segment_id: str,
    first: int,
    last: int,
    entries: Iterable[tuple[int, Reading]],
) -> Revision:
    specification = load_round(directory, round_id)
    require_identifier(segment_id, 'segment ID')
    coverage = BeatRange(first, last)
    if not specification.beats.contains_range(coverage):
        raise ValueError('segment coverage is outside the round')
    observations = validate_segment_entries(coverage, entries)
    revision = build_initial_revision(round_id, segment_id, coverage, observations)
    return station.insert_initial(revision)

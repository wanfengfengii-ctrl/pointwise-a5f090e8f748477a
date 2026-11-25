from dataclasses import dataclass
from fractions import Fraction
from uuid import uuid4

from rounds.grid import BeatRange


Reading = Fraction | int | str | None


@dataclass(frozen=True)
class Observation:
    beat: int
    value: Fraction | None


@dataclass(frozen=True)
class Revision:
    revision_id: str
    round_id: str
    segment_id: str
    coverage: BeatRange
    predecessor_id: str | None
    entries: tuple[Observation, ...]


def normalize_observation(beat: int, value: Reading) -> Observation:
    if type(beat) is not int:
        raise ValueError('observation beat must be an integer')
    if value is None:
        return Observation(beat, None)
    if isinstance(value, Fraction):
        return Observation(beat, value)
    if type(value) not in (int, str):
        raise ValueError(f'beat {beat} requires an exact rational reading or None')
    try:
        return Observation(beat, Fraction(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'beat {beat} has an invalid rational reading') from error


def build_initial_revision(
    round_id: str,
    segment_id: str,
    coverage: BeatRange,
    entries: tuple[Observation, ...],
) -> Revision:
    return Revision(
        f'rev-{uuid4().hex}', round_id, segment_id, coverage, None, entries,
    )


def build_next_revision(base: Revision, beat: int, value: Reading) -> Revision:
    if beat not in base.coverage:
        raise ValueError('correction beat is outside the segment')
    replacement = normalize_observation(beat, value)
    entries = tuple(replacement if item.beat == beat else item for item in base.entries)
    return Revision(
        f'rev-{uuid4().hex}', base.round_id, base.segment_id,
        base.coverage, base.revision_id, entries,
    )

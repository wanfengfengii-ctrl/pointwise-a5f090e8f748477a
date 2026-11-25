from collections.abc import Mapping
from fractions import Fraction
from uuid import uuid4

from evidence.calibration import (
    CalibratedFrozenParcel,
    HalfPlane,
    normalize_halfplanes,
    rational_input,
)
from evidence.coverage import project_calibrated_coverage, project_revision_coverage
from evidence.encode import FrozenParcel, encode_parcel
from evidence.store import IssueStore
from observations.read import load_revision
from observations.store import ObservationStore
from rounds.store import RoundStore
from rounds.validation import require_identifier


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


def _normalize_coefficients(
    snapshot, coefficients: object,
) -> dict[int, tuple[Fraction, Fraction]]:
    if not isinstance(coefficients, Mapping):
        raise ValueError('coefficients must be a mapping keyed by integer beat number')
    normalized = {}
    observed = {entry.beat: entry.value for entry in snapshot.revision.entries}
    for beat, pair in coefficients.items():
        if type(beat) is not int or beat not in observed:
            raise ValueError('coefficient beats must be observed beats inside the revision')
        if observed[beat] is None:
            raise ValueError('missing beats must not carry calibration coefficients')
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError('each coefficient must be an (alpha, beta) pair')
        normalized[beat] = (
            rational_input(pair[0], f'coefficient alpha at beat {beat}'),
            rational_input(pair[1], f'coefficient beta at beat {beat}'),
        )
    for beat, value in observed.items():
        if value is not None and beat not in normalized:
            raise ValueError(f'observed beat {beat} is missing calibration coefficients')
    return normalized


def freeze_calibrated_revision(
    directory: RoundStore,
    station: ObservationStore,
    issues: IssueStore,
    revision_id: str,
    calibration_id: str,
    coefficients: Mapping[int, tuple[Fraction, Fraction]],
    halfplanes: list[tuple[Fraction, Fraction, Fraction]],
) -> CalibratedFrozenParcel:
    require_identifier(calibration_id, 'calibration ID')
    snapshot = load_revision(directory, station, revision_id)
    normalized_coefficients = _normalize_coefficients(snapshot, coefficients)
    planes: tuple[HalfPlane, ...] = normalize_halfplanes(halfplanes)
    missing, contributions = project_calibrated_coverage(snapshot, normalized_coefficients)
    revision = snapshot.revision
    parcel = CalibratedFrozenParcel(
        f'issue-{uuid4().hex}',
        revision.revision_id,
        revision.segment_id,
        snapshot.round_spec,
        revision.coverage,
        missing,
        contributions,
        calibration_id,
        planes,
    )
    issues.insert(parcel.issue_id, parcel.revision_id, encode_parcel(parcel))
    return parcel

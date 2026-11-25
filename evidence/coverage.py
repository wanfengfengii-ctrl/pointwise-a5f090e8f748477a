from collections.abc import Mapping
from fractions import Fraction

from evidence.calibration import CalibratedContribution
from evidence.encode import BoxContribution
from observations.read import RevisionSnapshot
from rounds.grid import BeatRange, intersecting_boxes


def summarize_box_fragment(
    snapshot: RevisionSnapshot, width: int, index: int, fragment: BeatRange,
) -> BoxContribution:
    revision = snapshot.revision
    offset = fragment.first - revision.coverage.first
    entries = revision.entries[offset:offset + fragment.length]
    total = sum((entry.value for entry in entries if entry.value is not None), Fraction(0))
    return BoxContribution(width, index, total)


def summarize_calibrated_fragment(
    snapshot: RevisionSnapshot,
    coefficients: Mapping[int, tuple[Fraction, Fraction]],
    width: int,
    index: int,
    fragment: BeatRange,
) -> CalibratedContribution:
    revision = snapshot.revision
    offset = fragment.first - revision.coverage.first
    entries = revision.entries[offset:offset + fragment.length]
    total = Fraction(0)
    alpha_sum = Fraction(0)
    beta_sum = Fraction(0)
    for entry in entries:
        if entry.value is None:
            continue
        total += entry.value
        alpha, beta = coefficients[entry.beat]
        alpha_sum += alpha
        beta_sum += beta
    return CalibratedContribution(width, index, total, alpha_sum, beta_sum)


def project_revision_coverage(
    snapshot: RevisionSnapshot,
) -> tuple[tuple[int, ...], tuple[BoxContribution, ...]]:
    revision = snapshot.revision
    missing = tuple(entry.beat for entry in revision.entries if entry.value is None)
    contributions = []
    for width in snapshot.round_spec.protocol.box_widths:
        fragments = intersecting_boxes(snapshot.round_spec.beats.first, width, revision.coverage)
        for index, fragment in fragments:
            contributions.append(summarize_box_fragment(snapshot, width, index, fragment))
    return missing, tuple(contributions)


def project_calibrated_coverage(
    snapshot: RevisionSnapshot,
    coefficients: Mapping[int, tuple[Fraction, Fraction]],
) -> tuple[tuple[int, ...], tuple[CalibratedContribution, ...]]:
    revision = snapshot.revision
    missing = tuple(entry.beat for entry in revision.entries if entry.value is None)
    contributions = []
    for width in snapshot.round_spec.protocol.box_widths:
        fragments = intersecting_boxes(snapshot.round_spec.beats.first, width, revision.coverage)
        for index, fragment in fragments:
            contributions.append(
                summarize_calibrated_fragment(snapshot, coefficients, width, index, fragment),
            )
    return missing, tuple(contributions)

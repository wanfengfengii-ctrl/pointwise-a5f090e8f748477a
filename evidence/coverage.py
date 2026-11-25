from fractions import Fraction

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


def project_revision_coverage(
    snapshot: RevisionSnapshot,
) -> tuple[tuple[int, ...], tuple[BoxContribution, ...]]:
    revision = snapshot.revision
    specification = snapshot.round_spec
    missing = tuple(entry.beat for entry in revision.entries if entry.value is None)
    contributions = []
    for width in specification.protocol.box_widths:
        fragments = intersecting_boxes(specification.beats.first, width, revision.coverage)
        for index, fragment in fragments:
            contributions.append(summarize_box_fragment(snapshot, width, index, fragment))
    return missing, tuple(contributions)

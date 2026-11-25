from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from receipts.selection import ReceiptSelection
from rounds.grid import box_index, box_span
from rounds.protocol import require_box_width


@dataclass(frozen=True)
class QualifiedBox:
    index: int
    mean: Fraction


def qualify_boxes(selection: ReceiptSelection, width: int) -> tuple[QualifiedBox, ...]:
    specification = selection.round_spec
    require_box_width(specification.protocol, width)
    origin = specification.beats.first
    counts = Counter()
    totals = defaultdict(Fraction)
    for accepted in selection.accepted:
        parcel = accepted.parcel
        missing = Counter(box_index(origin, width, beat) for beat in parcel.missing)
        for item in parcel.contributions:
            if item.width != width:
                continue
            span = box_span(origin, width, item.index)
            fragment = span.intersection(parcel.coverage)
            if fragment is None:
                raise ValueError('accepted contribution has no matching coverage')
            counts[item.index] += fragment.length - missing[item.index]
            totals[item.index] += item.total
    return tuple(
        QualifiedBox(index, totals[index] / width)
        for index in sorted(counts)
        if counts[index] == width
    )


def adjacent_pairs(boxes: tuple[QualifiedBox, ...]) -> Iterator[tuple[QualifiedBox, QualifiedBox]]:
    for left, right in zip(boxes, boxes[1:]):
        if right.index == left.index + 1:
            yield left, right

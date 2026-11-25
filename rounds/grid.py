from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class BeatRange:
    first: int
    last: int

    def __post_init__(self) -> None:
        if type(self.first) is not int or type(self.last) is not int:
            raise ValueError('beat boundaries must be integers')
        if self.first > self.last:
            raise ValueError('first beat must be at or before last beat')

    @property
    def length(self) -> int:
        return self.last - self.first + 1

    def __contains__(self, beat: object) -> bool:
        return type(beat) is int and self.first <= beat <= self.last

    def contains_range(self, other: 'BeatRange') -> bool:
        return self.first <= other.first and other.last <= self.last

    def intersection(self, other: 'BeatRange') -> 'BeatRange | None':
        first = max(self.first, other.first)
        last = min(self.last, other.last)
        if first > last:
            return None
        return BeatRange(first, last)


def _check_width(width: int) -> None:
    if type(width) is not int or width < 1:
        raise ValueError('grid width must be a positive integer')


def box_index(origin: int, width: int, beat: int) -> int:
    _check_width(width)
    return (beat - origin) // width


def box_span(origin: int, width: int, index: int) -> BeatRange:
    _check_width(width)
    first = origin + width * index
    return BeatRange(first, first + width - 1)


def intersecting_boxes(origin: int, width: int, coverage: BeatRange) -> Iterator[tuple[int, BeatRange]]:
    first = box_index(origin, width, coverage.first)
    last = box_index(origin, width, coverage.last)
    for index in range(first, last + 1):
        fragment = box_span(origin, width, index).intersection(coverage)
        if fragment is not None:
            yield index, fragment

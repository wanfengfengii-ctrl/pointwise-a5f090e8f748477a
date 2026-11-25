from dataclasses import dataclass
from fractions import Fraction

from receipts.selection import ReceiptSelection
from reports.qualification import adjacent_pairs, qualify_boxes


@dataclass(frozen=True)
class StabilityResult:
    pair_count: int
    value: Fraction | None

    def __post_init__(self) -> None:
        if type(self.pair_count) is not int or self.pair_count < 0:
            raise ValueError('pair count must be a nonnegative integer')
        if (self.pair_count == 0) != (self.value is None):
            raise ValueError('only a result with valid pairs has a value')
        if self.value is not None and (not isinstance(self.value, Fraction) or self.value < 0):
            raise ValueError('stability value must be a nonnegative fraction')

    @property
    def status(self) -> str:
        return 'measured' if self.pair_count else 'insufficient'


def analyze_stability(selection: ReceiptSelection, width: int) -> StabilityResult:
    boxes = qualify_boxes(selection, width)
    pair_count = 0
    sum_squared = Fraction(0)
    for left, right in adjacent_pairs(boxes):
        difference = right.mean - left.mean
        sum_squared += difference * difference
        pair_count += 1
    value = sum_squared / (2 * pair_count) if pair_count else None
    return StabilityResult(pair_count, value)

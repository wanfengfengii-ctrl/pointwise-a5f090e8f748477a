"""Range analysis for calibrated V2 receipts.

Each observed reading ``x`` is explained by the shared parameters as
``x + alpha*a + beta*b``.  The stability statistic keeps the V1 definition:
the mean of squared differences between adjacent full-width box means,
divided by two.  Its exact minimum and maximum over the shared closed
feasible domain are returned together with reachable witnesses.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction

from receipts.selection import ReceiptSelection
from reports.domain import FeasibleDomain, Point, build_domain
from reports.qualification import adjacent_pairs
from rounds.grid import box_index, box_span
from rounds.protocol import require_box_width


@dataclass(frozen=True)
class CalibratedBox:
    index: int
    total: Fraction
    alpha_sum: Fraction
    beta_sum: Fraction
    mean: Fraction
    alpha_mean: Fraction
    beta_mean: Fraction


@dataclass(frozen=True)
class CalibratedDifference:
    index: int
    nominal: Fraction
    alpha: Fraction
    beta: Fraction


def qualify_calibrated_boxes(
    selection: ReceiptSelection, width: int,
) -> tuple[CalibratedBox, ...]:
    specification = selection.round_spec
    require_box_width(specification.protocol, width)
    origin = specification.beats.first
    counts = Counter()
    totals = defaultdict(Fraction)
    alpha_totals = defaultdict(Fraction)
    beta_totals = defaultdict(Fraction)
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
            alpha_totals[item.index] += item.alpha_sum
            beta_totals[item.index] += item.beta_sum
    boxes = []
    for index in sorted(counts):
        if counts[index] != width:
            continue
        boxes.append(CalibratedBox(
            index,
            totals[index],
            alpha_totals[index],
            beta_totals[index],
            totals[index] / width,
            alpha_totals[index] / width,
            beta_totals[index] / width,
        ))
    return tuple(boxes)


def calibrated_differences(boxes: tuple[CalibratedBox, ...]) -> tuple[CalibratedDifference, ...]:
    differences = []
    for left, right in adjacent_pairs(boxes):
        differences.append(CalibratedDifference(
            left.index,
            right.mean - left.mean,
            right.alpha_mean - left.alpha_mean,
            right.beta_mean - left.beta_mean,
        ))
    return tuple(differences)


@dataclass(frozen=True)
class CalibrationRangeResult:
    pair_count: int
    status: str
    lower: Fraction | None
    upper: Fraction | None
    lower_at: Point | None
    upper_at: Point | None
    domain: FeasibleDomain | None = None

    def __post_init__(self) -> None:
        if type(self.pair_count) is not int or self.pair_count < 0:
            raise ValueError('pair count must be a nonnegative integer')
        if self.status not in ('measured', 'insufficient', 'infeasible'):
            raise ValueError('invalid calibration result status')
        if self.status == 'measured':
            if self.pair_count == 0:
                raise ValueError('measured result requires at least one pair')
            for name in ('lower', 'upper'):
                value = getattr(self, name)
                if not isinstance(value, Fraction) or value < 0:
                    raise ValueError(f'{name} must be a nonnegative fraction')
            if self.lower > self.upper:
                raise ValueError('lower endpoint must not exceed upper endpoint')
            for name in ('lower_at', 'upper_at'):
                point = getattr(self, name)
                if (
                    not isinstance(point, tuple) or len(point) != 2
                    or not all(isinstance(coordinate, Fraction) for coordinate in point)
                ):
                    raise ValueError(f'{name} must be an (a, b) fraction pair')
        elif any(getattr(self, name) is not None for name in ('lower', 'upper', 'lower_at', 'upper_at')):
            raise ValueError('non-measured results must not carry endpoint values')


def _quadratic_parts(differences: tuple[CalibratedDifference, ...]) -> tuple:
    """Return constant, linear vector and Hessian of the mean squared value."""
    pair_count = len(differences)
    constant = Fraction(0)
    linear = [Fraction(0), Fraction(0)]
    hessian = [[Fraction(0), Fraction(0)], [Fraction(0), Fraction(0)]]
    for difference in differences:
        d0 = difference.nominal
        da = difference.alpha
        db = difference.beta
        constant += d0 * d0
        linear[0] += 2 * d0 * da
        linear[1] += 2 * d0 * db
        hessian[0][0] += da * da
        hessian[0][1] += da * db
        hessian[1][1] += db * db
    hessian[1][0] = hessian[0][1]
    scale = Fraction(1, 2 * pair_count)
    return (
        constant * scale,
        (linear[0] * scale, linear[1] * scale),
        ((hessian[0][0] * scale, hessian[0][1] * scale),
         (hessian[1][0] * scale, hessian[1][1] * scale)),
    )


def evaluate(
    point: Point,
    constant: Fraction,
    linear: tuple[Fraction, Fraction],
    hessian: tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]],
) -> Fraction:
    a, b = point
    return (
        constant
        + linear[0] * a + linear[1] * b
        + hessian[0][0] * a * a
        + (hessian[0][1] + hessian[1][0]) * a * b
        + hessian[1][1] * b * b
    )


def _edge_stationary_points(
    start: Point,
    end: Point,
    constant: Fraction,
    linear: tuple[Fraction, Fraction],
    hessian: tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]],
) -> tuple[Point, ...]:
    direction = (end[0] - start[0], end[1] - start[1])
    cross = hessian[0][1] + hessian[1][0]
    # f(start + t*direction) is quadratic in t in [0, 1].
    second = (
        hessian[0][0] * direction[0] * direction[0]
        + cross * direction[0] * direction[1]
        + hessian[1][1] * direction[1] * direction[1]
    )
    if second == 0:
        return ()
    gradient_at_start = (
        linear[0] + 2 * hessian[0][0] * start[0] + cross * start[1],
        linear[1] + cross * start[0] + 2 * hessian[1][1] * start[1],
    )
    first = gradient_at_start[0] * direction[0] + gradient_at_start[1] * direction[1]
    t_star = -first / (2 * second)
    if t_star <= 0 or t_star >= 1:
        return ()
    return ((start[0] + t_star * direction[0], start[1] + t_star * direction[1]),)


def _interior_stationary_point(
    linear: tuple[Fraction, Fraction],
    hessian: tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]],
) -> Point | None:
    determinant = hessian[0][0] * hessian[1][1] - hessian[0][1] * hessian[1][0]
    if determinant == 0:
        return None
    # Solve H x = -linear/2 ... but linear already carries the factor 2.
    rhs = (-linear[0] / 2, -linear[1] / 2)
    a = (rhs[0] * hessian[1][1] - hessian[0][1] * rhs[1]) / determinant
    b = (hessian[0][0] * rhs[1] - rhs[0] * hessian[1][0]) / determinant
    return a, b


def analyze_calibrated_range(
    selection: ReceiptSelection, width: int,
) -> CalibrationRangeResult:
    boxes = qualify_calibrated_boxes(selection, width)
    differences = calibrated_differences(boxes)
    pair_count = len(differences)
    halfplanes = tuple(plane for accepted in selection.accepted for plane in accepted.parcel.halfplanes)
    domain = build_domain(halfplanes)
    if domain.is_empty:
        return CalibrationRangeResult(pair_count, 'infeasible', None, None, None, None, domain)
    if pair_count == 0:
        return CalibrationRangeResult(0, 'insufficient', None, None, None, None, domain)

    constant, linear, hessian = _quadratic_parts(differences)
    candidates = set(domain.vertices)
    for start, end in domain.edges():
        candidates.update(_edge_stationary_points(start, end, constant, linear, hessian))
    if domain.kind == 'polygon':
        interior = _interior_stationary_point(linear, hessian)
        if interior is not None and domain.contains(interior):
            candidates.add(interior)

    minimum = None
    minimum_at = None
    maximum = None
    maximum_at = None
    for point in sorted(candidates):
        if not domain.contains(point):
            continue
        value = evaluate(point, constant, linear, hessian)
        if minimum is None or value < minimum:
            minimum = value
            minimum_at = point
        if maximum is None or value > maximum:
            maximum = value
            maximum_at = point
    return CalibrationRangeResult(
        pair_count, 'measured', minimum, maximum, minimum_at, maximum_at, domain,
    )

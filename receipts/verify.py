from collections import Counter, defaultdict
from fractions import Fraction

from evidence.calibration import CalibratedFrozenParcel
from evidence.encode import FrozenParcel, decode_parcel
from rounds.grid import box_index, box_span, intersecting_boxes
from rounds.registry import load_round
from rounds.store import RoundStore
from rounds.validation import require_matching_round


def validate_parcel_coverage(parcel: FrozenParcel) -> None:
    specification = parcel.round_spec
    coverage = parcel.coverage
    if not specification.beats.contains_range(coverage):
        raise ValueError('parcel coverage is outside the round')
    missing = set(parcel.missing)
    if len(missing) != len(parcel.missing) or any(beat not in coverage for beat in missing):
        raise ValueError('missing beats must be unique and inside the parcel coverage')

    totals = {}
    for contribution in parcel.contributions:
        key = (contribution.width, contribution.index)
        if key in totals:
            raise ValueError('duplicate box contribution')
        totals[key] = contribution.total

    origin = specification.beats.first
    expected_count = 0
    for width in specification.protocol.box_widths:
        missing_counts = Counter(box_index(origin, width, beat) for beat in missing)
        first = box_index(origin, width, coverage.first)
        last = box_index(origin, width, coverage.last)
        expected_count += last - first + 1
        if expected_count > len(totals):
            raise ValueError('missing contribution for a box fragment')
        for index, fragment in intersecting_boxes(origin, width, coverage):
            key = (width, index)
            if key not in totals:
                raise ValueError('missing contribution for a box fragment')
            if missing_counts[index] == fragment.length and totals[key] != 0:
                raise ValueError('fully missing fragment must have a zero sum')
    if expected_count != len(totals):
        raise ValueError('box contribution is outside the parcel grid')

    paired_sums = defaultdict(Fraction)
    for (width, index), total in totals.items():
        if width == 2:
            first = box_span(origin, width, index).first
            paired_sums[box_index(origin, 4, first)] += total
    for (width, index), total in totals.items():
        if width == 4 and total != paired_sums[index]:
            raise ValueError('two-beat and four-beat contributions disagree')


def validate_calibrated_parcel_coverage(parcel: CalibratedFrozenParcel) -> None:
    specification = parcel.round_spec
    coverage = parcel.coverage
    if not specification.beats.contains_range(coverage):
        raise ValueError('parcel coverage is outside the round')
    missing = set(parcel.missing)
    if len(missing) != len(parcel.missing) or any(beat not in coverage for beat in missing):
        raise ValueError('missing beats must be unique and inside the parcel coverage')

    totals = {}
    alpha_totals = {}
    beta_totals = {}
    for contribution in parcel.contributions:
        key = (contribution.width, contribution.index)
        if key in totals:
            raise ValueError('duplicate box contribution')
        totals[key] = contribution.total
        alpha_totals[key] = contribution.alpha_sum
        beta_totals[key] = contribution.beta_sum

    origin = specification.beats.first
    expected_count = 0
    for width in specification.protocol.box_widths:
        missing_counts = Counter(box_index(origin, width, beat) for beat in missing)
        first_index = box_index(origin, width, coverage.first)
        last_index = box_index(origin, width, coverage.last)
        expected_count += last_index - first_index + 1
        if expected_count > len(totals):
            raise ValueError('missing contribution for a box fragment')
        for index, fragment in intersecting_boxes(origin, width, coverage):
            key = (width, index)
            if key not in totals:
                raise ValueError('missing contribution for a box fragment')
            if missing_counts[index] == fragment.length:
                if (
                    totals[key] != 0
                    or alpha_totals[key] != 0
                    or beta_totals[key] != 0
                ):
                    raise ValueError('fully missing fragment must have zero sums')
    if expected_count != len(totals):
        raise ValueError('box contribution is outside the parcel grid')

    paired = {name: defaultdict(Fraction) for name in ('total', 'alpha', 'beta')}
    source = {'total': totals, 'alpha': alpha_totals, 'beta': beta_totals}
    for (width, index) in totals:
        if width == 2:
            first = box_span(origin, width, index).first
            merged = box_index(origin, 4, first)
            for name in paired:
                paired[name][merged] += source[name][(width, index)]
    for (width, index) in totals:
        if width == 4:
            for name in paired:
                if source[name][(width, index)] != paired[name][index]:
                    raise ValueError('two-beat and four-beat contributions disagree')


def verify_parcel(directory: RoundStore, body: str) -> FrozenParcel | CalibratedFrozenParcel:
    parcel = decode_parcel(body)
    try:
        registered = load_round(directory, parcel.round_spec.round_id)
    except LookupError as error:
        raise ValueError('parcel round is not registered') from error
    require_matching_round(registered, parcel.round_spec)
    if isinstance(parcel, CalibratedFrozenParcel):
        validate_calibrated_parcel_coverage(parcel)
    else:
        validate_parcel_coverage(parcel)
    return parcel

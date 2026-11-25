"""V2 calibrated parcel data types and exact rational input helpers."""
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class HalfPlane:
    """Closed half-plane ``A*a + B*b <= C`` with exact rational coefficients."""

    a: Fraction
    b: Fraction
    c: Fraction


@dataclass(frozen=True)
class CalibratedContribution:
    """Box fragment projection with nominal and coefficient response sums."""

    width: int
    index: int
    total: Fraction
    alpha_sum: Fraction
    beta_sum: Fraction


@dataclass(frozen=True)
class CalibratedFrozenParcel:
    """Frozen observation revision bound to a shared calibration declaration."""

    issue_id: str
    revision_id: str
    segment_id: str
    round_spec: object
    coverage: object
    missing: tuple[int, ...]
    contributions: tuple[CalibratedContribution, ...]
    calibration_id: str
    halfplanes: tuple[HalfPlane, ...]
    version: int = 2


def rational_input(value: object, label: str) -> Fraction:
    """Normalize V1 style rational inputs: ``Fraction``, non-bool int or string."""
    if isinstance(value, Fraction):
        return value
    if type(value) not in (int, str):
        raise ValueError(f'{label} must be an exact rational number')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{label} must be an exact rational number') from error


def normalize_halfplanes(halfplanes: object) -> tuple[HalfPlane, ...]:
    if isinstance(halfplanes, (str, bytes)) or not isinstance(halfplanes, Iterable):
        raise ValueError('halfplanes must be an iterable of (A, B, C) triples')
    planes = []
    for plane in halfplanes:
        if not isinstance(plane, (tuple, list)) or len(plane) != 3:
            raise ValueError('each halfplane must be an (A, B, C) triple')
        planes.append(HalfPlane(
            rational_input(plane[0], 'halfplane A'),
            rational_input(plane[1], 'halfplane B'),
            rational_input(plane[2], 'halfplane C'),
        ))
    return tuple(planes)

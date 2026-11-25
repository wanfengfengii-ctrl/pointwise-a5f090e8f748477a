"""Exact rational geometry of the shared calibration domain.

The domain is the intersection of the parameter box ``[-1, 1] ** 2`` with a
collection of closed half-planes ``A*a + B*b <= C``.  Everything is computed
with :class:`fractions.Fraction`, so the classification into empty set,
singleton, segment or polygon and every returned witness is exact.
"""
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cmp_to_key

from evidence.calibration import HalfPlane

Point = tuple[Fraction, Fraction]

BOX_HALFPLANES = (
    HalfPlane(Fraction(1), Fraction(0), Fraction(1)),
    HalfPlane(Fraction(-1), Fraction(0), Fraction(1)),
    HalfPlane(Fraction(0), Fraction(1), Fraction(1)),
    HalfPlane(Fraction(0), Fraction(-1), Fraction(1)),
)


def _as_halfplane(plane: HalfPlane | tuple[Fraction, Fraction, Fraction]) -> HalfPlane:
    if isinstance(plane, HalfPlane):
        return plane
    a, b, c = plane
    return HalfPlane(Fraction(a), Fraction(b), Fraction(c))


def _violates(point: Point, plane: HalfPlane) -> bool:
    a, b = point
    return plane.a * a + plane.b * b > plane.c


def _line_intersection(left: HalfPlane, right: HalfPlane) -> Point | None:
    """Intersect the two boundary lines; parallel lines return ``None``."""
    determinant = left.a * right.b - right.a * left.b
    if determinant == 0:
        return None
    a = (left.c * right.b - right.c * left.b) / determinant
    b = (left.a * right.c - right.a * left.c) / determinant
    return a, b


def feasible_vertices(halfplanes: Iterable[HalfPlane | tuple]) -> tuple[Point, ...]:
    """All distinct boundary intersections that satisfy every constraint."""
    planes = (*BOX_HALFPLANES, *(_as_halfplane(plane) for plane in halfplanes))
    vertices: set[Point] = set()
    for position, left in enumerate(planes):
        for right in planes[position + 1:]:
            point = _line_intersection(left, right)
            if point is None:
                continue
            if all(not _violates(point, plane) for plane in planes):
                vertices.add(point)
    return tuple(vertices)


def _cross(origin: Point, left: Point, right: Point) -> Fraction:
    return (left[0] - origin[0]) * (right[1] - origin[1]) - (
        left[1] - origin[1]
    ) * (right[0] - origin[0])


def _polygon_order(points: Sequence[Point]) -> tuple[Point, ...]:
    center_a = sum((point[0] for point in points), Fraction(0)) / len(points)
    center_b = sum((point[1] for point in points), Fraction(0)) / len(points)
    center = (center_a, center_b)

    def compare(left: Point, right: Point) -> int:
        cross = _cross(center, left, right)
        if cross > 0:
            return -1
        if cross < 0:
            return 1
        left_radius = (left[0] - center[0]) ** 2 + (left[1] - center[1]) ** 2
        right_radius = (right[0] - center[0]) ** 2 + (right[1] - center[1]) ** 2
        if left_radius < right_radius:
            return -1
        if left_radius > right_radius:
            return 1
        return 0

    return tuple(sorted(points, key=cmp_to_key(compare)))


@dataclass(frozen=True)
class FeasibleDomain:
    kind: str  # 'empty' | 'point' | 'segment' | 'polygon'
    vertices: tuple[Point, ...]
    halfplanes: tuple[HalfPlane, ...]

    @property
    def is_empty(self) -> bool:
        return self.kind == 'empty'

    def contains(self, point: Point) -> bool:
        return all(not _violates(point, plane) for plane in (*BOX_HALFPLANES, *self.halfplanes))

    def edges(self) -> tuple[tuple[Point, Point], ...]:
        if self.kind == 'segment':
            return ((self.vertices[0], self.vertices[1]),)
        if self.kind == 'polygon':
            return tuple(
                (self.vertices[index], self.vertices[(index + 1) % len(self.vertices)])
                for index in range(len(self.vertices))
            )
        return ()


def build_domain(halfplanes: Iterable[HalfPlane | tuple]) -> FeasibleDomain:
    planes = tuple(_as_halfplane(plane) for plane in halfplanes)
    vertices = feasible_vertices(planes)
    if not vertices:
        return FeasibleDomain('empty', (), planes)
    if len(vertices) == 1:
        return FeasibleDomain('point', vertices, planes)
    first = vertices[0]
    cross_products = {
        (point[0] - first[0]) * (other[1] - first[1])
        - (point[1] - first[1]) * (other[0] - first[0])
        for point in vertices[1:]
        for other in vertices[1:]
    }
    if cross_products <= {Fraction(0)}:
        ordered = tuple(sorted(vertices))
        return FeasibleDomain('segment', (ordered[0], ordered[-1]), planes)
    return FeasibleDomain('polygon', _polygon_order(vertices), planes)

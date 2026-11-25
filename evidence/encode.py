from dataclasses import dataclass
from fractions import Fraction
import json
import re

from evidence.calibration import (
    CalibratedContribution,
    CalibratedFrozenParcel,
    HalfPlane,
)
from rounds.grid import BeatRange
from rounds.protocol import MeasurementProtocol
from rounds.validation import RoundSpec, require_identifier, validate_round


@dataclass(frozen=True)
class BoxContribution:
    width: int
    index: int
    total: Fraction


@dataclass(frozen=True)
class FrozenParcel:
    issue_id: str
    revision_id: str
    segment_id: str
    round_spec: RoundSpec
    coverage: BeatRange
    missing: tuple[int, ...]
    contributions: tuple[BoxContribution, ...]


def _rational_pair(value: Fraction) -> list[str]:
    return [str(value.numerator), str(value.denominator)]


def _round_block(specification: RoundSpec) -> dict:
    protocol = specification.protocol
    return {
        'round_id': specification.round_id,
        'first': specification.beats.first,
        'last': specification.beats.last,
        'protocol_id': protocol.protocol_id,
        'unit': protocol.unit,
        'box_widths': list(protocol.box_widths),
    }


def encode_parcel(parcel: FrozenParcel | CalibratedFrozenParcel) -> str:
    if isinstance(parcel, CalibratedFrozenParcel):
        return _encode_calibrated(parcel)
    return _encode_v1(parcel)


def _encode_v1(parcel: FrozenParcel) -> str:
    contributions = sorted(parcel.contributions, key=lambda item: (item.width, item.index))
    body = {
        'version': 1,
        'issue_id': parcel.issue_id,
        'revision_id': parcel.revision_id,
        'segment_id': parcel.segment_id,
        'round': _round_block(parcel.round_spec),
        'coverage': [parcel.coverage.first, parcel.coverage.last],
        'missing': sorted(parcel.missing),
        'contributions': [
            {
                'width': item.width,
                'index': item.index,
                'sum': _rational_pair(item.total),
            }
            for item in contributions
        ],
    }
    return json.dumps(body, sort_keys=True, separators=(',', ':'))


def _encode_calibrated(parcel: CalibratedFrozenParcel) -> str:
    contributions = sorted(parcel.contributions, key=lambda item: (item.width, item.index))
    halfplanes = sorted(
        parcel.halfplanes,
        key=lambda plane: (plane.a, plane.b, plane.c),
    )
    body = {
        'version': 2,
        'issue_id': parcel.issue_id,
        'revision_id': parcel.revision_id,
        'segment_id': parcel.segment_id,
        'calibration_id': parcel.calibration_id,
        'round': _round_block(parcel.round_spec),
        'coverage': [parcel.coverage.first, parcel.coverage.last],
        'missing': sorted(parcel.missing),
        'halfplanes': [
            [_rational_pair(plane.a), _rational_pair(plane.b), _rational_pair(plane.c)]
            for plane in halfplanes
        ],
        'contributions': [
            {
                'width': item.width,
                'index': item.index,
                'sum': _rational_pair(item.total),
                'alpha_sum': _rational_pair(item.alpha_sum),
                'beta_sum': _rational_pair(item.beta_sum),
            }
            for item in contributions
        ],
    }
    return json.dumps(body, sort_keys=True, separators=(',', ':'))


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'duplicate parcel field: {name}')
        result[name] = value
    return result


def _require_fields(value: object, expected: set[str], label: str) -> dict:
    if type(value) is not dict or value.keys() != expected:
        raise ValueError(f'invalid fields in parcel {label}')
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f'{label} must be an integer')
    return value


def _list(value: object, label: str, length: int | None = None) -> list:
    if type(value) is not list or (length is not None and len(value) != length):
        raise ValueError(f'invalid list in parcel {label}')
    return value


_DECIMAL_INTEGER = re.compile(r'-?[0-9]+')


def _decode_sum(value: object) -> Fraction:
    numerator, denominator = _list(value, 'sum', 2)
    for part in (numerator, denominator):
        if type(part) is not str or _DECIMAL_INTEGER.fullmatch(part) is None:
            raise ValueError('sum must contain decimal integer strings')
    divisor = int(denominator)
    if divisor <= 0:
        raise ValueError('sum denominator must be positive')
    return Fraction(int(numerator), divisor)


def _decode_round(value: object) -> RoundSpec:
    fields = {'round_id', 'first', 'last', 'protocol_id', 'unit', 'box_widths'}
    body = _require_fields(value, fields, 'round')
    widths = tuple(_integer(item, 'box width') for item in _list(body['box_widths'], 'box_widths'))
    protocol = MeasurementProtocol(body['protocol_id'], body['unit'], widths)
    return validate_round(body['round_id'], body['first'], body['last'], protocol)


def _decode_contribution(value: object) -> BoxContribution:
    fields = _require_fields(value, {'width', 'index', 'sum'}, 'contribution')
    return BoxContribution(
        _integer(fields['width'], 'contribution width'),
        _integer(fields['index'], 'contribution index'),
        _decode_sum(fields['sum']),
    )


def _decode_calibrated_contribution(value: object) -> CalibratedContribution:
    fields = _require_fields(
        value, {'width', 'index', 'sum', 'alpha_sum', 'beta_sum'}, 'contribution',
    )
    return CalibratedContribution(
        _integer(fields['width'], 'contribution width'),
        _integer(fields['index'], 'contribution index'),
        _decode_sum(fields['sum']),
        _decode_sum(fields['alpha_sum']),
        _decode_sum(fields['beta_sum']),
    )


def _decode_halfplane(value: object) -> HalfPlane:
    triple = _list(value, 'halfplane', 3)
    return HalfPlane(_decode_sum(triple[0]), _decode_sum(triple[1]), _decode_sum(triple[2]))


def decode_parcel(body: str) -> FrozenParcel | CalibratedFrozenParcel:
    if type(body) is not str:
        raise ValueError('parcel body must be JSON text')
    root = json.loads(body, object_pairs_hook=_unique_object)
    if type(root) is not dict or 'version' not in root:
        raise ValueError('invalid parcel body')
    version = _integer(root['version'], 'version')
    if version == 1:
        return _decode_v1(root)
    if version == 2:
        return _decode_calibrated(root)
    raise ValueError('unsupported parcel version')


def _decode_v1(root: dict) -> FrozenParcel:
    fields = {'version', 'issue_id', 'revision_id', 'segment_id', 'round', 'coverage', 'missing', 'contributions'}
    root = _require_fields(root, fields, 'body')
    first, last = _list(root['coverage'], 'coverage', 2)
    missing = sorted(_integer(beat, 'missing beat') for beat in _list(root['missing'], 'missing'))
    contributions = sorted(
        (_decode_contribution(item) for item in _list(root['contributions'], 'contributions')),
        key=lambda item: (item.width, item.index),
    )
    return FrozenParcel(
        require_identifier(root['issue_id'], 'issue ID'),
        require_identifier(root['revision_id'], 'revision ID'),
        require_identifier(root['segment_id'], 'segment ID'),
        _decode_round(root['round']), BeatRange(first, last), tuple(missing), tuple(contributions),
    )


def _decode_calibrated(root: dict) -> CalibratedFrozenParcel:
    fields = {
        'version', 'issue_id', 'revision_id', 'segment_id', 'calibration_id',
        'round', 'coverage', 'missing', 'halfplanes', 'contributions',
    }
    root = _require_fields(root, fields, 'body')
    first, last = _list(root['coverage'], 'coverage', 2)
    missing = sorted(_integer(beat, 'missing beat') for beat in _list(root['missing'], 'missing'))
    contributions = sorted(
        (
            _decode_calibrated_contribution(item)
            for item in _list(root['contributions'], 'contributions')
        ),
        key=lambda item: (item.width, item.index),
    )
    halfplanes = tuple(
        _decode_halfplane(item) for item in _list(root['halfplanes'], 'halfplanes')
    )
    # Order is not part of the half-plane declaration identity.
    halfplanes = tuple(sorted(halfplanes, key=lambda plane: (plane.a, plane.b, plane.c)))
    return CalibratedFrozenParcel(
        require_identifier(root['issue_id'], 'issue ID'),
        require_identifier(root['revision_id'], 'revision ID'),
        require_identifier(root['segment_id'], 'segment ID'),
        _decode_round(root['round']),
        BeatRange(first, last),
        tuple(missing),
        tuple(contributions),
        require_identifier(root['calibration_id'], 'calibration ID'),
        halfplanes,
    )

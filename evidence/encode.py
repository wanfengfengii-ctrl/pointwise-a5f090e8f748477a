from dataclasses import dataclass
from fractions import Fraction
import json
import re

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


def encode_parcel(parcel: FrozenParcel) -> str:
    specification = parcel.round_spec
    protocol = specification.protocol
    contributions = sorted(parcel.contributions, key=lambda item: (item.width, item.index))
    body = {
        'version': 1,
        'issue_id': parcel.issue_id,
        'revision_id': parcel.revision_id,
        'segment_id': parcel.segment_id,
        'round': {
            'round_id': specification.round_id,
            'first': specification.beats.first,
            'last': specification.beats.last,
            'protocol_id': protocol.protocol_id,
            'unit': protocol.unit,
            'box_widths': list(protocol.box_widths),
        },
        'coverage': [parcel.coverage.first, parcel.coverage.last],
        'missing': sorted(parcel.missing),
        'contributions': [
            {
                'width': item.width,
                'index': item.index,
                'sum': [str(item.total.numerator), str(item.total.denominator)],
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


def decode_parcel(body: str) -> FrozenParcel:
    if type(body) is not str:
        raise ValueError('parcel body must be JSON text')
    root = json.loads(body, object_pairs_hook=_unique_object)
    fields = {'version', 'issue_id', 'revision_id', 'segment_id', 'round', 'coverage', 'missing', 'contributions'}
    root = _require_fields(root, fields, 'body')
    if _integer(root['version'], 'version') != 1:
        raise ValueError('unsupported parcel version')
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

from dataclasses import dataclass

from rounds.grid import BeatRange
from rounds.protocol import MeasurementProtocol, REFERENCE_PROTOCOL


@dataclass(frozen=True)
class RoundSpec:
    round_id: str
    beats: BeatRange
    protocol: MeasurementProtocol


def require_identifier(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f'{label} must be a nonempty string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError(f'{label} must be valid UTF-8 text') from error
    return value


def validate_round(
    round_id: str,
    first: int,
    last: int,
    protocol: MeasurementProtocol = REFERENCE_PROTOCOL,
) -> RoundSpec:
    require_identifier(round_id, 'round ID')
    beats = BeatRange(first, last)
    if (
        type(protocol) is not MeasurementProtocol
        or type(protocol.box_widths) is not tuple
        or any(type(width) is not int for width in protocol.box_widths)
        or protocol != REFERENCE_PROTOCOL
    ):
        raise ValueError('unsupported reference instrument protocol')
    return RoundSpec(round_id, beats, REFERENCE_PROTOCOL)


def require_matching_round(registered: RoundSpec, received: RoundSpec) -> None:
    if received.round_id != registered.round_id:
        raise ValueError('parcel belongs to a different round')
    if received != registered:
        raise ValueError('parcel coordinates or protocol differ from the directory')

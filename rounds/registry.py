from rounds.protocol import MeasurementProtocol, REFERENCE_PROTOCOL
from rounds.store import RoundStore
from rounds.validation import RoundSpec, require_identifier, validate_round


def open_round(
    directory: RoundStore,
    round_id: str,
    first: int,
    last: int,
    protocol: MeasurementProtocol = REFERENCE_PROTOCOL,
) -> RoundSpec:
    specification = validate_round(round_id, first, last, protocol)
    return directory.register(specification)


def load_round(directory: RoundStore, round_id: str) -> RoundSpec:
    require_identifier(round_id, 'round ID')
    return directory.get(round_id)

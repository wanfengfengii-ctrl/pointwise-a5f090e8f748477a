from dataclasses import dataclass


@dataclass(frozen=True)
class MeasurementProtocol:
    protocol_id: str
    unit: str
    box_widths: tuple[int, ...]


REFERENCE_PROTOCOL = MeasurementProtocol('reference-stability-v1', 'μm', (2, 4))


def require_box_width(protocol: MeasurementProtocol, width: int) -> int:
    if type(width) is not int or width not in protocol.box_widths:
        raise ValueError(f'box width must be one of {protocol.box_widths}')
    return width

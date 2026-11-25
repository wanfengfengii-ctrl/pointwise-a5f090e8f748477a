import sqlite3

from ledger_db import initialize_schema, write_transaction
from rounds.protocol import MeasurementProtocol, REFERENCE_PROTOCOL
from rounds.validation import RoundSpec, validate_round


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS measurement_rounds (
        round_id TEXT PRIMARY KEY NOT NULL,
        first_beat TEXT NOT NULL,
        last_beat TEXT NOT NULL,
        protocol_id TEXT NOT NULL,
        unit TEXT NOT NULL
    )''',
)


def _round_from_row(row: tuple) -> RoundSpec:
    round_id, first, last, protocol_id, unit = row
    protocol = MeasurementProtocol(protocol_id, unit, REFERENCE_PROTOCOL.box_widths)
    return validate_round(round_id, int(first), int(last), protocol)


class RoundStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def _find_row(self, round_id: str) -> tuple | None:
        return self.connection.execute(
            '''SELECT round_id, first_beat, last_beat, protocol_id, unit
               FROM measurement_rounds WHERE round_id = ?''',
            (round_id,),
        ).fetchone()

    def register(self, specification: RoundSpec) -> RoundSpec:
        with write_transaction(self.connection):
            existing_row = self._find_row(specification.round_id)
            if existing_row is not None:
                existing = _round_from_row(existing_row)
                if existing != specification:
                    raise ValueError('round ID already has different coordinates or protocol')
                return existing
            self.connection.execute(
                '''INSERT INTO measurement_rounds
                   (round_id, first_beat, last_beat, protocol_id, unit)
                   VALUES (?, ?, ?, ?, ?)''',
                (
                    specification.round_id,
                    str(specification.beats.first),
                    str(specification.beats.last),
                    specification.protocol.protocol_id,
                    specification.protocol.unit,
                ),
            )
        return specification

    def get(self, round_id: str) -> RoundSpec:
        row = self._find_row(round_id)
        if row is None:
            raise LookupError(f'unknown round: {round_id}')
        return _round_from_row(row)

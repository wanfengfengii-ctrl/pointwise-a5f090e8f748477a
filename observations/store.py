from fractions import Fraction
import sqlite3

from ledger_db import initialize_schema, write_transaction
from observations.revisions import Observation, Revision
from rounds.grid import BeatRange


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS observation_segments (
        round_id TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        first_beat TEXT NOT NULL,
        last_beat TEXT NOT NULL,
        current_revision_id TEXT NOT NULL REFERENCES observation_revisions(revision_id)
            DEFERRABLE INITIALLY DEFERRED,
        PRIMARY KEY (round_id, segment_id)
    )''',
    '''CREATE TABLE IF NOT EXISTS observation_revisions (
        revision_id TEXT PRIMARY KEY NOT NULL,
        round_id TEXT NOT NULL,
        segment_id TEXT NOT NULL,
        predecessor_id TEXT REFERENCES observation_revisions(revision_id),
        FOREIGN KEY (round_id, segment_id)
            REFERENCES observation_segments(round_id, segment_id)
    )''',
    '''CREATE TABLE IF NOT EXISTS observation_entries (
        revision_id TEXT NOT NULL REFERENCES observation_revisions(revision_id),
        beat TEXT NOT NULL,
        numerator TEXT,
        denominator TEXT,
        CHECK ((numerator IS NULL) = (denominator IS NULL)),
        PRIMARY KEY (revision_id, beat)
    )''',
)


def _entry_row(revision_id: str, entry: Observation) -> tuple:
    value = entry.value
    if value is None:
        return revision_id, str(entry.beat), None, None
    return revision_id, str(entry.beat), str(value.numerator), str(value.denominator)


class ObservationStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def _write_revision(self, revision: Revision) -> None:
        self.connection.execute(
            '''INSERT INTO observation_revisions
               (revision_id, round_id, segment_id, predecessor_id) VALUES (?, ?, ?, ?)''',
            (revision.revision_id, revision.round_id, revision.segment_id, revision.predecessor_id),
        )
        self.connection.executemany(
            '''INSERT INTO observation_entries
               (revision_id, beat, numerator, denominator) VALUES (?, ?, ?, ?)''',
            (_entry_row(revision.revision_id, entry) for entry in revision.entries),
        )

    def insert_initial(self, revision: Revision) -> Revision:
        key = (revision.round_id, revision.segment_id)
        with write_transaction(self.connection):
            existing = self.connection.execute(
                'SELECT 1 FROM observation_segments WHERE round_id = ? AND segment_id = ?', key,
            ).fetchone()
            if existing is not None:
                raise ValueError('segment already has a revision in this round')
            self.connection.execute(
                '''INSERT INTO observation_segments
                   (round_id, segment_id, first_beat, last_beat, current_revision_id)
                   VALUES (?, ?, ?, ?, ?)''',
                (*key, str(revision.coverage.first), str(revision.coverage.last), revision.revision_id),
            )
            self._write_revision(revision)
        return revision

    def append_if_current(self, revision: Revision) -> Revision:
        with write_transaction(self.connection):
            updated = self.connection.execute(
                '''UPDATE observation_segments SET current_revision_id = ?
                   WHERE round_id = ? AND segment_id = ? AND current_revision_id = ?''',
                (revision.revision_id, revision.round_id, revision.segment_id, revision.predecessor_id),
            )
            if updated.rowcount != 1:
                raise ValueError('stale base revision')
            self._write_revision(revision)
        return revision

    def get_revision(self, revision_id: str) -> Revision:
        metadata = self.connection.execute(
            '''SELECT r.round_id, r.segment_id, r.predecessor_id, s.first_beat, s.last_beat
               FROM observation_revisions AS r JOIN observation_segments AS s
                 ON s.round_id = r.round_id AND s.segment_id = r.segment_id
               WHERE r.revision_id = ?''',
            (revision_id,),
        ).fetchone()
        if metadata is None:
            raise LookupError(f'unknown revision: {revision_id}')
        round_id, segment_id, predecessor_id, first, last = metadata
        rows = self.connection.execute(
            'SELECT beat, numerator, denominator FROM observation_entries WHERE revision_id = ?',
            (revision_id,),
        )
        entries = []
        for beat, numerator, denominator in rows:
            value = None if numerator is None else Fraction(int(numerator), int(denominator))
            entries.append(Observation(int(beat), value))
        entries.sort(key=lambda entry: entry.beat)
        return Revision(
            revision_id, round_id, segment_id, BeatRange(int(first), int(last)),
            predecessor_id, tuple(entries),
        )

    def get_current_revision(self, round_id: str, segment_id: str) -> Revision:
        row = self.connection.execute(
            '''SELECT current_revision_id FROM observation_segments
               WHERE round_id = ? AND segment_id = ?''',
            (round_id, segment_id),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown segment: {round_id}/{segment_id}')
        return self.get_revision(row[0])

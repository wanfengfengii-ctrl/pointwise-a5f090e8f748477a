from fractions import Fraction

from evidence.freeze import freeze_revision
from evidence.retrieve import load_issued_parcel
from observations.ingest import record_segment
from observations.read import load_revision
from rounds.protocol import MeasurementProtocol
from rounds.registry import load_round, open_round
from tests.support import LedgerCase


class ObservationTests(LedgerCase):
    def test_duplicate_beat_rejects_entire_segment_and_valid_retry(self):
        round_id = 'retry'
        registered = open_round(self.directory, round_id, 1, 3)
        duplicate = [(1, 0), (2, None), (2, 7), (3, '1/3')]
        with self.assertRaisesRegex(ValueError, 'duplicate beat'):
            record_segment(self.directory, self.station, round_id, 'day', 1, 3, duplicate)
        with self.assertRaises(LookupError):
            self.station.get_current_revision(round_id, 'day')
        self.assertEqual(self.source.execute('SELECT count(*) FROM observation_revisions').fetchone()[0], 0)
        self.assertEqual(load_round(self.directory, round_id), registered)
        for bad_entries, message in (
            ([(1, 0), (3, '1/3')], 'do not cover'),
            ([(1, 0), (2, None), (4, '1/3')], 'outside the segment'),
            ([(1, 0.0), (2, None), (3, 0)], 'exact rational'),
        ):
            with self.subTest(entries=bad_entries):
                with self.assertRaisesRegex(ValueError, message):
                    record_segment(self.directory, self.station, round_id, 'day', 1, 3, bad_entries)
                with self.assertRaises(LookupError):
                    self.station.get_current_revision(round_id, 'day')
        good = [(3, '1/3'), (1, 0), (2, None)]
        revision = record_segment(self.directory, self.station, round_id, 'day', 1, 3, good)
        self.assertEqual(
            [(item.beat, item.value) for item in revision.entries],
            [(1, Fraction(0)), (2, None), (3, Fraction(1, 3))],
        )
        self.assertIsInstance(revision.entries[0].value, Fraction)
        self.assertIsNone(revision.predecessor_id)
        parcel = self.freeze(revision)
        self.assertEqual(parcel.missing, (2,))
        self.assertEqual(parcel.revision_id, revision.revision_id)
        for store in (self.directory, self.station, self.issues):
            store.initialize()
        self.assertEqual(open_round(self.directory, round_id, 1, 3), registered)
        self.assertEqual(load_revision(self.directory, self.station, revision.revision_id).revision, revision)
        self.assertEqual(load_issued_parcel(self.issues, parcel.issue_id), parcel)
        with self.assertRaisesRegex(ValueError, 'already has a revision'):
            record_segment(self.directory, self.station, round_id, 'day', 1, 3, good)

    def test_directory_rejects_conflicting_coordinates_and_protocol(self):
        registered = open_round(self.directory, 'reference', 10, 15)
        with self.assertRaisesRegex(ValueError, 'already has different'):
            open_round(self.directory, 'reference', 10, 16)
        with self.assertRaisesRegex(ValueError, 'first beat'):
            open_round(self.directory, 'reverse', 15, 10)
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            open_round(self.directory, 'millimeters', 1, 6, MeasurementProtocol('other', 'mm', (2, 4)))
        self.assertEqual(load_round(self.directory, 'reference'), registered)
        with self.assertRaises(LookupError):
            load_round(self.directory, 'reverse')

    def test_unknown_revision_cannot_issue(self):
        with self.assertRaises(LookupError):
            freeze_revision(self.directory, self.station, self.issues, 'unknown-revision')
        self.assertEqual(self.source.execute('SELECT count(*) FROM issued_parcels').fetchone()[0], 0)

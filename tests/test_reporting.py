from fractions import Fraction
import json
import sqlite3

from receipts.accept import accept_parcel
from receipts.retrieve import load_accepted
from reports.retrieve import load_report
from rounds.registry import open_round
from tests.support import LedgerCase


class ReportingTests(LedgerCase):
    def test_ordered_selection_and_wrong_round(self):
        values = [0, 0, 2, 2, 4, 4]
        same = self.prepare('same', values, 3)
        other = self.prepare('other', values, 3)
        self.close_source()
        reverse = same[::-1]
        valid = self.publish('same', 2, reverse)
        self.assertEqual(valid.receipt_ids, reverse)
        self.assertEqual(valid.result.pair_count, 2)
        self.assertEqual(valid.result.value, Fraction(2))
        exported = self.exported(valid)
        self.assertEqual([parent['receipt_id'] for parent in exported['parents']], list(reverse))
        self.assertEqual([parent['segment_id'] for parent in exported['parents']], ['night', 'day'])
        counts = self.publication_counts()
        with self.assertRaisesRegex(ValueError, 'different round'):
            self.publish('same', 2, (same[0], other[1]))
        self.assertEqual(self.publication_counts(), counts)
        self.assertEqual(load_report(self.reports, valid.report_id), valid)

    def test_illegal_width_and_unknown_receipt_leave_no_publication(self):
        ids = self.prepare('checks', [0, 0, 2, 2, 4, 4], 3)
        self.close_source()
        for width in (3, 2.0, True):
            with self.subTest(width=width), self.assertRaisesRegex(ValueError, 'box width'):
                self.publish('checks', width, ids)
        with self.assertRaisesRegex(LookupError, 'unknown receipt'):
            self.publish('checks', 2, (ids[0], 'unknown-receipt'))
        self.assertEqual(self.publication_counts(), (0, 0, 0))

    def test_gap_overlap_and_length_balanced_overlap(self):
        open_round(self.directory, 'coverage', 1, 6)
        accepted = {}
        for name, first, values in (
            ('day', 1, [0, 0, 2]),
            ('night', 4, [2, 4, 4]),
            ('early', 1, [0, 0, 2, 2]),
            ('balanced', 4, [2, 4]),
        ):
            accepted[name] = self.receive(self.segment('coverage', name, first, values))
        self.close_source()
        invalid = (
            (('day',), 'coverage gap'),
            (('early', 'night'), 'overlapping'),
            (('early', 'balanced'), 'overlapping'),
            (('day', 'day'), 'overlapping'),
        )
        for names, message in invalid:
            ids = tuple(accepted[name].receipt_id for name in names)
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, message):
                self.publish('coverage', 2, ids)
            self.assertEqual(self.publication_counts(), (0, 0, 0))
        for original in accepted.values():
            self.assertEqual(load_accepted(self.receipts, original.receipt_id), original)
        report = self.publish('coverage', 2, (accepted['day'].receipt_id, accepted['night'].receipt_id))
        self.assertEqual(report.result.value, Fraction(2))

    def test_receipt_conflict_preserves_body_and_acknowledgment(self):
        ids = self.prepare('receipt-conflict', [0, 0, 2, 2, 4, 4], 3)
        self.close_source()
        original = load_accepted(self.receipts, ids[0])
        equivalent = json.loads(original.body)
        equivalent['contributions'].reverse()
        repeated = accept_parcel(self.directory, self.receipts, json.dumps(equivalent, indent=2))
        self.assertEqual(repeated, original)
        altered = json.loads(original.body)
        for fragment in altered['contributions']:
            if (fragment['width'], fragment['index']) in ((2, 1), (4, 0)):
                fragment['sum'] = ['6', '1']
        with self.assertRaisesRegex(ValueError, 'different body'):
            accept_parcel(self.directory, self.receipts, json.dumps(altered))
        self.assertEqual(load_accepted(self.receipts, ids[0]), original)
        self.assertEqual(self.center.execute('SELECT count(*) FROM accepted_parcels').fetchone()[0], 2)
        self.assertEqual(self.publish('receipt-conflict', 2, ids).result.value, Fraction(2))

    def test_invalid_transport_evidence_is_rejected_at_receipt(self):
        ids = self.prepare('transport', [0, 0, 2, 2, 4, 4], 3)
        self.close_source()
        original = load_accepted(self.receipts, ids[0]).body
        for variant in ('wrong_round', 'missing_bounds', 'missing_fragment', 'inconsistent_sum', 'duplicate_fragment'):
            body = json.loads(original)
            body['issue_id'] = f'bad-{variant}'
            if variant == 'wrong_round':
                body['round']['last'] = 7
            elif variant == 'missing_bounds':
                body['missing'] = [4]
            elif variant == 'missing_fragment':
                body['contributions'].pop()
            elif variant == 'inconsistent_sum':
                body['contributions'][-1]['sum'] = ['9', '1']
            else:
                body['contributions'].append(body['contributions'][0])
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                accept_parcel(self.directory, self.receipts, json.dumps(body))
        self.assertEqual(self.center.execute('SELECT count(*) FROM accepted_parcels').fetchone()[0], 2)

    def test_acknowledgment_failure_rolls_back_and_allows_retry(self):
        ids = self.prepare('rollback', [0, 0, 2, 2, 4, 4], 3)
        self.close_source()
        before = self.publish('rollback', 2, ids)
        counts = self.publication_counts()
        self.center.execute('''CREATE TEMP TRIGGER reject_report_ack
            BEFORE INSERT ON main.report_acknowledgments
            BEGIN SELECT RAISE(ABORT, 'acknowledgment unavailable'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'acknowledgment unavailable'):
            self.publish('rollback', 2, ids)
        self.assertEqual(self.publication_counts(), counts)
        self.assertEqual(load_report(self.reports, before.report_id), before)
        for receipt_id in ids:
            self.assertEqual(load_accepted(self.receipts, receipt_id).receipt_id, receipt_id)
        self.center.execute('DROP TRIGGER temp.reject_report_ack')
        retry = self.publish('rollback', 2, ids)
        self.assertEqual(self.publication_counts(), (counts[0] + 1, counts[1] + 2, counts[2] + 1))
        self.assertNotEqual(before.report_id, retry.report_id)
        self.assertNotEqual(before.ack_id, retry.ack_id)
        self.assertEqual(retry.receipt_ids, ids)
        self.assertEqual(load_report(self.reports, retry.report_id), retry)

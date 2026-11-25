from fractions import Fraction

from evidence.retrieve import load_issued_parcel
from observations.corrections import amend_revision
from observations.read import load_revision
from receipts.retrieve import load_accepted
from reports.retrieve import load_report
from rounds.registry import open_round
from tests.support import LedgerCase, scenario


class HistoryTests(LedgerCase):
    def test_stale_base_and_out_of_range_corrections_preserve_history(self):
        open_round(self.directory, 'stale', 1, 6)
        old = self.segment('stale', 'day', 1, [0, 0, 2])
        new = amend_revision(self.station, old.revision_id, 3, 6)
        with self.assertRaisesRegex(ValueError, 'stale base'):
            amend_revision(self.station, old.revision_id, 3, 8)
        with self.assertRaisesRegex(ValueError, 'outside the segment'):
            amend_revision(self.station, new.revision_id, 4, 8)
        self.assertEqual(new.predecessor_id, old.revision_id)
        self.assertEqual(self.station.get_current_revision('stale', 'day'), new)
        self.assertEqual(load_revision(self.directory, self.station, old.revision_id).revision, old)
        self.assertEqual(self.source.execute('SELECT count(*) FROM observation_revisions').fetchone()[0], 2)

    def test_explicit_old_revision_can_be_reissued_after_amendment(self):
        open_round(self.directory, 'reissue', 1, 6)
        old = self.segment('reissue', 'day', 1, [0, 0, 2])
        initial = self.freeze(old)
        new = amend_revision(self.station, old.revision_id, 3, 6)
        reissued = self.freeze(old)
        new_parcel = self.freeze(new)
        self.assertEqual(load_issued_parcel(self.issues, initial.issue_id), initial)
        self.assertNotEqual(initial.issue_id, reissued.issue_id)
        self.assertEqual(reissued.revision_id, old.revision_id)
        self.assertEqual(reissued.contributions, initial.contributions)
        self.assertNotEqual(reissued.contributions, new_parcel.contributions)
        accepted_old = self.accept(reissued)
        accepted_new = self.accept(new_parcel)
        night = self.receive(self.segment('reissue', 'night', 4, [2, 4, 4]))
        self.close_source()
        old_report = self.publish('reissue', 2, (accepted_old.receipt_id, night.receipt_id))
        new_report = self.publish('reissue', 2, (accepted_new.receipt_id, night.receipt_id))
        self.assertEqual((old_report.result.pair_count, old_report.result.value), (2, Fraction(2)))
        self.assertEqual((new_report.result.pair_count, new_report.result.value), (2, Fraction(4)))
        self.assertEqual(old_report.parents[0].revision_id, old.revision_id)

    def test_reopen_and_export_original_and_corrected_reports(self):
        open_round(self.directory, 'history', 1, 6)
        original_day = self.segment('history', 'day', 1, [0, 0, 2])
        night = self.receive(self.segment('history', 'night', 4, [2, 4, 4]))
        original_receipt = self.receive(original_day)
        original_ids = (night.receipt_id, original_receipt.receipt_id)
        old = self.publish('history', 2, original_ids)
        old_export = self.exported(old)
        corrected_day = amend_revision(self.station, original_day.revision_id, 3, 6)
        corrected_receipt = self.receive(corrected_day)
        corrected_ids = (corrected_receipt.receipt_id, night.receipt_id)
        self.close_source()
        current = self.publish('history', 2, corrected_ids)
        current_export = self.exported(current)
        self.assertEqual((old.result.pair_count, old.result.value), (2, Fraction(2)))
        self.assertEqual((current.result.pair_count, current.result.value), (2, Fraction(4)))
        self.assertNotEqual(old.ack_id, current.ack_id)
        self.center.close()
        self.open_center()
        self.receipts.initialize()
        self.reports.initialize()
        self.assertEqual(load_accepted(self.receipts, original_receipt.receipt_id), original_receipt)
        self.assertEqual(load_report(self.reports, old.report_id), old)
        self.assertEqual(load_report(self.reports, current.report_id), current)
        old_reopened = self.exported(old)
        current_reopened = self.exported(current)
        self.assertEqual(old_reopened, old_export)
        self.assertEqual(current_reopened, current_export)
        self.assertEqual([parent['receipt_id'] for parent in old_reopened['parents']], list(original_ids))
        self.assertEqual([parent['receipt_id'] for parent in current_reopened['parents']], list(corrected_ids))
        self.assertEqual(old_reopened['parents'][1]['revision_id'], original_day.revision_id)
        self.assertEqual(current_reopened['parents'][0]['revision_id'], corrected_day.revision_id)
        self.assertEqual((old_reopened['ack_id'], current_reopened['ack_id']), (old.ack_id, current.ack_id))
        with self.assertRaisesRegex(LookupError, 'unknown report'):
            load_report(self.reports, 'unknown-report')
        scenario(
            'v8.reopen_export', {'old_reading_3': 2, 'corrected_reading_3': 6, 'width': 2},
            {'pairs': [2, 2], 'values': ['2', '4']},
            {'pairs': [old.result.pair_count, current.result.pair_count],
             'values': [str(old.result.value), str(current.result.value)]},
            {'original_unchanged': True, 'corrected_unchanged': True},
            {'original_unchanged': old_reopened == old_export, 'corrected_unchanged': current_reopened == current_export},
            ['observations/corrections.py', 'evidence/freeze.py', 'reports/publish.py', 'reports/retrieve.py'],
            'Means change from 0, 2, 4 to 0, 4, 4. The two squared differences change from 4 and 4 to 16 and 0.',
        )

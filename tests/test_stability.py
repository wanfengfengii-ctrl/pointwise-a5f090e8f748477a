from fractions import Fraction
import json
from pathlib import Path

from receipts.accept import accept_parcel
from rounds.registry import open_round
from tests.support import LedgerCase, scenario


class StabilityTests(LedgerCase):
    def assert_result(self, report, count, value, status):
        self.assertEqual(report.result.pair_count, count)
        self.assertEqual(report.result.value, value)
        self.assertEqual(report.result.status, status)

    def test_cross_shift_two_beats_hand_calculation(self):
        values = [0, 0, 2, 2, 4, 4]
        aligned = self.prepare('aligned', values, cut=2)
        offset = self.prepare('offset', values, cut=3)
        self.close_source()
        aligned_report = self.publish('aligned', 2, aligned)
        report = self.publish('offset', 2, offset)
        self.assert_result(aligned_report, 2, Fraction(2), 'measured')
        self.assert_result(report, 2, Fraction(2), 'measured')
        exported = self.exported(report)
        expected = {'pair_count': 2, 'status': 'measured', 'value': ['2', '1'], 'unit': 'μm²'}
        self.assertEqual(exported['result'], expected)
        stored_sources = [parent['receipt_id'] for parent in exported['parents']]
        self.assertEqual(stored_sources, list(offset))
        scenario(
            'v2', {'beats': values, 'first': 1, 'cuts_after': [2, 3], 'width': 2},
            {'pairs': 2, 'value': '2'},
            {'pairs': report.result.pair_count, 'value': str(report.result.value)},
            {'result': expected, 'sources_in_request_order': True},
            {'result': exported['result'], 'sources_in_request_order': stored_sources == list(offset)},
            ['evidence/coverage.py', 'reports/qualification.py', 'reports/analysis.py', 'reports/retrieve.py'],
            'Box means 0, 2, 4 give two squared differences of 4 and a half mean of 2.',
        )

    def test_fragment_projection_preserves_day_last_beat_state(self):
        for round_id in ('played', 'missing'):
            open_round(self.directory, round_id, 1, 6)
        selected = {}
        for round_id, third in (('played', 2), ('missing', None)):
            day = self.freeze(self.segment(round_id, 'day', 1, [0, 0, third]))
            fragment = next(item for item in day.contributions if (item.width, item.index) == (2, 1))
            self.assertEqual(day.missing, () if third == 2 else (3,))
            self.assertEqual(fragment.total, Fraction(2 if third == 2 else 0))
            night = self.receive(self.segment(round_id, 'night', 4, [2, 4, 4]))
            selected[round_id] = (self.accept(day).receipt_id, night.receipt_id)
        self.close_source()
        self.assert_result(self.publish('played', 2, selected['played']), 2, Fraction(2), 'measured')
        self.assert_result(self.publish('missing', 2, selected['missing']), 0, None, 'insufficient')

    def test_shifted_fractional_grid(self):
        values = ['1/3', '1/3', '4/3', '4/3', '7/3', '7/3']
        cases = [(f'fraction-{cut}', cut) for cut in (2, 3)]
        ids = {name: self.prepare(name, values, cut, first=10) for name, cut in cases}
        self.close_source()
        for name, cut in cases:
            with self.subTest(cut=cut):
                self.assert_result(self.publish(name, 2, ids[name]), 2, Fraction(1, 2), 'measured')

    def test_independent_missing_parcels_do_not_bridge_the_middle_box(self):
        fixture_path = Path(__file__).resolve().parents[1] / 'samples' / 'independent_missing.json'
        bodies = json.loads(fixture_path.read_text(encoding='utf-8'))['parcels']
        open_round(self.directory, 'independent-missing', 1, 6)
        self.close_source()
        accepted = [accept_parcel(self.directory, self.receipts, json.dumps(body)) for body in bodies]
        ids = tuple(item.receipt_id for item in accepted)
        report = self.publish('independent-missing', 2, ids)
        self.assert_result(report, 0, None, 'insufficient')
        exported = self.exported(report)
        expected = {'pair_count': 0, 'status': 'insufficient', 'value': None, 'unit': 'μm²'}
        self.assertEqual(exported['result'], expected)
        self.assertEqual([parent['issue_id'] for parent in exported['parents']], [body['issue_id'] for body in bodies])
        self.assertEqual(exported['ack_id'], report.ack_id)
        scenario(
            'v3.independent_parcel',
            {'coverage': [body['coverage'] for body in bodies], 'missing': [3], 'width': 2},
            {'pairs': 0, 'value': None}, {'pairs': report.result.pair_count, 'value': report.result.value},
            expected, exported['result'],
            ['receipts/verify.py', 'reports/qualification.py', 'reports/analysis.py', 'reports/retrieve.py'],
            'Beat 3 disqualifies box 3–4, leaving boxes 1–2 and 5–6 with no adjacent pair.',
        )

    def test_missing_box_leaves_other_real_pairs_eligible(self):
        values = [0, 0, 2, 2, None, 9, 4, 4, 8, 8]
        ids = self.prepare('middle-gap', values, cut=5)
        self.close_source()
        self.assert_result(self.publish('middle-gap', 2, ids), 2, Fraction(5), 'measured')

    def test_four_beat_width_and_partial_tail(self):
        step = [0, 0, 0, 0, 2, 2, 2, 2]
        cases = [
            ('flat', [7] * 8, 3, 0),
            ('step-aligned', step, 4, 2),
            ('step-offset', step, 2, 2),
            ('tail', step + [99], 2, 2),
        ]
        selected = {name: self.prepare(name, values, cut) for name, values, cut, _ in cases}
        self.close_source()
        for name, _, _, value in cases:
            with self.subTest(round_id=name):
                report = self.publish(name, 4, selected[name])
                self.assert_result(report, 1, Fraction(value), 'measured')
                stored = self.exported(report)['result']
                self.assertEqual(stored['value'], [str(value), '1'])
                self.assertEqual(stored['status'], 'measured')

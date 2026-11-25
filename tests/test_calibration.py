import json
from fractions import Fraction
from pathlib import Path

from evidence.calibration import (
    CalibratedFrozenParcel,
    HalfPlane,
    rational_input,
)
from evidence.encode import decode_parcel, encode_parcel
from evidence.freeze import freeze_calibrated_revision
from observations.ingest import record_segment
from receipts.accept import accept_parcel
from receipts.retrieve import load_accepted
from reports.calibration_analysis import (
    _quadratic_parts,
    calibrated_differences,
    evaluate,
    qualify_calibrated_boxes,
)
from reports.domain import build_domain, feasible_vertices
from reports.publish import publish_calibrated_report, publish_report
from reports.retrieve import export_report, load_report
from reports.store import CalibrationReportRecord
from rounds.registry import open_round
from tests.support import LedgerCase, scenario

FIXTURE_PATH = Path(__file__).resolve().parents[1] / 'samples' / 'calibration_ranges.json'


def _planes(rows):
    return [tuple(Fraction(str(number)) for number in row) for row in rows]


class CalibrationLedgerCase(LedgerCase):
    def calibrated_segment(self, round_id, segment_id, first, values, coefficients,
                           calibration_id, halfplanes=()):
        revision = record_segment(
            self.directory, self.station, round_id, segment_id,
            first, first + len(values) - 1,
            [(first + offset, value) for offset, value in enumerate(values)],
        )
        return freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            calibration_id, coefficients, halfplanes,
        )

    def accept_parcel(self, parcel):
        return accept_parcel(self.directory, self.receipts, encode_parcel(parcel))


class FreezeTransportTests(CalibrationLedgerCase):
    def _prepare(self, round_id='freeze', halfplanes=((1, -1, 0),)):
        open_round(self.directory, round_id, 1, 4)
        coefficients = {1: (0, 0), 2: (0, 0), 3: (Fraction(1), Fraction(1)), 4: (1, 1)}
        parcel = self.calibrated_segment(
            round_id, 'day', 1, [0, 0, 0, 0], coefficients, 'cal-1', _planes(halfplanes),
        )
        return parcel

    def test_freeze_encodes_version_two_with_affine_sums_and_halfplanes(self):
        parcel = self._prepare()
        self.assertIsInstance(parcel, CalibratedFrozenParcel)
        body = json.loads(encode_parcel(parcel))
        self.assertEqual(body['version'], 2)
        self.assertEqual(body['calibration_id'], 'cal-1')
        self.assertEqual(
            body['halfplanes'],
            [[['1', '1'], ['-1', '1'], ['0', '1']]],
        )
        contributions = {(item['width'], item['index']): item for item in body['contributions']}
        width_two_one = contributions[(2, 1)]
        self.assertEqual(width_two_one['sum'], ['0', '1'])
        self.assertEqual(width_two_one['alpha_sum'], ['2', '1'])
        self.assertEqual(width_two_one['beta_sum'], ['2', '1'])
        width_four = contributions[(4, 0)]
        self.assertEqual(width_four['alpha_sum'], ['2', '1'])
        self.assertEqual(width_four['beta_sum'], ['2', '1'])
        # Per-beat readings and coefficients stay at the station, not the parcel.
        self.assertNotIn('readings', body)
        self.assertNotIn('coefficients', body)
        # Round trip through decode keeps exact rational values.
        decoded = decode_parcel(encode_parcel(parcel))
        self.assertEqual(decoded, parcel)
        self.assertEqual(decoded.halfplanes, (HalfPlane(Fraction(1), Fraction(-1), Fraction(0)),))

    def test_zero_coefficients_still_register_every_observed_beat(self):
        open_round(self.directory, 'zeros', 1, 3)
        revision = record_segment(
            self.directory, self.station, 'zeros', 'day', 1, 3,
            [(1, 0), (2, '1/2'), (3, 0)],
        )
        coefficients = {1: (0, 0), 2: (0, 0), 3: (0, 0)}
        parcel = freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            'cal-zero', coefficients, [],
        )
        fragment = next(item for item in parcel.contributions if (item.width, item.index) == (2, 0))
        self.assertEqual((fragment.total, fragment.alpha_sum, fragment.beta_sum),
                         (Fraction(1, 2), Fraction(0), Fraction(0)))

    def test_missing_beats_must_be_omitted_from_coefficients(self):
        open_round(self.directory, 'missing', 1, 3)
        revision = record_segment(
            self.directory, self.station, 'missing', 'day', 1, 3,
            [(1, 0), (2, None), (3, 1)],
        )
        with self.assertRaisesRegex(ValueError, 'missing beats'):
            freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                'cal-missing', {1: (0, 0), 2: (1, 0), 3: (0, 0)}, [],
            )
        with self.assertRaisesRegex(ValueError, 'missing calibration coefficients'):
            freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                'cal-missing', {1: (0, 0)}, [],
            )
        parcel = freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            'cal-missing', {1: (0, 0), 3: (0, 0)}, [],
        )
        body = json.loads(encode_parcel(parcel))
        self.assertEqual(body['missing'], [2])
        fragment = next(item for item in body['contributions'] if item['width'] == 2 and item['index'] == 0)
        self.assertEqual(fragment['sum'], ['0', '1'])
        self.assertEqual(fragment['alpha_sum'], ['0', '1'])

    def test_invalid_calibration_inputs_are_rejected(self):
        open_round(self.directory, 'invalid', 1, 2)
        revision = record_segment(
            self.directory, self.station, 'invalid', 'day', 1, 2, [(1, 0), (2, 0)],
        )
        kwargs = dict(
            directory=self.directory, station=self.station, issues=self.issues,
            revision_id=revision.revision_id,
        )
        with self.assertRaisesRegex(ValueError, 'calibration ID'):
            freeze_calibrated_revision(**kwargs, calibration_id='  ', coefficients={1: (0, 0), 2: (0, 0)}, halfplanes=[])
        with self.assertRaisesRegex(ValueError, 'mapping'):
            freeze_calibrated_revision(**kwargs, calibration_id='cal', coefficients=[(1, (0, 0))], halfplanes=[])
        with self.assertRaisesRegex(ValueError, 'observed beats'):
            freeze_calibrated_revision(**kwargs, calibration_id='cal', coefficients={9: (0, 0)}, halfplanes=[])
        with self.assertRaisesRegex(ValueError, 'alpha, beta'):
            freeze_calibrated_revision(**kwargs, calibration_id='cal', coefficients={1: (0,), 2: (0, 0)}, halfplanes=[])
        with self.assertRaisesRegex(ValueError, 'exact rational'):
            freeze_calibrated_revision(
                **kwargs, calibration_id='cal',
                coefficients={1: (0.5, 0), 2: (0, 0)}, halfplanes=[],
            )
        with self.assertRaisesRegex(ValueError, 'exact rational'):
            freeze_calibrated_revision(
                **kwargs, calibration_id='cal',
                coefficients={1: (True, 0), 2: (0, 0)}, halfplanes=[],
            )
        with self.assertRaisesRegex(ValueError, 'halfplane must be'):
            freeze_calibrated_revision(
                **kwargs, calibration_id='cal',
                coefficients={1: (0, 0), 2: (0, 0)}, halfplanes=[(1, 0)],
            )
        with self.assertRaisesRegex(ValueError, 'iterable'):
            freeze_calibrated_revision(
                **kwargs, calibration_id='cal',
                coefficients={1: (0, 0), 2: (0, 0)}, halfplanes=42,
            )
        with self.assertRaises(LookupError):
            freeze_calibrated_revision(
                self.directory, self.station, self.issues, 'unknown-rev',
                'cal', {1: (0, 0)}, [],
            )

    def test_rational_input_accepts_v1_forms_only(self):
        self.assertEqual(rational_input(Fraction(1, 3), 'x'), Fraction(1, 3))
        self.assertEqual(rational_input(2, 'x'), Fraction(2))
        self.assertEqual(rational_input('-7/2', 'x'), Fraction(-7, 2))
        for bad in (1.5, True, False, None, object()):
            with self.assertRaises(ValueError):
                rational_input(bad, 'x')

    def test_same_revision_can_carry_distinct_calibration_declarations(self):
        open_round(self.directory, 'multi', 1, 2)
        revision = record_segment(
            self.directory, self.station, 'multi', 'day', 1, 2, [(1, 0), (2, 0)],
        )
        first = freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            'cal-a', {1: (1, 0), 2: (1, 0)}, [],
        )
        second = freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            'cal-b', {1: (0, 1), 2: (0, 1)}, _planes([[1, 1, 1]]),
        )
        self.assertNotEqual(first.issue_id, second.issue_id)
        self.assertEqual(first.revision_id, second.revision_id)
        self.assertEqual(second.halfplanes, (HalfPlane(1, 1, 1),))


class ReceiptVerificationTests(CalibrationLedgerCase):
    def _two_segments(self, round_id='receipt', halfplanes=()):
        open_round(self.directory, round_id, 1, 4)
        day = self.calibrated_segment(
            round_id, 'day', 1, [0, 0, 0],
            {1: (0, 0), 2: (0, 0), 3: (1, 1)}, 'cal-x', halfplanes,
        )
        night = self.calibrated_segment(
            round_id, 'night', 4, [0], {4: (1, 1)}, 'cal-x', halfplanes,
        )
        return day, night

    def test_valid_v2_parcel_is_accepted_and_reloaded(self):
        day, night = self._two_segments()
        accepted_day = self.accept_parcel(day)
        accepted_night = self.accept_parcel(night)
        self.assertTrue(accepted_day.receipt_id.startswith('receipt-'))
        reloaded = load_accepted(self.receipts, accepted_day.receipt_id)
        self.assertEqual(reloaded, accepted_day)
        self.assertEqual(reloaded.parcel.calibration_id, 'cal-x')
        self.assertNotEqual(accepted_day.receipt_id, accepted_night.receipt_id)

    def test_re_receipt_ignores_halfplane_order_and_json_formatting(self):
        day, _ = self._two_segments(halfplanes=_planes([[1, 0, 1], [0, 1, 1]]))
        original = self.accept_parcel(day)
        body = json.loads(original.body)
        body['halfplanes'].reverse()
        body['contributions'].reverse()
        repeated = accept_parcel(self.directory, self.receipts, json.dumps(body, indent=2))
        self.assertEqual(repeated, original)

    def test_duplicate_halfplanes_keep_their_multiplicity(self):
        day, _ = self._two_segments(halfplanes=_planes([[1, 0, 1], [1, 0, 1]]))
        original = self.accept_parcel(day)
        body = json.loads(original.body)
        self.assertEqual(len(body['halfplanes']), 2)
        body['halfplanes'].pop()
        with self.assertRaisesRegex(ValueError, 'different body'):
            accept_parcel(self.directory, self.receipts, json.dumps(body))

    def test_changed_coefficients_or_halfplanes_under_same_issue_are_rejected(self):
        day, _ = self._two_segments()
        original = self.accept_parcel(day)
        altered = json.loads(original.body)
        for fragment in altered['contributions']:
            if fragment['width'] == 2 and fragment['index'] == 1:
                fragment['alpha_sum'] = ['3', '1']
        with self.assertRaises(ValueError):
            accept_parcel(self.directory, self.receipts, json.dumps(altered))
        constrained = json.loads(original.body)
        constrained['halfplanes'] = [[['1', '1'], ['0', '1'], ['0', '1']]]
        with self.assertRaisesRegex(ValueError, 'different body'):
            accept_parcel(self.directory, self.receipts, json.dumps(constrained))
        # The first accepted parcel and its first-execution receipt survive.
        self.assertEqual(load_accepted(self.receipts, original.receipt_id), original)

    def test_structural_and_double_width_checks_reject_bad_v2_bodies(self):
        day, _ = self._two_segments()
        original = json.loads(self.accept_parcel(day).body)
        variants = {
            'missing_alpha': lambda body: body['contributions'][0].pop('alpha_sum'),
            'broken_double_width': lambda body: next(
                item for item in body['contributions'] if item['width'] == 4
            ).__setitem__('beta_sum', ['9', '1']),
            'missing_fragment': lambda body: body['contributions'].pop(),
            'bad_version': lambda body: body.__setitem__('version', 3),
            'missing_calibration': lambda body: body.pop('calibration_id'),
            'bad_rational': lambda body: body['contributions'][0].__setitem__(
                'alpha_sum', ['1', '0']),
            'unknown_round': lambda body: body['round'].__setitem__('round_id', 'no-such-round'),
        }
        for name, mutation in variants.items():
            body = json.loads(json.dumps(original))
            body['issue_id'] = f'bad-v2-{name}'
            mutation(body)
            with self.subTest(name=name), self.assertRaises(ValueError):
                accept_parcel(self.directory, self.receipts, json.dumps(body))

    def test_fully_missing_fragment_requires_all_three_zero_sums(self):
        open_round(self.directory, 'all-missing', 1, 3)
        revision = record_segment(
            self.directory, self.station, 'all-missing', 'day', 1, 3,
            [(1, None), (2, None), (3, 0)],
        )
        parcel = freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            'cal-m', {3: (1, 0)}, [],
        )
        body = json.loads(encode_parcel(parcel))
        fragment = next(item for item in body['contributions'] if item['width'] == 2 and item['index'] == 0)
        self.assertEqual((fragment['sum'], fragment['alpha_sum'], fragment['beta_sum']),
                         (['0', '1'], ['0', '1'], ['0', '1']))
        self.accept_parcel(parcel)
        bad = json.loads(json.dumps(body))
        bad['issue_id'] = 'bad-missing-sum'
        next(item for item in bad['contributions'] if item['width'] == 2 and item['index'] == 0)['alpha_sum'] = ['1', '1']
        with self.assertRaisesRegex(ValueError, 'zero sums'):
            accept_parcel(self.directory, self.receipts, json.dumps(bad))


class DomainGeometryTests(CalibrationLedgerCase):
    def test_box_only_domain_is_a_polygon_with_four_vertices(self):
        domain = build_domain(())
        self.assertEqual(domain.kind, 'polygon')
        self.assertEqual(
            sorted(domain.vertices),
            sorted([
                (Fraction(-1), Fraction(-1)), (Fraction(-1), Fraction(1)),
                (Fraction(1), Fraction(-1)), (Fraction(1), Fraction(1)),
            ]),
        )
        self.assertEqual(len(domain.edges()), 4)

    def test_empty_domain_is_detected_even_with_pairs(self):
        domain = build_domain(_planes([[1, 0, 0], [-1, 0, 0], [1, 0, 1], [-1, 0, -1]]))
        self.assertEqual(domain.kind, 'empty')
        self.assertEqual(domain.vertices, ())

    def test_singleton_and_segment_domains(self):
        singleton = build_domain(_planes([
            [1, 0, '1/2'], [-1, 0, '-1/2'], [0, 1, '1/4'], [0, -1, '-1/4'],
        ]))
        self.assertEqual(singleton.kind, 'point')
        self.assertEqual(singleton.vertices, ((Fraction(1, 2), Fraction(1, 4)),))
        self.assertEqual(singleton.edges(), ())

        segment = build_domain(_planes([[1, -1, 1], [-1, 1, -1]]))
        self.assertEqual(segment.kind, 'segment')
        self.assertEqual(
            sorted(segment.vertices),
            sorted([(Fraction(0), Fraction(-1)), (Fraction(1), Fraction(0))]),
        )
        self.assertTrue(segment.contains((Fraction(1, 2), Fraction(-1, 2))))
        self.assertFalse(segment.contains((Fraction(1), Fraction(1))))

    def test_redundant_and_duplicated_constraints_do_not_inflate_vertices(self):
        domain = build_domain(_planes([
            [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1],
            [1, 0, 2], [1, 0, 1],
        ]))
        self.assertEqual(domain.kind, 'polygon')
        self.assertEqual(len(domain.vertices), 4)

    def test_feasible_vertices_are_exact_fractions(self):
        vertices = feasible_vertices(_planes([[2, 1, 0]]))
        for a, b in vertices:
            self.assertIsInstance(a, Fraction)
            self.assertIsInstance(b, Fraction)
        # 2a + b = 0 crosses the parameter box at these exact boundary points.
        self.assertIn((Fraction(-1, 2), Fraction(1)), vertices)
        self.assertIn((Fraction(1, 2), Fraction(-1)), vertices)


class RangePublicationTests(CalibrationLedgerCase):
    def _publish_fixture(self, case, round_id):
        first, cut, values = case['first'], case['cut'], case['values']
        last = first + len(values) - 1
        open_round(self.directory, round_id, first, last)
        calibration_id = f"cal-{case['id']}"

        def build(segment_id, lo, hi, planes):
            entries = [
                (beat, None if values[beat - first] is None else Fraction(values[beat - first]))
                for beat in range(lo, hi + 1)
            ]
            revision = record_segment(
                self.directory, self.station, round_id, segment_id, lo, hi, entries,
            )
            coefficients = {
                beat: (
                    Fraction(case['coefficients'][beat - first][0]),
                    Fraction(case['coefficients'][beat - first][1]),
                )
                for beat in range(lo, hi + 1)
                if case['coefficients'][beat - first] is not None
                and values[beat - first] is not None
            }
            parcel = freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                calibration_id, coefficients, _planes(planes),
            )
            return self.accept_parcel(parcel).receipt_id

        day = build('day', first, first + cut - 1, case['day'])
        night = build('night', first + cut, last, case['night'])
        return publish_calibrated_report(
            self.directory, self.receipts, self.reports, round_id, case['width'], (day, night),
        )

    def test_all_hand_calculated_fixtures(self):
        fixtures = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
        for case in fixtures:
            with self.subTest(case=case['id']):
                report = self._publish_fixture(case, f"fixture-{case['id']}")
                result = report.result
                self.assertIsInstance(report, CalibrationReportRecord)
                self.assertEqual(result.status, case['status'])
                self.assertEqual(result.pair_count, case['pairs'])
                if case['range'] is None:
                    self.assertIsNone(result.lower)
                    self.assertIsNone(result.upper)
                    self.assertIsNone(result.lower_at)
                    self.assertIsNone(result.upper_at)
                    continue
                self.assertEqual(result.lower, Fraction(case['range'][0]))
                self.assertEqual(result.upper, Fraction(case['range'][1]))
                # Witnesses must lie in the shared domain and hit the endpoints.
                self.assertTrue(result.domain.contains(result.lower_at))
                self.assertTrue(result.domain.contains(result.upper_at))
                exported = json.loads(export_report(self.reports, report.report_id))
                self.assertEqual(exported['calibration_id'], f"cal-{case['id']}")
                self.assertEqual(exported['result']['unit'], 'μm²')
                self.assertEqual(exported['result']['lower'],
                                 [str(result.lower.numerator), str(result.lower.denominator)])
                self.assertEqual(
                    exported['result']['lower_at'],
                    [[str(result.lower_at[0].numerator), str(result.lower_at[0].denominator)],
                     [str(result.lower_at[1].numerator), str(result.lower_at[1].denominator)]],
                )

    def test_witness_substitution_reproduces_each_endpoint(self):
        fixtures = {case['id']: case for case in json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))}
        case = fixtures['shared-pair-minimum']
        report = self._publish_fixture(case, 'substitution')
        from receipts.selection import select_calibrated_receipts
        from rounds.registry import load_round

        spec = load_round(self.directory, 'substitution')
        selection = select_calibrated_receipts(
            self.receipts, spec, report.receipt_ids,
        )
        boxes = qualify_calibrated_boxes(selection, 2)
        constant, linear, hessian = _quadratic_parts(calibrated_differences(boxes))
        self.assertEqual(
            evaluate(report.result.lower_at, constant, linear, hessian),
            report.result.lower,
        )
        self.assertEqual(
            evaluate(report.result.upper_at, constant, linear, hessian),
            report.result.upper,
        )

    def test_infeasible_domain_still_reports_coverage_pair_count(self):
        case = next(item for item in json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
                    if item['id'] == 'no-domain')
        report = self._publish_fixture(case, 'infeasible-round')
        self.assertEqual(report.result.status, 'infeasible')
        self.assertEqual(report.result.pair_count, 1)
        exported = json.loads(export_report(self.reports, report.report_id))
        self.assertEqual(exported['result'], {
            'pair_count': 1, 'status': 'infeasible',
            'lower': None, 'upper': None, 'lower_at': None, 'upper_at': None,
            'unit': 'μm²',
        })

    def test_mixed_calibration_ids_and_v1_receipts_are_rejected(self):
        open_round(self.directory, 'mixed', 1, 4)
        first = self.calibrated_segment(
            'mixed', 'day', 1, [0, 0, 0],
            {1: (0, 0), 2: (0, 0), 3: (0, 0)}, 'cal-a',
        )
        second = self.calibrated_segment(
            'mixed', 'night', 4, [0], {4: (0, 0)}, 'cal-b',
        )
        ids = (self.accept_parcel(first).receipt_id, self.accept_parcel(second).receipt_id)
        before = self.publication_counts()
        with self.assertRaisesRegex(ValueError, 'share one calibration ID'):
            publish_calibrated_report(
                self.directory, self.receipts, self.reports, 'mixed', 2, ids,
            )
        self.assertEqual(self.publication_counts(), before)

        # A V1 receipt cannot enter a calibrated report.
        open_round(self.directory, 'mixed-v1', 1, 4)
        v1_revision = record_segment(
            self.directory, self.station, 'mixed-v1', 'day', 1, 3, [(1, 0), (2, 0), (3, 0)],
        )
        v1 = self.receive(v1_revision)
        with self.assertRaisesRegex(ValueError, 'version 2 receipts'):
            publish_calibrated_report(
                self.directory, self.receipts, self.reports, 'mixed-v1', 2, (v1.receipt_id, ids[1]),
            )

    def test_v1_point_report_rejects_v2_receipts(self):
        open_round(self.directory, 'guard', 1, 2)
        parcel = self.calibrated_segment(
            'guard', 'day', 1, [0, 0], {1: (0, 0), 2: (0, 0)}, 'cal-guard',
        )
        receipt_id = self.accept_parcel(parcel).receipt_id
        with self.assertRaisesRegex(ValueError, 'version 1 receipts'):
            publish_report(
                self.directory, self.receipts, self.reports, 'guard', 2, (receipt_id,),
            )

    def test_coverage_gap_and_unknown_receipt_leave_no_calibrated_report(self):
        open_round(self.directory, 'gap', 1, 4)
        day = self.calibrated_segment(
            'gap', 'day', 1, [0, 0, 0],
            {1: (0, 0), 2: (0, 0), 3: (0, 0)}, 'cal-gap',
        )
        receipt_id = self.accept_parcel(day).receipt_id
        with self.assertRaisesRegex(ValueError, 'coverage gap'):
            publish_calibrated_report(
                self.directory, self.receipts, self.reports, 'gap', 2, (receipt_id,),
            )
        with self.assertRaisesRegex(LookupError, 'unknown receipt'):
            publish_calibrated_report(
                self.directory, self.receipts, self.reports, 'gap', 2,
                (receipt_id, 'receipt-unknown'),
            )
        self.assertEqual(self.publication_counts(), (0, 0, 0))

    def test_parents_follow_request_order_and_keep_lineage(self):
        case = next(item for item in json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
                    if item['id'] == 'open-box')
        report = self._publish_fixture(case, 'lineage')
        self.assertEqual([parent.segment_id for parent in report.parents], ['day', 'night'])
        exported = json.loads(export_report(self.reports, report.report_id))
        self.assertEqual(
            [parent['segment_id'] for parent in exported['parents']], ['day', 'night'],
        )
        for parent in report.parents:
            accepted = load_accepted(self.receipts, parent.receipt_id)
            self.assertEqual(accepted.parcel.calibration_id, report.calibration_id)
        scenario(
            'cal.open_box',
            {'width': 2, 'calibration': 'shared (a,b) box [-1,1]'},
            {'status': 'measured', 'range': ['0', '2']},
            {'status': report.result.status,
             'range': [str(report.result.lower), str(report.result.upper)]},
            {'parents': ['day', 'night']},
            {'parents': [parent.segment_id for parent in report.parents]},
            ['reports/calibration_analysis.py', 'reports/domain.py', 'reports/publish.py'],
            'd = a + b on [(-1,-1),(1,1)] ranges from 0 to 2; stability is d^2/2.',
        )


class PersistenceAndReopenTests(CalibrationLedgerCase):
    def test_finalized_calibrated_report_survives_reopen(self):
        fixtures = {case['id']: case for case in json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))}
        case = fixtures['singleton']
        first, cut, values = case['first'], case['cut'], case['values']
        last = first + len(values) - 1
        open_round(self.directory, 'reopen-cal', first, last)

        def build(segment_id, lo, hi, planes):
            revision = record_segment(
                self.directory, self.station, 'reopen-cal', segment_id, lo, hi,
                [(beat, Fraction(values[beat - first])) for beat in range(lo, hi + 1)],
            )
            coefficients = {
                beat: (
                    Fraction(case['coefficients'][beat - first][0]),
                    Fraction(case['coefficients'][beat - first][1]),
                )
                for beat in range(lo, hi + 1)
            }
            parcel = freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                'cal-reopen', coefficients, _planes(planes),
            )
            return self.accept_parcel(parcel).receipt_id

        ids = (
            build('day', first, first + cut - 1, case['day']),
            build('night', first + cut, last, case['night']),
        )
        report = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'reopen-cal', 2, ids,
        )
        exported_before = export_report(self.reports, report.report_id)

        self.center.close()
        self.open_center()
        self.receipts.initialize()
        self.reports.initialize()
        reopened = load_report(self.reports, report.report_id)
        self.assertIsInstance(reopened, CalibrationReportRecord)
        self.assertEqual(reopened.report_id, report.report_id)
        self.assertEqual(reopened.calibration_id, 'cal-reopen')
        self.assertEqual(reopened.result.pair_count, report.result.pair_count)
        self.assertEqual(reopened.result.status, report.result.status)
        self.assertEqual(reopened.result.lower, report.result.lower)
        self.assertEqual(reopened.result.upper, report.result.upper)
        self.assertEqual(reopened.result.lower_at, report.result.lower_at)
        self.assertEqual(reopened.result.upper_at, report.result.upper_at)
        self.assertEqual(reopened.parents, report.parents)
        self.assertEqual(reopened.ack_id, report.ack_id)
        self.assertEqual(export_report(self.reports, report.report_id), exported_before)
        for receipt_id in ids:
            self.assertEqual(load_accepted(self.receipts, receipt_id).receipt_id, receipt_id)
        with self.assertRaisesRegex(LookupError, 'unknown report'):
            load_report(self.reports, 'calibration-report-missing')

    def test_v1_and_v2_reports_coexist_and_dispatch_on_reload(self):
        open_round(self.directory, 'coexist', 1, 2)
        v1_revision = record_segment(
            self.directory, self.station, 'coexist', 'day', 1, 2, [(1, 0), (2, 2)],
        )
        v1_receipt = self.receive(v1_revision)
        v1_report = publish_report(
            self.directory, self.receipts, self.reports, 'coexist', 2, (v1_receipt.receipt_id,),
        )
        v2 = self.calibrated_segment(
            'coexist', 'shift', 1, [0, 2], {1: (0, 0), 2: (0, 0)}, 'cal-coexist',
        )
        # A second round is needed because segments are unique per round.
        open_round(self.directory, 'coexist-2', 1, 2)
        v2_revision = record_segment(
            self.directory, self.station, 'coexist-2', 'day', 1, 2, [(1, 0), (2, 2)],
        )
        v2_parcel = freeze_calibrated_revision(
            self.directory, self.station, self.issues, v2_revision.revision_id,
            'cal-coexist', {1: (0, 0), 2: (0, 0)}, [],
        )
        v2_receipt = self.accept_parcel(v2_parcel)
        v2_report = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'coexist-2', 2, (v2_receipt.receipt_id,),
        )
        self.assertIsInstance(load_report(self.reports, v1_report.report_id), type(v1_report))
        self.assertIsInstance(load_report(self.reports, v2_report.report_id), CalibrationReportRecord)
        v1_export = json.loads(export_report(self.reports, v1_report.report_id))
        v2_export = json.loads(export_report(self.reports, v2_report.report_id))
        self.assertIn('value', v1_export['result'])
        self.assertNotIn('calibration_id', v1_export)
        self.assertIn('calibration_id', v2_export)
        self.assertEqual(
            set(v2_export['result']),
            {'pair_count', 'status', 'lower', 'upper', 'lower_at', 'upper_at', 'unit'},
        )

    def test_acknowledgment_failure_rolls_back_calibrated_report(self):
        open_round(self.directory, 'rollback-cal', 1, 2)
        parcel = self.calibrated_segment(
            'rollback-cal', 'day', 1, [0, 0], {1: (0, 0), 2: (0, 0)}, 'cal-rollback',
        )
        receipt_id = self.accept_parcel(parcel).receipt_id
        before = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'rollback-cal', 2, (receipt_id,),
        )
        counts = (
            self.center.execute('SELECT count(*) FROM calibration_reports').fetchone()[0],
            self.center.execute('SELECT count(*) FROM calibration_report_parents').fetchone()[0],
            self.center.execute('SELECT count(*) FROM calibration_report_acknowledgments').fetchone()[0],
        )
        self.center.execute('''CREATE TEMP TRIGGER reject_cal_ack
            BEFORE INSERT ON main.calibration_report_acknowledgments
            BEGIN SELECT RAISE(ABORT, 'acknowledgment unavailable'); END''')
        import sqlite3
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'acknowledgment unavailable'):
            publish_calibrated_report(
                self.directory, self.receipts, self.reports, 'rollback-cal', 2, (receipt_id,),
            )
        self.assertEqual(
            (
                self.center.execute('SELECT count(*) FROM calibration_reports').fetchone()[0],
                self.center.execute('SELECT count(*) FROM calibration_report_parents').fetchone()[0],
                self.center.execute('SELECT count(*) FROM calibration_report_acknowledgments').fetchone()[0],
            ),
            counts,
        )
        self.center.execute('DROP TRIGGER temp.reject_cal_ack')
        retry = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'rollback-cal', 2, (receipt_id,),
        )
        self.assertNotEqual(before.report_id, retry.report_id)
        reloaded = load_report(self.reports, retry.report_id)
        self.assertEqual(reloaded.report_id, retry.report_id)
        self.assertEqual(reloaded.result.status, retry.result.status)
        self.assertEqual(reloaded.result.lower, retry.result.lower)
        self.assertEqual(reloaded.result.upper, retry.result.upper)
        self.assertEqual(reloaded.parents, retry.parents)
        self.assertEqual(reloaded.ack_id, retry.ack_id)


class FixtureFileTests(CalibrationLedgerCase):
    def test_fixture_count_and_statuses(self):
        fixtures = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
        self.assertEqual(len(fixtures), 9)
        statuses = sorted(item['status'] for item in fixtures)
        self.assertEqual(statuses.count('measured'), 7)
        self.assertEqual(statuses.count('infeasible'), 1)
        self.assertEqual(statuses.count('insufficient'), 1)
        for case in fixtures:
            self.assertEqual(len(case['values']), len(case['coefficients']))


class SolverBranchTests(CalibrationLedgerCase):
    def _report(self, round_id, values, coefficients, width, halfplanes=(), cut=None):
        first = 1
        cut = cut if cut is not None else len(values) // 2
        last = len(values)
        open_round(self.directory, round_id, first, last)

        def build(segment_id, lo, hi):
            revision = record_segment(
                self.directory, self.station, round_id, segment_id, lo, hi,
                [(beat, Fraction(values[beat - 1])) for beat in range(lo, hi + 1)],
            )
            parcel = freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                f'cal-{round_id}',
                {beat: coefficients[beat - 1] for beat in range(lo, hi + 1)
                 if coefficients[beat - 1] is not None},
                _planes(halfplanes),
            )
            return self.accept_parcel(parcel).receipt_id

        ids = (build('day', first, cut), build('night', cut + 1, last))
        return publish_calibrated_report(
            self.directory, self.receipts, self.reports, round_id, width, ids,
        )

    def test_singular_hessian_linear_form_uses_vertex_extrema(self):
        # One pair with nominal offset so d = -(1 + a): purely affine, Hessian zero.
        report = self._report(
            'linear', [1, 1, 0, 0],
            [(0, 0), (0, 0), (1, 0), (1, 0)], 2,
        )
        result = report.result
        self.assertEqual(result.status, 'measured')
        # d = -(1 + a) spans [-2, 0], f = d^2/2 spans [0, 2].
        self.assertEqual(result.lower, Fraction(0))
        self.assertEqual(result.upper, Fraction(2))
        self.assertEqual(result.lower_at, (Fraction(1), Fraction(-1)))
        self.assertEqual(result.upper_at, (Fraction(-1), Fraction(-1)))

    def test_edge_stationary_minimum_on_a_constrained_segment(self):
        # The shifted-line fixture forces the minimizer into the segment interior.
        case = next(item for item in json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
                    if item['id'] == 'shifted-line')
        first, cut, values = case['first'], case['cut'], case['values']
        last = first + len(values) - 1
        open_round(self.directory, 'edge-min', first, last)

        def build(segment_id, lo, hi, planes):
            revision = record_segment(
                self.directory, self.station, 'edge-min', segment_id, lo, hi,
                [(beat, Fraction(values[beat - first])) for beat in range(lo, hi + 1)],
            )
            coefficients = {
                beat: (Fraction(case['coefficients'][beat - first][0]),
                       Fraction(case['coefficients'][beat - first][1]))
                for beat in range(lo, hi + 1)
            }
            parcel = freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                'cal-edge-min', coefficients, _planes(planes),
            )
            return self.accept_parcel(parcel).receipt_id

        ids = (
            build('day', first, first + cut - 1, case['day']),
            build('night', first + cut, last, case['night']),
        )
        report = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'edge-min', 2, ids,
        )
        self.assertEqual(report.result.lower, Fraction(0))
        self.assertEqual(report.result.upper, Fraction(1, 2))
        # Lower witness sits strictly inside the segment, not at a box vertex.
        self.assertEqual(report.result.lower_at, (Fraction(1, 2), Fraction(-1, 2)))

    def test_invertible_hessian_interior_stationary_point_is_found(self):
        # Three adjacent pairs give a positive definite Hessian and an
        # unconstrained stationary point that is not a box vertex.
        values = [0, 0, 1, 1, 0, 0, 1, 1]
        coefficients = [
            (0, 0), (0, 0),
            (1, 0), (1, 0),
            (1, 1), (1, 1),
            (0, 1), (0, 1),
        ]
        report = self._report('interior-hessian', values, coefficients, 2, cut=4)
        result = report.result
        self.assertEqual(result.pair_count, 3)
        self.assertEqual(result.domain.kind, 'polygon')
        # Differences d0 = 1+a, d1 = -1+b, d2 = 1-a give the interior
        # stationary point (a, b) = (0, 1) with value 1/3.
        self.assertEqual(result.lower_at, (Fraction(0), Fraction(1)))
        self.assertEqual(result.lower, Fraction(1, 3))
        self.assertTrue(result.domain.contains(result.lower_at))

    def test_equality_halfplanes_shrink_to_a_singleton_with_measured_value(self):
        case = next(item for item in json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
                    if item['id'] == 'singleton')
        first, cut, values = case['first'], case['cut'], case['values']
        last = first + len(values) - 1
        open_round(self.directory, 'solo', first, last)

        def build(segment_id, lo, hi, planes):
            revision = record_segment(
                self.directory, self.station, 'solo', segment_id, lo, hi,
                [(beat, Fraction(values[beat - first])) for beat in range(lo, hi + 1)],
            )
            coefficients = {
                beat: (Fraction(case['coefficients'][beat - first][0]),
                       Fraction(case['coefficients'][beat - first][1]))
                for beat in range(lo, hi + 1)
            }
            parcel = freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                'cal-solo', coefficients, _planes(planes),
            )
            return self.accept_parcel(parcel).receipt_id

        ids = (
            build('day', first, first + cut - 1, case['day']),
            build('night', first + cut, last, case['night']),
        )
        report = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'solo', 2, ids,
        )
        self.assertEqual(report.result.domain.kind, 'point')
        self.assertEqual(report.result.lower, report.result.upper)
        self.assertEqual(report.result.lower_at, report.result.upper_at)

    def test_constant_statistic_gives_equal_endpoints_with_a_feasible_witness(self):
        open_round(self.directory, 'flat', 1, 4)
        ids = []
        for segment_id, lo, hi in (('day', 1, 2), ('night', 3, 4)):
            revision = record_segment(
                self.directory, self.station, 'flat', segment_id, lo, hi,
                [(beat, 0) for beat in range(lo, hi + 1)],
            )
            parcel = freeze_calibrated_revision(
                self.directory, self.station, self.issues, revision.revision_id,
                'cal-flat', {beat: (0, 0) for beat in range(lo, hi + 1)}, [],
            )
            ids.append(self.accept_parcel(parcel).receipt_id)
        report = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'flat', 2, ids,
        )
        self.assertEqual(report.result.lower, Fraction(0))
        self.assertEqual(report.result.upper, Fraction(0))
        self.assertTrue(report.result.domain.contains(report.result.lower_at))

    def test_infeasible_domain_takes_precedence_over_zero_pairs(self):
        open_round(self.directory, 'tiny', 1, 2)
        revision = record_segment(
            self.directory, self.station, 'tiny', 'day', 1, 2, [(1, 0), (2, 0)],
        )
        parcel = freeze_calibrated_revision(
            self.directory, self.station, self.issues, revision.revision_id,
            'cal-tiny', {1: (0, 0), 2: (0, 0)},
            _planes([[1, 0, 0], [-1, 0, 0], [1, 0, 1], [-1, 0, -1]]),
        )
        receipt_id = self.accept_parcel(parcel).receipt_id
        report = publish_calibrated_report(
            self.directory, self.receipts, self.reports, 'tiny', 2, (receipt_id,),
        )
        self.assertEqual(report.result.status, 'infeasible')
        self.assertEqual(report.result.pair_count, 0)
        self.assertIsNone(report.result.lower)

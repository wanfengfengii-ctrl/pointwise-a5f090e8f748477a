from dataclasses import asdict
import json

from reports.store import (
    CalibrationReportRecord,
    ReportRecord,
    ReportStore,
)
from rounds.validation import require_identifier


def load_report(
    reports: ReportStore, report_id: str,
) -> ReportRecord | CalibrationReportRecord:
    require_identifier(report_id, 'report ID')
    return reports.get_any(report_id)


def _rational_pair(value):
    return [str(value.numerator), str(value.denominator)]


def _export_calibrated(report: CalibrationReportRecord) -> dict:
    result = report.result
    if result.status == 'measured':
        lower = _rational_pair(result.lower)
        upper = _rational_pair(result.upper)
        lower_at = [_rational_pair(result.lower_at[0]), _rational_pair(result.lower_at[1])]
        upper_at = [_rational_pair(result.upper_at[0]), _rational_pair(result.upper_at[1])]
    else:
        lower = upper = lower_at = upper_at = None
    return {
        'report_id': report.report_id,
        'round_id': report.round_id,
        'width': report.width,
        'calibration_id': report.calibration_id,
        'result': {
            'pair_count': result.pair_count,
            'status': result.status,
            'lower': lower,
            'upper': upper,
            'lower_at': lower_at,
            'upper_at': upper_at,
            'unit': 'μm²',
        },
        'parents': [asdict(parent) for parent in report.parents],
        'ack_id': report.ack_id,
    }


def export_report(reports: ReportStore, report_id: str) -> str:
    report = load_report(reports, report_id)
    if isinstance(report, CalibrationReportRecord):
        return json.dumps(_export_calibrated(report), ensure_ascii=False, sort_keys=True)
    value = report.result.value
    body = {
        'report_id': report.report_id,
        'round_id': report.round_id,
        'width': report.width,
        'result': {
            'pair_count': report.result.pair_count,
            'status': report.result.status,
            'value': [str(value.numerator), str(value.denominator)] if value is not None else None,
            'unit': 'μm²',
        },
        'parents': [asdict(parent) for parent in report.parents],
        'ack_id': report.ack_id,
    }
    return json.dumps(body, ensure_ascii=False, sort_keys=True)

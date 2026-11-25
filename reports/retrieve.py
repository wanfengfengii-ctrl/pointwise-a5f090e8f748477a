from dataclasses import asdict
import json

from reports.store import ReportRecord, ReportStore
from rounds.validation import require_identifier


def load_report(reports: ReportStore, report_id: str) -> ReportRecord:
    require_identifier(report_id, 'report ID')
    return reports.get(report_id)


def export_report(reports: ReportStore, report_id: str) -> str:
    report = load_report(reports, report_id)
    value = report.result.value
    return json.dumps(
        {
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
        },
        ensure_ascii=False,
        sort_keys=True,
    )

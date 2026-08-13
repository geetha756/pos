"""Create the Machine E2E workbook from the current Playwright JSON result."""
import json
import re
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / 'test-report' / 'results' / 'results.json'
OUTPUT = ROOT / 'reports' / 'machine-test-report.xlsx'
data = json.loads(RESULTS.read_text(encoding='utf-8'))
status_map = {'passed': 'Passed', 'failed': 'Failed', 'skipped': 'Skipped', 'timedOut': 'Failed', 'interrupted': 'Failed'}

def specs(suites):
    for suite in suites:
        yield from suite.get('specs', [])
        yield from specs(suite.get('suites', []))

rows = []
for spec in specs(data['suites']):
    match = re.match(r'(MCH-\d+)\s+-\s+(.*)', spec['title'])
    if not match:
        continue
    result = spec['tests'][0]['results'][0]
    state = status_map.get(result['status'], 'Skipped')
    error = ''
    screenshot = ''
    if result.get('errors'):
        error = re.sub(r'\x1b\[[0-9;]*m', '', result['errors'][0].get('message', '')).split('\n')[0]
    for attachment in result.get('attachments', []):
        if attachment.get('name') == 'screenshot':
            screenshot = attachment.get('path', '')
    title = match.group(2)
    kind = 'Negative' if any(word in title.lower() for word in ('failure', 'invalid', 'error', 'empty', 'blocks')) else 'Positive'
    rows.append((match.group(1), 'Machine Management', title, kind,
                 'All assertions in the automated scenario pass.',
                 'All assertions passed.' if state == 'Passed' else 'Automated assertion failed.',
                state, error, screenshot))

wb = Workbook()
summary = wb.active
summary.title = 'Summary'
summary.append(['Machine Management – Playwright E2E Report'])
summary['A1'].font = Font(size=16, bold=True, color='FFFFFF')
summary['A1'].fill = PatternFill('solid', fgColor='1F3D2E')
summary.merge_cells('A1:C1')
total = len(rows); passed = sum(r[6] == 'Passed' for r in rows); failed = sum(r[6] == 'Failed' for r in rows); skipped = sum(r[6] == 'Skipped' for r in rows)
for row in [('Total test cases', total), ('Passed', passed), ('Failed', failed), ('Skipped', skipped),
            ('Positive cases', sum(r[3] == 'Positive' for r in rows)), ('Negative cases', sum(r[3] == 'Negative' for r in rows)),
            ('Pass percentage', f'{(passed / total * 100):.1f}%' if total else '0.0%')]:
    summary.append(row)
summary.append([])
summary.append(['Run source', str(RESULTS)])
summary.append(['Resolved defect', 'MCH-008 identified that Enter re-opened the graph-type combobox after commit. The capture handler now stops propagation after committing; the final full run passed.'])
summary.column_dimensions['A'].width = 24; summary.column_dimensions['B'].width = 100

sheet = wb.create_sheet('Test Results')
headers = ['Test ID', 'Module', 'Test Case', 'Type', 'Expected Result', 'Actual Result', 'Status', 'Error', 'Screenshot']
sheet.append(headers)
for cell in sheet[1]:
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = PatternFill('solid', fgColor='1F3D2E')
for row in rows:
    sheet.append(row)
for row in sheet.iter_rows():
    for cell in row:
        cell.alignment = Alignment(vertical='top', wrap_text=True)
for col, width in zip('ABCDEFGHI', [12, 22, 48, 12, 42, 32, 12, 70, 60]):
    sheet.column_dimensions[col].width = width
sheet.freeze_panes = 'A2'
for index, row in enumerate(rows, start=2):
    fill = 'E6F6EE' if row[6] == 'Passed' else ('FDEAEA' if row[6] == 'Failed' else 'FBF2E2')
    sheet.cell(index, 7).fill = PatternFill('solid', fgColor=fill)

OUTPUT.parent.mkdir(exist_ok=True)
wb.save(OUTPUT)
print(f'Saved {OUTPUT} with {total} actual results ({passed} passed, {failed} failed, {skipped} skipped).')

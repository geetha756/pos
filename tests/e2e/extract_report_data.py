import json
import re
from pathlib import Path

RESULTS_JSON = Path('test-report/results/results.json')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
TITLE_RE = re.compile(r'^([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s*(?:\(([a-zA-Z]+)\))?\s*[:\-]\s*(.*)$')
STATUS_MAP = {'passed': 'PASS', 'failed': 'FAIL', 'timedOut': 'FAIL', 'interrupted': 'FAIL', 'skipped': 'SKIPPED'}
NEGATIVE_KEYWORDS = (
    'failure', 'invalid', 'error', 'empty', 'blocks', 'blocked', 'not ', 'never ',
    'does not', "doesn't", 'stays hidden', 'without', 'no false', 'malformed',
    'absent', 'rejected', 'redirects to login', 'non-existent', 'left blank',
)


def walk_specs(suites, file_name=None):
    for suite in suites:
        fname = suite.get('file') or file_name
        for spec in suite.get('specs', []):
            yield fname, spec
        yield from walk_specs(suite.get('suites', []), fname)


def classify_kind(marker, scenario):
    if marker:
        m = marker.lower()
        if m.startswith('pos'):
            return 'Positive'
        if m.startswith('neg'):
            return 'Negative'
    lowered = scenario.lower()
    return 'Negative' if any(w in lowered for w in NEGATIVE_KEYWORDS) else 'Positive'


data = json.loads(RESULTS_JSON.read_text(encoding='utf-8'))
rows = []
for fname, spec in walk_specs(data['suites']):
    match = TITLE_RE.match(spec['title'])
    if not match:
        continue
    tc_id, marker, scenario = match.group(1), match.group(2), match.group(3)
    category = classify_kind(marker, scenario)
    test = spec['tests'][0]
    result = test['results'][0] if test['results'] else {}
    status = STATUS_MAP.get(result.get('status'), 'SKIPPED')
    duration_s = round((result.get('duration') or 0) / 1000, 1)
    error_message = ''
    if status == 'FAIL':
        errors = result.get('errors') or []
        msg = errors[0].get('message', '') if errors else 'Test failed.'
        error_message = ANSI_RE.sub('', msg).strip().split('\n')[0][:300]
    module = 'Machine' if ('machine' in (fname or '').lower()) else 'Staff'
    prefix = re.match(r'^[A-Za-z]+', tc_id).group(0)
    rows.append({
        'id': tc_id, 'prefix': prefix, 'module': module, 'category': category,
        'scenario': scenario, 'file': (fname or '').replace('\\', '/'), 'status': status,
        'error': error_message, 'duration': duration_s,
    })


def sort_key(r):
    m = re.search(r'(\d+)$', r['id'])
    return (r['module'], r['prefix'], int(m.group(1)) if m else 0)


rows.sort(key=sort_key)

out = {
    'runDate': data['stats'].get('startTime', ''),
    'durationMs': data['stats'].get('duration', 0),
    'rows': rows,
}
Path('tests/e2e/report-data.json').write_text(json.dumps(out), encoding='utf-8')
print('rows:', len(rows))
print('staff:', sum(1 for r in rows if r['module'] == 'Staff'))
print('machine:', sum(1 for r in rows if r['module'] == 'Machine'))

import json
from pathlib import Path
p = Path('playwright-test-output.json')
text = p.read_text('utf-16')
obj = json.loads(text)
print('root type', type(obj))
print('keys', list(obj.keys()))
print('stats', obj.get('stats'))
for s in obj.get('suites', [])[:2]:
    print('suite', s.get('title'), 'tests', len(s.get('tests', [])), 'suites', len(s.get('suites', [])))
    for t in s.get('tests', [])[:5]:
        print('  test', t.get('title'), t.get('result'), t.get('location'))
    for ss in s.get('suites', [])[:2]:
        print('  subsuite', ss.get('title'), 'tests', len(ss.get('tests', [])))
        for t in ss.get('tests', [])[:5]:
            print('    t', t.get('title'), t.get('result'))

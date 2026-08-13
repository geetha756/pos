import json
from pathlib import Path

p = Path('playwright-test-output.json')
text = p.read_text('utf-16')
obj = json.loads(text)
print('root type', type(obj))
print('root keys', list(obj.keys()))
print('stats', obj.get('stats'))


def walk_suite(suite, indent=0):
    prefix = '  ' * indent
    print(f"{prefix}suite title={suite.get('title')!r} tests={len(suite.get('tests', []))} suites={len(suite.get('suites', []))}")
    for test in suite.get('tests', []):
        print(f"{prefix}  TEST title={test.get('title')!r} result={test.get('result')} location={test.get('location')}")
    for subsuite in suite.get('suites', []):
        walk_suite(subsuite, indent + 1)

for top in obj.get('suites', []):
    walk_suite(top)
    print('top keys', list(top.keys()))
    for k,v in top.items():
        if isinstance(v, list):
            print('  top', k, len(v), 'sample type', type(v[0]).__name__ if v else 'none')
            if k == 'suites' and v:
                sub = v[0]
                print('  sub keys', list(sub.keys()))
                for kk,vv in sub.items():
                    if isinstance(vv, list):
                        print('    sub', kk, len(vv), 'sample type', type(vv[0]).__name__ if vv else 'none')
                if 'specs' in sub:
                    print('  specs in sub:', len(sub['specs']))
                    for i, spec in enumerate(sub['specs'][:10]):
                        print(f"    spec[{i}] title={spec.get('title')} result={spec.get('result')} keys={list(spec.keys())}")

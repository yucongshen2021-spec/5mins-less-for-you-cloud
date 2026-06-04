"""Verify a release zip — called by release.ps1."""
import sys, json, zipfile

zip_path = sys.argv[1]
expected_version = sys.argv[2]

with zipfile.ZipFile(zip_path, 'r') as z:
    names = z.namelist()
    prefix = [n for n in names if n.endswith('/RELEASE_INFO.json')][0].replace('RELEASE_INFO.json', '')

    ri = json.loads(z.read(prefix + 'RELEASE_INFO.json'))
    uc = json.loads(z.read(prefix + 'application/portal/update_config.json'))
    pngs = [n for n in names if n.endswith('.png') and 'runtime/' not in n]

    passed = 0
    failed = 0

    checks = [
        ('version=' + expected_version, ri.get('version') == expected_version),
        ('mirror_urls configured', len(uc.get('mirror_urls', [])) >= 2),
        ('no app PNGs', len(pngs) == 0),
    ]
    for name, ok in checks:
        if ok:
            passed += 1
            print('PASS  ' + name)
        else:
            failed += 1
            print('FAIL  ' + name)

    if failed == 0:
        print('ALL CHECKS PASSED')
        sys.exit(0)
    else:
        sys.exit(1)

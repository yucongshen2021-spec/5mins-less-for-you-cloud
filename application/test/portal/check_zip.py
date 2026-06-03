"""Check release zip for demo leaks."""
import zipfile, json, re, sys

zp = sys.argv[1] if len(sys.argv) > 1 else r'dist\帮你节省5分钟-release-1.1.4.zip'
with zipfile.ZipFile(zp, 'r') as z:
    names = z.namelist()
    prefix = [n for n in names if n.endswith('/RELEASE_INFO.json')][0].replace('RELEASE_INFO.json', '')

    html = z.read(prefix+'application/portal/templates/index.html').decode('utf-8')

    print('=== Checking for demo leaks in', zp, '===')
    bad_patterns = [
        ('DEMO', 'Demo badge text'),
        ('demo试用版', 'Demo description'),
        ('demo版', 'Demo mode text'),
        ('id="dlCard"', 'Download card (demo only)'),
        ('port 5000', 'Demo port reference'),
        ('class="ver-badge demo"', 'Demo badge CSS'),
        ('5000端口', 'Demo port Chinese'),
    ]

    found_any = False
    for pattern, desc in bad_patterns:
        if pattern in html:
            # Count occurrences
            count = html.count(pattern)
            print(f'  LEAK: "{pattern}" ({desc}) — found {count} time(s)')
            found_any = True

    if not found_any:
        print('  CLEAN: No demo leaks found in HTML template')

    # Check template logic
    has_is_release = '{% if is_release %}' in html
    has_is_not_release = '{% if not is_release %}' in html
    has_upgrade = 'id="upgradeBtn"' in html
    has_dlcard = 'id="dlCard"' in html
    has_banner = 'id="updateBanner"' in html

    print(f'\n=== Template logic ===')
    print(f'  is_release condition: {has_is_release}')
    print(f'  not is_release condition: {has_is_not_release}')
    print(f'  upgradeBtn (release): {has_upgrade}')
    print(f'  dlCard (demo): {has_dlcard}')
    print(f'  updateBanner (release): {has_banner}')

    # Check RELEASE_INFO
    ri = json.loads(z.read(prefix+'RELEASE_INFO.json'))
    print(f'\n=== RELEASE_INFO ===')
    print(f'  version: {ri.get("version")}')
    print(f'  name: {ri.get("name")}')

    # Check app.py for RELEASE_MODE handling
    app_py = z.read(prefix+'application/portal/app.py').decode('utf-8')
    is_release_var = '_RELEASE' in app_py
    print(f'\n=== app.py ===')
    print(f'  _RELEASE variable: {is_release_var}')
    if is_release_var:
        m = re.search(r'_RELEASE\s*=.*', app_py)
        if m: print(f'  def: {m.group()}')

    # Check build output
    print(f'\n=== Build stats ===')
    src_count = ri.get('source_file_count', '?')
    print(f'  source files: {src_count}')

    # Check PNG leaks
    pngs = [n for n in names if n.endswith('.png') and 'runtime/' not in n]
    if pngs:
        print(f'  PNGs: {len(pngs)} application PNGs (should be 0)')
        for p in pngs[:5]:
            print(f'    {p}')
    else:
        print(f'  PNGs: 0 (clean)')

    # Check test files
    tests = [n for n in names if '/test/' in n and 'runtime/' not in n]
    print(f'  Test files: {len(tests)} (should be 0)')
    for t in tests[:5]:
        print(f'    {t}')

    # Check bat file
    bat = z.read(prefix+'start_all.bat').decode('utf-8')
    has_chcp = 'chcp' in bat
    has_chinese = not bat.isascii()
    print(f'\n=== start_all.bat ===')
    print(f'  chcp present: {has_chcp} (should be False)')
    print(f'  non-ASCII: {has_chinese} (should be False)')

# Import réel de complete.py + chaque session sNN en sous-processus isolé
# (clés factices, cwd temporaire).
import subprocess, sys, tempfile

SRC = r'C:\Users\forma\Coding\mekicode\src'
SESSIONS = SRC + r'\sessions'
fails = []
mods = ['complete'] + ['s%02d' % n for n in range(1, 21)]
for mod in mods:
    code = (
        "import os\n"
        "os.environ.setdefault('ANTHROPIC_API_KEY', 'sk-test-dummy')\n"
        "os.environ.setdefault('MODEL_ID', 'claude-test')\n"
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "import %s\n"
        "print('%s OK')\n"
    ) % (SRC, SESSIONS, mod, mod)
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, '-c', code], cwd=tmp, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        fails.append(mod)
        tail = (r.stderr or r.stdout).strip().splitlines()
        print(mod, 'FAIL:', tail[-1][:200] if tail else '(aucune sortie)')
    else:
        print(r.stdout.strip())
print('---')
print('imports:', len(mods) - len(fails), '/', len(mods), 'OK (complete + 20 sessions)')
sys.exit(1 if fails else 0)

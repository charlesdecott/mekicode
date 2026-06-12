# Portail qualité du refactoring de shared.py :
# 1. py_compile
# 2. diff AST vs baseline (les 183 noms module-level doivent tous exister)
# 3. import réel avec clés factices dans un cwd temporaire (le module doit
#    s'importer sans erreur : décorateurs, mkdirs, scan skills, thread cron)
import ast, json, os, py_compile, subprocess, sys, tempfile

SRC = r'C:\Users\forma\Coding\mekicode\src\shared.py'
BASELINE = r'C:\Users\forma\Coding\mekicode\.understand-anything\shared-baseline.json'

# 1. compilation
py_compile.compile(SRC, doraise=True)
print('1. py_compile: OK')

# 2. noms module-level
tree = ast.parse(open(SRC, encoding='utf-8').read())
names = set()
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.add(node.target.id)
baseline = json.load(open(BASELINE))
missing = sorted(set(baseline['module_names']) - names)
if missing:
    print('2. NOMS PERDUS (%d):' % len(missing), ', '.join(missing))
    sys.exit(1)
print('2. AST: les %d noms de la baseline existent tous' % len(baseline['module_names']))

# 3. import réel, cwd temporaire, clés factices
test = (
    "import os\n"
    "os.environ.setdefault('ANTHROPIC_API_KEY', 'sk-test-dummy')\n"
    "os.environ.setdefault('MODEL_ID', 'claude-test')\n"
    "import sys; sys.path.insert(0, r'C:\\Users\\forma\\Coding\\mekicode\\src')\n"
    "import shared\n"
    "names = json.load(open(r'%s'))['module_names']\n"
    "missing = [n for n in names if not hasattr(shared, n)]\n"
    "assert not missing, 'attributs manquants: ' + ', '.join(missing)\n"
    "assert len(shared.BUILTIN_TOOLS) == 27, 'BUILTIN_TOOLS != 27: %%d' %% len(shared.BUILTIN_TOOLS)\n"
    "tools = set(t['name'] for t in shared.BUILTIN_TOOLS); handlers = set(shared.BUILTIN_HANDLERS)\n"
    "assert tools - handlers == {'compact'}, 'TOOLS sans handler inattendus: ' + str(tools - handlers)\n"
    "assert handlers <= tools, 'handlers orphelins: ' + str(handlers - tools)\n"
    "import inspect\n"
    "sig = inspect.signature(shared.agent_loop)\n"
    "assert {'tools','handlers','system'} <= set(sig.parameters), 'agent_loop a perdu ses parametres'\n"
    "baseline_sigs = json.load(open(r'%s')).get('signatures', {})\n"
    "bad = []\n"
    "for n, params in baseline_sigs.items():\n"
    "    obj = shared\n"
    "    for part in n.split('.'):\n"
    "        obj = getattr(obj, part, None)\n"
    "        if obj is None: break\n"
    "    if obj is None: bad.append(n + ' (absent)'); continue\n"
    "    try: cur = [p for p in inspect.signature(obj).parameters if p != 'self']\n"
    "    except (ValueError, TypeError): continue\n"
    "    ref = [p for p in params if p != 'self']\n"
    "    if cur != ref: bad.append('%%s: %%s != %%s' %% (n, cur, ref))\n"
    "assert not bad, 'signatures modifiees: ' + '; '.join(bad[:8])\n"
    "print('   import OK |', len(names), 'attributs |', len(shared.BUILTIN_TOOLS), 'outils |', len(shared.SKILL_REGISTRY), 'skills scannees')\n"
) % (BASELINE, BASELINE)
test = "import json\n" + test
with tempfile.TemporaryDirectory() as tmp:
    r = subprocess.run([sys.executable, '-c', test], cwd=tmp, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print('3. IMPORT FAIL:\n', r.stdout[-2000:], r.stderr[-2000:])
        sys.exit(1)
    print('3. import réel:', r.stdout.strip())
print('TOUT EST VERT')

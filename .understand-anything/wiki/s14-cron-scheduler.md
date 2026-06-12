---
title: "s14 · Cron Scheduler"
session: 14
phase: "Tâches & temps"
fichier: "inspiration/learn-claude-code/s14_cron_scheduler/code.py"
lignes: 805
tags: [cron, scheduler, threads, queue, durabilite]
prev: "s13-background-tasks"
next: "s15-agent-teams"
---

# s14 · Cron Scheduler

> **En une phrase** : un thread démon indépendant évalue chaque seconde des expressions cron à 5 champs, pousse les jobs qui « tirent » dans une file thread-safe, et un *queue processor* réveille l'agent quand il est inactif pour livrer ce travail planifié — avec persistance optionnelle sur disque.

## Rôle dans le harness

Le README de la session ouvre sur l'image du réveil-matin : « un réveil n'a pas besoin que vous le regardiez. Vous le réglez sur 7h00, il sonne à 7h00 ». Depuis [[s13-background-tasks]], l'agent sait exécuter des opérations lentes en arrière-plan, mais **chaque opération reste déclenchée manuellement** par l'humain. Or des demandes comme « lance les tests tous les matins à 9h » ou « vérifie le statut CI toutes les 30 minutes » ne devraient pas exiger qu'un humain appuie sur le bouton à chaque fois.

La session introduit un modèle à **quatre couches**, explicité dans la docstring (lignes 18–22) : (1) le *scheduler*, un thread démon qui vérifie l'heure et fait « tirer » les jobs dont l'expression cron correspond ; (2) la *file* `cron_queue` qui découple le scheduler de la boucle agent ; (3) le *queue processor* qui réveille l'agent quand la file est non vide et que l'agent est inactif ; (4) le *consommateur* `agent_loop` qui vide la file et injecte les prompts planifiés dans les messages. Producteur, livreur et consommateur ne se connaissent pas : ils ne partagent que `cron_queue`, `cron_lock` et `agent_lock`.

Dans le vrai Claude Code, le même mécanisme existe avec trois outils (`CronCreate`, `CronDelete`, `CronList`), un stockage dans `.claude/scheduled_tasks.json` protégé par un fichier de verrou, un polling à 1 seconde (`cronScheduler.ts`, `CHECK_INTERVAL_MS = 1000`), une limite de 50 jobs, un *jitter* anti-« thundering herd » (délai jusqu'à 10 % de la période), une expiration automatique des jobs récurrents après 7 jours, et une livraison via `useQueueProcessor.ts` quand aucune requête n'est active. La version pédagogique en garde l'essentiel : polling 1 s, file, livraison automatique à l'agent inactif, durabilité.

Mise en garde importante du README : le scheduler vit **dans le processus de l'agent**. « Durable » signifie seulement que la *définition* du job survit au redémarrage (rechargée par `load_durable_jobs`) — si le processus est arrêté, rien ne tire. Pour du « même app fermée », il faut le crontab système ou un timer systemd.

## Vue d'ensemble du fichier

Le fichier compte 804 lignes physiques (numérotation utilisée ci-dessous) ; la carte du wiki indique 666 lignes hors lignes vides.

| Lignes | Zone | Contenu |
|---|---|---|
| 1–23 | Docstring | Les changements vs s13 et le modèle à quatre couches |
| 25–47 | Imports & init | readline, dotenv, `WORKDIR`, client Anthropic, `MODEL` |
| 49–141 | Task system | `Task` + CRUD + dépendances, repris de [[s12-task-system]] |
| 143–175 | Prompt assembly | `PROMPT_SECTIONS` + cache, repris de [[s10-system-prompt]] |
| 178–215 | Outils de base | `safe_path`, `run_bash`, `run_read`, `run_write` |
| 218–255 | Handlers d'outils tâches | `run_create_task` … `run_complete_task` |
| 258–344 | Background tasks | Dispatch en threads démons, repris de [[s13-background-tasks]] |
| 346–562 | **Cron scheduler (nouveau)** | `CronJob`, matching, validation, durabilité, thread scheduler |
| 565–591 | **Handlers d'outils cron (nouveau)** | `run_schedule_cron`, `run_list_crons`, `run_cancel_cron` |
| 593–662 | `TOOLS` | 11 définitions d'outils (8 de s13 + 3 cron) |
| 665–678 | Contexte | `update_context` |
| 681–737 | `agent_loop` | Modifiée : consomme `cron_queue` en tête de boucle |
| 740–789 | **Tour verrouillé + queue processor (nouveau)** | `run_agent_turn_locked`, `queue_processor_loop` |
| 791–804 | REPL `__main__` | Démarre le thread queue processor, prend `agent_lock` par tour |

## Constantes et configuration

- **Lignes 39–41** : `load_dotenv(override=True)` puis suppression de `ANTHROPIC_AUTH_TOKEN` si une `ANTHROPIC_BASE_URL` est définie (évite un conflit d'authentification avec un proxy).
- **Lignes 43–47** : `WORKDIR = Path.cwd()`, `MEMORY_DIR`/`MEMORY_INDEX` (`.memory/MEMORY.md`), client `Anthropic`, `MODEL = os.environ["MODEL_ID"]`.
- **Lignes 51–52** : `TASKS_DIR = WORKDIR / ".tasks"`, créé immédiatement.
- **Lignes 145–152** : `PROMPT_SECTIONS` — la section `tools` énumère désormais aussi `schedule_cron, list_crons, cancel_cron`.
- **Ligne 165** : `_last_context_key, _last_prompt` — cache du prompt système.
- **Lignes 260–263** : état des background tasks (`_bg_counter`, `background_tasks`, `background_results`, `background_lock`), repris de [[s13-background-tasks]].
- **Ligne 348** : `DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"` — fichier de persistance des jobs durables (même nom que le vrai CC, sans le préfixe `.claude/`).
- **Lignes 360–364** : l'état du scheduler, tout nouveau :
  ```python
  scheduled_jobs: dict[str, CronJob] = {}
  cron_queue: list[CronJob] = []
  cron_lock = threading.Lock()
  agent_lock = threading.Lock()
  _last_fired: dict[str, str] = {}  # job_id → "YYYY-MM-DD HH:MM"
  ```
  `cron_lock` protège `scheduled_jobs` et `cron_queue` ; `agent_lock` sérialise les tours d'agent entre le REPL et le queue processor ; `_last_fired` mémorise la dernière minute de tir de chaque job (anti double-tir).
- **Lignes 560–562** : bloc de démarrage exécuté à l'import — `load_durable_jobs()` puis `threading.Thread(target=cron_scheduler_loop, daemon=True).start()`. Le scheduler tourne donc avant même la première saisie utilisateur.
- **Lignes 595–662** : `TOOLS` — 11 outils. Les trois nouveaux : `schedule_cron` (lignes 640–652, paramètres `cron`, `prompt`, `recurring`, `durable`), `list_crons` (653–656), `cancel_cron` (657–661).
- **Lignes 740–741** : `session_history` et `session_context` deviennent des **globales de module** (et non plus des locales du `__main__`) : le queue processor doit pouvoir lancer un tour d'agent sans passer par le REPL.

## Les fonctions, une à une

### `Task` (dataclass) — lignes 55–62
Reprise de [[s12-task-system]] sans modification : `id`, `subject`, `description`, `status` (`pending | in_progress | completed`), `owner`, `blockedBy`.

### `_task_path(task_id)` — lignes 65–66
Reprise de [[s12-task-system]] sans modification : chemin `.tasks/{id}.json`.

### `create_task(subject, description, blockedBy)` — lignes 69–78
Reprise de [[s12-task-system]] sans modification : id horodaté + 4 chiffres aléatoires, statut `pending`, sauvegarde immédiate.

### `save_task(task)` / `load_task(task_id)` — lignes 81–82 / 85–86
Reprises de [[s12-task-system]] sans modification : sérialisation JSON via `asdict`.

### `list_tasks()` — lignes 89–91
Reprise de [[s12-task-system]] sans modification : charge tous les `task_*.json` triés.

### `get_task(task_id)` — lignes 94–97
Reprise de [[s12-task-system]] sans modification : détails complets en JSON.

### `can_start(task_id)` — lignes 100–109
Reprise de [[s12-task-system]] sans modification : toutes les dépendances `blockedBy` doivent être `completed` ; une dépendance manquante bloque.

### `claim_task(task_id, owner)` — lignes 112–124
Reprise de [[s12-task-system]] sans modification : refuse si non-`pending` ou bloquée, sinon passe `in_progress` et fixe `owner`.

### `complete_task(task_id)` — lignes 127–140
Reprise de [[s12-task-system]] sans modification : passe `completed` et liste les tâches débloquées en aval.

### `assemble_system_prompt(context)` — lignes 155–162
Reprise de [[s10-system-prompt]] sans modification structurelle : concatène identité, outils, workspace, et les mémoires si présentes.

### `get_system_prompt(context)` — lignes 168–175
Reprise de [[s10-system-prompt]] sans modification : cache le prompt assemblé tant que la clé JSON du contexte ne change pas.

### `safe_path(p)` — lignes 180–184
Reprise des sessions fondamentales (voir [[s03-permission]]) : résout le chemin et rejette toute évasion hors de `WORKDIR`.

### `run_bash(command, run_in_background)` — lignes 187–195
Reprise de [[s13-background-tasks]] : `subprocess.run` avec timeout 120 s, sortie tronquée à 50 000 caractères. Le paramètre `run_in_background` est accepté mais **ignoré ici** — c'est le dispatch de `agent_loop` qui décide du passage en arrière-plan (commentaire ligne 188).

### `run_read(path, limit)` — lignes 198–205
Reprise de [[s02-tool-use]] sans modification : lecture avec troncature optionnelle.

### `run_write(path, content)` — lignes 208–215
Reprise de [[s02-tool-use]] sans modification : écriture avec création des dossiers parents.

### `run_create_task` … `run_complete_task` — lignes 220–255
Handlers d'outils repris de [[s12-task-system]] sans modification : `run_create_task` (220–225), `run_list_tasks` (228–240, icônes ○/●/✓), `run_get_task` (243–247), `run_claim_task` (250–251), `run_complete_task` (254–255).

### `is_slow_operation(tool_name, tool_input)` — lignes 266–274
Reprise de [[s13-background-tasks]] sans modification : heuristique par mots-clés (`install`, `build`, `test`…) pour détecter les commandes bash probablement > 30 s.

### `should_run_background(tool_name, tool_input)` — lignes 277–281
Reprise de [[s13-background-tasks]] sans modification : la demande explicite du modèle (`run_in_background`) prime, sinon heuristique.

### `execute_tool(block)` — lignes 284–296
Reprise de [[s13-background-tasks]], **modifiée** : la table de dispatch gagne trois entrées `schedule_cron`, `list_crons`, `cancel_cron` (lignes 291–292). Détail : la table référence `run_schedule_cron` & co définies plus bas dans le fichier (lignes 567+) — légal en Python car la résolution du nom n'a lieu qu'à l'appel.

### `start_background_task(block)` — lignes 299–320
Reprise de [[s13-background-tasks]] sans modification : exécute l'outil dans un thread démon, enregistre `bg_id` dans `background_tasks` sous `background_lock`.

### `collect_background_results()` — lignes 323–343
Reprise de [[s13-background-tasks]] sans modification : transforme les résultats terminés en blocs `<task_notification>` (résumé tronqué à 200 caractères).

### `CronJob` (dataclass) — lignes 351–358 — NOUVEAU

La structure de données centrale de la session :

```python
@dataclass
class CronJob:
    id: str
    cron: str        # "0 9 * * *"
    prompt: str      # message to inject when fired
    recurring: bool  # True = recurring, False = one-shot
    durable: bool    # True = persist to disk
```

Deux axes orthogonaux : `recurring` (récurrent vs one-shot, retiré après le premier tir) et `durable` (persisté dans `.scheduled_tasks.json` vs mémoire de session uniquement). Le `prompt` n'est pas une commande : c'est un **message utilisateur** qui sera injecté dans la conversation, et c'est le LLM qui décidera quoi en faire.

### `_cron_field_matches(field, value)` — lignes 367–380 — NOUVEAU

Le cœur du parsing d'expressions cron : fait correspondre **un champ** à une valeur entière, en gérant les quatre syntaxes `*`, `*/N`, `N,M,...`, `N-M` et la valeur simple `N`.

```python
def _cron_field_matches(field: str, value: int) -> bool:
    """Match a single cron field against a value."""
    if field == "*":
        return True
    if field.startswith("*/"):
        step = int(field[2:])
        return step > 0 and value % step == 0
    if "," in field:
        return any(_cron_field_matches(f.strip(), value)
                   for f in field.split(","))
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return value == int(field)
```

Ligne par ligne :
- **369–370** : le joker `*` matche tout — court-circuit immédiat.
- **371–373** : le pas `*/N` matche si `value % N == 0`. Attention : c'est une approximation. Le vrai cron interprète `*/5` comme « depuis le début de la plage » — pour le jour du mois (plage 1–31), cron matche 1, 6, 11…, alors qu'ici on matche 5, 10, 15… Identique pour les minutes/heures (plage commençant à 0), divergent pour DOM et mois.
- **374–376** : la liste `N,M,...` est traitée par **récursion** sur chaque élément — donc `1-5,10` fonctionnerait aussi, chaque partie repassant par la même fonction.
- **377–379** : la plage `N-M` est un simple test d'encadrement. `split("-", 1)` ne coupe qu'au premier tiret.
- **380** : cas de base, égalité stricte.

L'ordre des tests compte : la virgule est testée **avant** le tiret, ce qui permet à `1-5,10` d'être découpé d'abord en éléments de liste.

### `cron_matches(cron_expr, dt)` — lignes 383–410 — NOUVEAU

Combine les 5 champs avec la sémantique cron standard, y compris la règle la moins connue : **DOM et DOW sont en OU quand les deux sont contraints**.

```python
    minute, hour, dom, month, dow = fields
    dow_val = (dt.weekday() + 1) % 7  # Python Monday=0 → cron Sunday=0

    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)

    # Minute, hour, month must all match
    if not (m and h and month_ok):
        return False
    # DOM and DOW: if both constrained, either matching is enough (OR)
    dom_unconstrained = dom == "*"
    dow_unconstrained = dow == "*"
    if dom_unconstrained and dow_unconstrained:
        return True
    if dom_unconstrained:
        return dow_ok
    if dow_unconstrained:
        return dom_ok
    return dom_ok or dow_ok
```

- **387–388** : exactement 5 champs séparés par des espaces, sinon `False` (pas d'exception — un cron malformé ne tire jamais, il ne plante pas).
- **390** : conversion des jours de semaine — Python compte lundi=0, cron compte dimanche=0. `(weekday() + 1) % 7` transforme lundi=0 en 1, …, dimanche=6 en 0.
- **399–400** : minute, heure et mois doivent **tous** matcher (logique ET).
- **402–410** : la subtilité cron historique. Si DOM et DOW sont tous deux `*` → tir. Si un seul est contraint → c'est lui qui décide. Si **les deux** sont contraints (ex. `0 9 13 * 5` = « le 13 du mois OU le vendredi, à 9h »), un seul des deux suffit (`or`). C'est le comportement du cron Unix depuis 50 ans, souvent contre-intuitif.

### `_validate_cron_field(field, lo, hi)` — lignes 413–445 — NOUVEAU

Pendant de `_cron_field_matches`, mais pour la **validation à l'enregistrement** : vérifie qu'un champ est syntaxiquement correct et dans les bornes `[lo, hi]`. Retourne un message d'erreur ou `None`.

```python
    if "-" in field:
        parts = field.split("-", 1)
        if not parts[0].isdigit() or not parts[1].isdigit():
            return f"Invalid range: {field}"
        a, b = int(parts[0]), int(parts[1])
        if a < lo or a > hi or b < lo or b > hi:
            return f"Range {field} out of bounds [{lo}-{hi}]"
        if a > b:
            return f"Range start > end: {field}"
        return None
```

Cas couverts : `*` toujours valide (414–415) ; `*/N` exige `N` numérique et > 0 (416–424) — mais **pas de borne supérieure** : `*/99` passe la validation pour un champ minute ; les listes valident récursivement chaque élément (425–429) ; les plages exigent deux entiers, dans les bornes, et `a <= b` (430–439) ; la valeur simple doit être un entier dans `[lo, hi]` (440–445). Séparer matching et validation est un choix de design : la validation tourne une fois à l'enregistrement (et au chargement disque), le matching tourne chaque seconde.

### `validate_cron(cron_expr)` — lignes 448–459 — NOUVEAU

Valide l'expression complète : 5 champs, puis chaque champ contre ses bornes propres :

```python
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
```

L'erreur retournée est préfixée du nom du champ (`"minute: Invalid step: */x"`), ce qui donne au LLM un retour exploitable pour corriger son appel d'outil. (Détail : la variable `i` de l'`enumerate` ligne 455 n'est jamais utilisée.)

### `save_durable_jobs()` — lignes 462–465 — NOUVEAU
Filtre `scheduled_jobs` sur `durable=True` et réécrit **tout** le fichier `.scheduled_tasks.json` (pas d'append). Les jobs de session n'y figurent jamais.

### `load_durable_jobs()` — lignes 468–485 — NOUVEAU

Au démarrage, recharge les jobs durables :

```python
        jobs = json.loads(DURABLE_PATH.read_text())
        for j in jobs:
            job = CronJob(**j)
            err = validate_cron(job.cron)
            if err:
                print(f"  \033[31m[cron] skipping invalid job {job.id}: {err}\033[0m")
                continue
            scheduled_jobs[job.id] = job
```

Deux protections : chaque job est **re-validé** (un fichier édité à la main ou corrompu ne charge pas un cron invalide qui spammerait des erreurs chaque seconde), et tout le bloc est dans un `try/except Exception: pass` (479–485) — un JSON illisible ne casse pas le démarrage. Le `except … pass` silencieux est toutefois radical : un fichier corrompu disparaît sans aucun message.

### `schedule_job(cron, prompt, recurring, durable)` — lignes 488–504 — NOUVEAU

Enregistre un job, valeur de retour à double type (`CronJob` ou `str` d'erreur) :

```python
    err = validate_cron(cron)
    if err:
        return err
    job = CronJob(
        id=f"cron_{random.randint(0, 999999):06d}",
        cron=cron, prompt=prompt,
        recurring=recurring, durable=durable,
    )
    with cron_lock:
        scheduled_jobs[job.id] = job
    if durable:
        save_durable_jobs()
```

- **491–493** : validation **avant** création — un cron invalide n'entre jamais dans `scheduled_jobs`, donc le thread scheduler n'a jamais à s'en protéger (défense en profondeur : il a quand même son `try/except`).
- **495** : id = 6 chiffres aléatoires ; pas de garantie d'unicité (collision possible, qui écraserait silencieusement un job existant).
- **499–502** : l'insertion est sous `cron_lock`, mais `save_durable_jobs()` est appelée **hors verrou** — elle itère `scheduled_jobs` pendant qu'un autre thread pourrait le modifier (course bénigne en pratique grâce au GIL et à la copie implicite de `.values()` dans la compréhension).

### `cancel_job(job_id)` — lignes 507–516 — NOUVEAU
`scheduled_jobs.pop(job_id, None)` sous verrou ; si le job était durable, réécrit le fichier (le job en est donc retiré). Retourne un message d'erreur si l'id est inconnu.

### `cron_scheduler_loop()` — lignes 519–542 — NOUVEAU

La couche 1 du modèle : le thread démon qui produit le travail.

```python
    while True:
        time.sleep(1)
        now = datetime.now()
        # Date-aware marker prevents daily jobs from skipping on day 2+
        minute_marker = now.strftime("%Y-%m-%d %H:%M")
        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now):
                        if _last_fired.get(job.id) != minute_marker:
                            cron_queue.append(job)
                            _last_fired[job.id] = minute_marker
                        if not job.recurring:
                            scheduled_jobs.pop(job.id, None)
                            if job.durable:
                                save_durable_jobs()
                except Exception as e:
                    print(f"  \033[31m[cron error] {job.id}: {e}\033[0m")
```

- **524** : polling à 1 s — même rythme que le vrai CC (`CHECK_INTERVAL_MS = 1000`). Comme la granularité cron est la minute, un job matchera ~60 fois par minute : d'où le garde-fou suivant.
- **527** : `minute_marker` inclut la **date**, pas seulement `HH:MM`. Avec un simple `"09:00"`, un job quotidien ayant tiré lundi à 9h00 ne tirerait plus jamais (le marqueur resterait égal) ; avec `"2026-06-11 09:00"`, mardi 9h00 produit un marqueur différent → le job retire bien. C'est le commentaire « prevents daily jobs from skipping on day 2+ ».
- **529** : `list(scheduled_jobs.values())` — copie défensive, car la boucle peut faire `pop` sur le dict qu'elle parcourt (job one-shot, ligne 538).
- **530–542** : `try/except` **par job** : un job pathologique loggue une erreur mais ne tue pas le thread — sinon tout le scheduling de la session mourrait en silence.
- **532–534** : double condition de tir — l'expression matche **et** ce job n'a pas déjà tiré cette minute-ci. Le job est alors poussé dans `cron_queue` (toujours sous `cron_lock`).
- **537–540** : un job one-shot est retiré aussitôt après son tir ; s'il était durable, le fichier est réécrit (sous verrou, cette fois — incohérence de style avec `schedule_job`, sans conséquence ici).

### `consume_cron_queue()` — lignes 545–550 — NOUVEAU
La couche 4 côté lecture : copie la file sous `cron_lock`, la vide, retourne la copie. Le « take-all-and-clear » atomique évite qu'un job poussé pendant la consommation soit perdu ou doublé.

### `has_cron_queue()` — lignes 553–556 — NOUVEAU
Prédicat non destructif (`bool(cron_queue)` sous verrou) utilisé par le queue processor pour décider s'il y a du travail, **sans** consommer.

### `run_schedule_cron(cron, prompt, recurring, durable)` — lignes 567–572 — NOUVEAU
Handler de l'outil `schedule_cron` : appelle `schedule_job` et discrimine le double type de retour — `isinstance(result, str)` signifie erreur de validation, renvoyée au modèle préfixée `Error:`.

### `run_list_crons()` — lignes 575–586 — NOUVEAU
Liste les jobs avec leurs deux étiquettes : `recurring`/`one-shot` et `durable`/`session`. La copie `list(scheduled_jobs.values())` est prise sous `cron_lock` puis formatée hors verrou.

### `run_cancel_cron(job_id)` — lignes 589–590 — NOUVEAU
Simple délégation à `cancel_job`.

### `update_context(context, messages)` — lignes 667–678
Reprise des sessions précédentes (voir [[s09-memory]] / [[s10-system-prompt]]) : reconstruit le contexte depuis l'état réel (outils actifs, workspace, contenu de `MEMORY.md` s'il existe).

### `agent_loop(messages, context)` — lignes 686–737

Reprise de [[s13-background-tasks]], **modifiée** sur deux points. D'abord, la consommation des jobs cron en tête de chaque itération (lignes 688–694) :

```python
    while True:
        # Layer 4: consume fired cron jobs → inject as messages
        fired = consume_cron_queue()
        for job in fired:
            messages.append({"role": "user",
                             "content": f"[Scheduled] {job.prompt}"})
```

Le prompt du job devient un message utilisateur préfixé `[Scheduled]` — l'agent ne distingue le travail planifié du travail humain que par ce préfixe. Comme la consommation est en tête de `while True`, un job qui tire **pendant** un tour multi-étapes est injecté à l'itération suivante, sans attendre la fin du tour. Ensuite, la signature change : la fonction **retourne `context`** (lignes 704 et 708) au lieu de rien, car son appelant `run_agent_turn_locked` doit maintenir la globale `session_context`. Le reste (dispatch background, fusion des `tool_result` et des `<task_notification>` en un seul message user) est identique à [[s13-background-tasks]].

### `print_latest_assistant_text(messages)` — lignes 744–759 — NOUVEAU
Affiche les blocs texte du dernier message assistant. Gère deux représentations : objets SDK (`getattr(block, "type")`) et dicts bruts (cas du message d'erreur synthétique injecté lignes 701–703). Factorisé hors du `__main__` car deux chemins l'utilisent désormais (REPL et queue processor).

### `run_agent_turn_locked(user_query)` — lignes 762–770 — NOUVEAU

Le point d'entrée unique d'un tour d'agent, **sous contrat de verrou** :

```python
def run_agent_turn_locked(user_query: str | None = None):
    """Run one agent turn. Caller must hold agent_lock."""
    global session_context
    if user_query is not None:
        session_history.append({"role": "user", "content": user_query})
    session_context = agent_loop(session_history, session_context)
```

`user_query` est optionnel : le REPL passe la saisie humaine, le queue processor passe `None` (le « prompt » du tour est alors le message `[Scheduled]` injecté par `agent_loop`). Le contrat « caller must hold agent_lock » n'est pas vérifié par le code — c'est une convention documentée, pas une assertion.

### `queue_processor_loop()` — lignes 773–788 — NOUVEAU

La couche 3 : livrer le travail quand l'agent est inactif.

```python
    while True:
        time.sleep(0.2)
        if not has_cron_queue():
            continue
        if not agent_lock.acquire(blocking=False):
            continue
        try:
            if not has_cron_queue():
                continue
            print("\n  \033[35m[queue processor] delivering scheduled work\033[0m")
            run_agent_turn_locked()
        finally:
            agent_lock.release()
```

- **777–779** : polling rapide (200 ms) mais quasi gratuit tant que la file est vide.
- **780–781** : `acquire(blocking=False)` — si l'agent est occupé (l'humain a la main dans le REPL, ligne 803), on **n'attend pas** : on réessaiera dans 200 ms. C'est ainsi que « l'agent est inactif » est détecté : le verrou est libre.
- **783–784** : re-vérification de la file **après** acquisition du verrou — classique fenêtre TOCTOU : entre le premier test et l'acquisition, le tour REPL en cours a pu consommer la file. Le `continue` dans le `try` passe quand même par le `finally`, donc le verrou est bien relâché.
- Le tour lancé sans `user_query` laisse `agent_loop` injecter lui-même les messages `[Scheduled]`.

### Bloc `__main__` — lignes 791–804

Démarre le thread `queue_processor_loop` (démon, ligne 794), puis la boucle REPL habituelle — à un détail près : chaque tour humain est encadré de `with agent_lock:` (lignes 803–804), ce qui exclut mutuellement saisie humaine et livraison automatique. `q`, `exit`, chaîne vide ou Ctrl-C/Ctrl-D quittent.

## Ce qui change par rapport à [[s13-background-tasks]]

- **Nouvelle dataclass `CronJob`** (351–358) : `id`, `cron`, `prompt`, `recurring`, `durable`.
- **Nouveau bloc cron complet** (346–562) : matching (`_cron_field_matches`, `cron_matches`), validation (`_validate_cron_field`, `validate_cron`), persistance (`save_durable_jobs`, `load_durable_jobs`, `DURABLE_PATH`), cycle de vie (`schedule_job`, `cancel_job`), thread `cron_scheduler_loop`, file (`consume_cron_queue`, `has_cron_queue`).
- **Deux nouveaux threads démons** : le scheduler (démarré à l'import, ligne 561) et le queue processor (démarré dans `__main__`, ligne 794) — en plus des threads background de s13.
- **3 nouveaux outils** : `schedule_cron`, `list_crons`, `cancel_cron` (8 → 11) ; `PROMPT_SECTIONS["tools"]` et `execute_tool` mis à jour.
- **`agent_loop` modifiée** : consomme `cron_queue` en tête de boucle et retourne `context`.
- **État de session globalisé** : `session_history`/`session_context` (740–741) + nouvelles fonctions `print_latest_assistant_text`, `run_agent_turn_locked`, et le verrou `agent_lock` qui arbitre REPL vs queue processor.
- **Toujours absent** (assumé par la docstring et le README) : la récupération d'erreurs complète de [[s11-error-recovery]], la mémoire de [[s09-memory]] et les skills de [[s07-skill-loading]] — le code pédagogique reste focalisé sur le mécanisme du jour.

## Pièges et détails d'implémentation

- **Le `minute_marker` contient la date** (ligne 527). Avec `HH:MM` seul, un job quotidien tirerait le jour 1 puis plus jamais. C'est le genre de bug qui ne se voit qu'au deuxième jour de production.
- **`*/N` n'est pas le `*/N` du vrai cron** : `value % N == 0` équivaut au comportement cron uniquement pour les plages commençant à 0 (minutes, heures, DOW). Pour le jour du mois, `*/5` matche ici 5, 10, 15… alors que cron matche 1, 6, 11… De plus, la validation n'impose aucune borne au pas (`*/99` accepté en champ minute : le job tire alors une seule fois par heure, à la minute 0).
- **DOM/DOW en OU** : `0 9 13 * 5` tire le 13 du mois **ou** chaque vendredi — pas « le vendredi 13 ». Sémantique Unix historique, reproduite fidèlement (lignes 401–410).
- **« Durable » ne veut pas dire « tourne hors process »** : seul le JSON survit ; si le processus est éteint à l'heure dite, le job ne tire pas (et rien ne « rattrape » les tirs manqués au redémarrage).
- **Double vérification dans `queue_processor_loop`** : tester la file, prendre le verrou en non-bloquant, **retester** la file. Sans le deuxième test, le processor pourrait lancer un tour d'agent à vide (l'agent venant de consommer la file en fin de tour humain).
- **Les ids ne sont pas garantis uniques** : `cron_{random:06d}` (et `task_{ts}_{random:04d}`) peuvent théoriquement collisionner ; un nouveau job écraserait l'ancien dans le dict.
- **Verrouillage incohérent autour de `save_durable_jobs`** : appelée hors `cron_lock` dans `schedule_job`/`cancel_job` mais sous verrou dans le scheduler. Sans conséquence ici (GIL + écriture de fichier idempotente), mais à ne pas reproduire tel quel en production.

## Liens

- Session précédente : [[s13-background-tasks]]
- Session suivante : [[s15-agent-teams]]
- Sessions liées : [[s12-task-system]] (système de tâches embarqué), [[s10-system-prompt]] (assemblage du prompt), [[s11-error-recovery]] (la gestion d'erreurs omise ici), [[s17-autonomous-agents]] (autre usage des boucles d'attente), [[s20-comprehensive]] (synthèse finale)

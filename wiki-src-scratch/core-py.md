---
title: "core.py · Le socle"
phase: "Fondations"
fichier: "src_scratch/core.py"
lignes: 134
tags: [config, permissions, event-bus, hooks, client, ansi]
---

# core.py · Le socle

> **En une phrase** : tout ce que les dix autres modules partagent — client Anthropic, chemins (`ROOT`, `STATE_DIR`), `config.yaml` mis en cache, gouvernance trois tiers (s15), event bus à veto (s16) et couleurs ANSI — chargé une fois, à l'import.

## Rôle dans le harness

Dans le repo source, le `core.py` de 626 lignes mélangeait outils, dispatch et utilitaires ; chaque session en réimportait des morceaux et redéfinissait le reste. Ici le socle est réduit à ce qui est **réellement transversal** : la configuration (env + `config.yaml`), le client API, la gouvernance des permissions et l'event bus. Les outils, eux, vivent dans [[tools-py]] ; la boucle dans [[loop-py]]. Sessions source couvertes : le core lui-même, s15 (permissions YAML) et s16 (hooks).

Le module a des **effets de bord à l'import**, assumés : reconfiguration UTF-8 de la console, `load_dotenv(override=True)`, création de `STATE_DIR`, instanciation du `client`. C'est le prix d'un socle « import et c'est prêt » — tous les modules de `src_scratch/` commencent par `from core import …` et héritent de cet environnement initialisé.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–5 | Docstring | Rôle du module + contrat des hooks (`hook(event, payload)`, `False` = veto) |
| 11–19 | Encodage console | FIX : stdout/stderr/stdin reconfigurés en UTF-8 (Windows cp1252) |
| 21–34 | Confort terminal | `readline` et `colorama` optionnels, comme la source |
| 36–43 | Env & client | `load_dotenv(override=True)`, purge du token si gateway tiers |
| 45–56 | Constantes | `client`, `MODEL`, `DEFAULT_SYSTEM`, `ROOT`, `STATE_DIR`, `CONFIG_PATH` |
| 58–63 | Couleurs | `_ANSI` + `paint()` |
| 66–84 | Config | `_CONFIG` (cache module), `load_config()`, `load_rules()` |
| 87–107 | Gouvernance | `check_permission()` — trois tiers deny/allow/ask (s15) |
| 110–134 | Event bus | `HOOKS`, `on()`, `emit()` (s16) |

## Constantes et configuration

- **`client` (ligne 45)** : `Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))` — un seul client pour tout le harness. Si `ANTHROPIC_BASE_URL` est défini, les lignes 41–43 retirent `ANTHROPIC_AUTH_TOKEN` de l'environnement : on n'envoie pas un token résiduel vers un gateway tiers.
- **`MODEL` (ligne 46)** : env `MODEL_ID`, défaut `"claude-sonnet-4-6"`.
- **`DEFAULT_SYSTEM` (lignes 47–49)** : « You are a coding agent at `<cwd>`… » — `os.getcwd()` est capturé **à l'import** ; lancer le harness depuis un autre répertoire change le prompt.
- **`ROOT` (ligne 51)** : `Path(__file__).parent` — l'ancre de tous les chemins du projet (jamais `parent.parent`, voir Bugs ci-dessous).
- **`STATE_DIR` (lignes 52–53)** : `ROOT/".state"` (surchargeable via env `MEKI_STATE_DIR`), `mkdir` immédiat. Tout l'état runtime ([[tasks-py]], [[mailbox-py]], [[sessions-py]], mémoire de [[context-py]]) vit dessous.
- **`CONFIG_PATH` (ligne 56)** : `ROOT / "config.yaml"`.
- **`_ANSI` (ligne 58)** : six couleurs (red/green/yellow/cyan/magenta/dim) pour `paint()`.
- **`HOOKS` (ligne 113)** : dict `event → liste de hooks`, le registre de l'event bus. Événements émis par le harness : `session_start`, `user_message`, `pre_tool`, `post_tool`, `assistant_message`, `session_end`.

### config.yaml — le fichier de configuration (70 lignes)

C'est core qui le charge, donc c'est ici qu'on le documente. Deux sections :

**`permissions` (lignes 8–56 du yaml)** — la gouvernance trois tiers de s15. Chaque règle est un couple `pattern` (regex Python, testée insensible à la casse) + `reason` (affichée à l'utilisateur). Ordre d'évaluation : `always_deny` → `always_allow` → `ask_user` → allow par défaut.

| Tier | Lignes yaml | Exemples |
|---|---|---|
| `always_deny` | 9–21 | `rm -rf /`, `sudo`, `shutdown\|reboot\|halt`, fork bomb, `curl…\| sh` |
| `always_allow` | 23–40 | `^ls( \|$)`, `^cat `, `^pwd$`, `^git (status\|log\|diff\|show\|branch\|tag)` |
| `ask_user` | 42–56 | `^rm `, `^pip install`, `^git (commit\|push\|merge\|rebase\|reset)`, `\.env` |

**`mcp.servers` (lignes 60–70 du yaml)** — la liste des serveurs MCP stdio consommée par [[mcp-runtime-py]] (`name`, `transport`, `command`, `args`). Vide par défaut, avec deux exemples commentés (filesystem via `npx`, git via `uvx`).

## Les fonctions, une à une

### `paint(text, color)` — lignes 61–63

```python
def paint(text: str, color: str) -> str:
    """Colore `text` en ANSI (red/green/yellow/cyan/magenta/dim)."""
    return f"\033[{_ANSI.get(color, '0')}m{text}\033[0m"
```

L'unique fonction d'affichage du harness — la source dupliquait les séquences `\033[...]` en dur dans chaque session. Couleur inconnue → code `'0'` (texte normal), jamais d'erreur. Le `\033[0m` final garantit le reset.

### `load_config()` — lignes 69–78

Charge `config.yaml` complet et le met en cache module (`_CONFIG`, ligne 66) : le fichier n'est lu **qu'une seule fois** par processus.

```python
    if _CONFIG is None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _CONFIG = yaml.safe_load(f) or {}
        except FileNotFoundError:
            _CONFIG = {}
```

- **Ligne 75** : `or {}` — un yaml vide donne `None` chez `yaml.safe_load` ; on normalise en dict.
- **Lignes 76–77** : fichier absent → dict vide, pas de crash. Le harness tourne sans config (mais alors sans règles — tout est « allowed by default »).

### `load_rules()` — lignes 81–84

```python
def load_rules() -> dict:
    """Section `permissions` du config.yaml — trois tiers, listes vides par défaut."""
    perms = load_config().get("permissions") or {}
    return {tier: perms.get(tier) or [] for tier in ("always_deny", "always_allow", "ask_user")}
```

Normalisation défensive : quel que soit l'état du yaml (section absente, tier absent, tier explicitement `null`), le retour a toujours les trois clés avec des listes — `check_permission` n'a aucun cas particulier à gérer.

### `check_permission(tool_name, input_str, rules=None)` — lignes 87–107

La gate de s15 : trois boucles dans l'ordre des tiers, première règle qui matche gagne.

```python
    for rule in rules.get("always_deny", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "blocked by policy")
            print(paint(f"[DENIED] {reason}", "red"))
            return False, f"Denied: {reason}"
```

- **`re.search` + `re.IGNORECASE`** : la regex peut matcher n'importe où dans `input_str` (sauf ancre `^`/`$` explicite dans le motif), sans tenir compte de la casse — `SUDO` est bloqué comme `sudo`.
- **`ask_user` (lignes 98–106)** : affiche outil + arguments tronqués à 100 caractères + raison, puis `input("  Autoriser ? [y/N] ")`. `EOFError`/`KeyboardInterrupt` ⇒ réponse `"n"` : **en cas de doute, on refuse**. Seuls `y`/`yes` autorisent.
- **Ligne 107** : aucun tier ne matche → `(True, "allowed by default (no rule matched)")`. Politique permissive par défaut — la sécurité réelle vient des règles `always_deny` du yaml et de la `_ALWAYS_BLOCK` de [[tools-py]].
- Le paramètre `rules` permet d'injecter un jeu de règles de test ; `None` (et non falsy) déclenche `load_rules()` — passer `{}` désactive donc réellement toutes les règles.

### `on(event, hook)` — lignes 116–118

```python
def on(event: str, hook) -> None:
    """Abonne `hook(event, payload)` à `event`."""
    HOOKS.setdefault(event, []).append(hook)
```

Abonnement minimal : pas de désabonnement, pas de priorité — les hooks d'un événement sont appelés dans l'ordre d'inscription.

### `emit(event, payload)` — lignes 121–134

```python
    ok = True
    for hook in HOOKS.get(event, []):
        try:
            if hook(event, payload) is False:
                ok = False
        except Exception as e:
            print(paint(f"[hooks] erreur dans un hook '{event}': {e}", "red"))
    return ok
```

- **`is False` (ligne 130)** : seul un `False` explicite vaut veto — un hook qui renvoie `None` (cas du hook « observateur » qui ne return rien) n'a aucun effet sur le verdict.
- **Pas de court-circuit** : tous les hooks tournent même si l'un a déjà mis son veto — un hook de log placé après un hook de sécurité voit quand même passer l'événement.
- **Une exception ne vaut PAS veto** : elle est loggée (FIX, voir ci-dessous) mais `ok` reste inchangé. Un hook de sécurité qui crashe laisse donc passer l'action — il est juste désormais **visible** qu'il a crashé.
- C'est [[loop-py]] qui exploite le veto : `emit("pre_tool", …) is False` ⇒ tool_result « Blocked by hook » sans exécution.

## Bugs de la source corrigés ici

- **`CONFIG_PATH` ancré sur `ROOT` (lignes 54–56)** — dans le core de la source (utilisé par s15), `_PERM_CONFIG` était construit avec `Path(__file__).parent.parent`, soit **hors du repo** : le yaml n'était jamais trouvé, `load_rules()` renvoyait des listes vides et toute la gouvernance tournait à blanc, silencieusement. Correction : `CONFIG_PATH = ROOT / "config.yaml"` (et la règle de la spec : jamais `parent.parent`).
- **`emit()` ne s'avale plus la langue (lignes 124–133)** — en s16, le `except Exception: pass` autour de l'appel des hooks neutralisait sans aucune trace un hook de sécurité buggé. Correction : l'exception est affichée en rouge avec le nom de l'événement. (Le choix de ne pas transformer l'exception en veto est conservé — voir Pièges.)
- **Console Windows UTF-8 (lignes 11–19)** — durcissement propre à mekicode (marqué `# FIX(mekicode):` mais sans équivalent dans la source) : en cp1252, les caractères `→` ou `≈` des affichages (stats de cache de [[loop-py]] notamment) faisaient crasher `print`, et un pipe UTF-8 vers stdin était décodé de travers. Les trois flux sont reconfigurés en `utf-8/replace` **avant** le wrap colorama.
- **Regex `^ls( |$|$)` du yaml (ligne 25 du yaml)** — le `permissions.yaml` de la source dupliquait l'alternative `$`. Sans conséquence fonctionnelle, mais corrigé en `^ls( |$)` dans notre `config.yaml`.

## Qui l'utilise

Tout `src_scratch/` — c'est le socle. Par module :

- [[tools-py]] — `paint`
- [[loop-py]] — `client`, `MODEL`, `DEFAULT_SYSTEM`, `check_permission`, `emit`, `paint`
- [[context-py]] — `MODEL`, `ROOT`, `STATE_DIR`, `client`, `paint`
- [[tasks-py]] — `STATE_DIR`, `paint`
- [[mailbox-py]] — `STATE_DIR`, `paint`
- [[agents-py]] — `paint`
- [[worktree-py]] — `paint`
- [[sessions-py]] — `STATE_DIR`, `paint`
- [[mcp-runtime-py]] — `load_config`, `paint`
- [[main-py]] — `DEFAULT_SYSTEM`, `emit`, `paint`

## Pièges et détails d'implémentation

- **Importer core a des effets de bord** : `mkdir` de `STATE_DIR`, reconfiguration des flux, `load_dotenv(override=True)` — le `override=True` écrase des variables d'environnement déjà posées par votre shell avec le contenu du `.env`.
- **`_CONFIG` est un cache sans invalidation** : modifier `config.yaml` en cours de session n'a aucun effet ; il faut redémarrer le processus (ou remettre `core._CONFIG = None` à la main).
- **`check_permission` ne voit que ce qu'on lui passe** : [[loop-py]] lui transmet la **première valeur** de l'input (sémantique s15) — la commande pour `bash`, le chemin pour `read`/`write` — et les motifs ancrés `^ls`, `^rm `… du yaml s'appliquent donc pleinement. Tout autre appelant doit respecter ce contrat : passer la repr du dict complet neutraliserait les ancres (voir l'historique dans la page [[loop-py]]).
- **Un hook qui crashe n'est pas un veto** : `emit` logge l'exception mais laisse passer l'action. Pour un hook de sécurité critique, attraper ses propres exceptions et `return False` explicitement.
- **`ask_user` bloque sur `input()`** : appelée depuis un contexte sans stdin interactif (worker, thread), la question tombe en `EOFError` → refus automatique. Comportement sûr, mais à connaître pour les agents autonomes de [[agents-py]].

## Liens

- Modules liés : [[tools-py]] (consomme `paint`, complète la blocklist), [[loop-py]] (branche `check_permission` et `emit` sur chaque tool_use), [[mcp-runtime-py]] (lit `mcp.servers` via `load_config`), [[main-py]] (émet les événements de session)

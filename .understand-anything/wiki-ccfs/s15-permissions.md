---
title: "s15 · Permissions YAML"
session: 15
phase: "Durcissement production"
fichier: "inspiration/claude-code-from-scratch/s15_permissions.py"
lignes: 169
tags: [permissions, yaml, governance, guarded-dispatch, middleware, ask-user]
prev: "s14-tools-extended"
next: "s16-event-bus"
---

# s15 · Permissions YAML

> **En une phrase** : chaque entrée de la table de dispatch est enveloppée dans `_guarded()`, qui soumet l'appel d'outil à `check_permission()` et aux trois étages de `config/permissions.yaml` (`always_deny` → `always_allow` → `ask_user`) avant — ou au lieu — de l'exécuter.

## Rôle dans le harness

Jusqu'ici, tout ce que le modèle demande est exécuté (au blacklist `_ALWAYS_BLOCK` de core.py près, codé en dur dans `run_bash`). Or un agent autonome qui enchaîne des tours peut produire un `rm`, un `git push` ou un `pip install` sans qu'aucun humain ne l'ait validé. La devise de la session (ligne 6) : *« Trust is earned; every action is judged before it runs »*.

La réponse suit le quatrième principe du harness engineering énoncé par le README : **« Permissions are declarative, not procedural — what is allowed, blocked, or requires approval lives in configuration, not code. »** Les règles sont des regex dans un YAML externe, pas des `if` dans les outils. Le docstring (lignes 18–21) nomme le pattern : *Guarded Dispatch* — on sépare « ce que fait l'outil » de « qui a le droit de le faire », ce qui permet d'auditer la politique de sécurité sans toucher au code des outils.

L'analogie README (tableau Phase 4) : **« CC permission governance »**. Le vrai Claude Code fonctionne exactement ainsi — des règles `allow`/`deny`/`ask` dans `settings.json`, évaluées avant chaque tool call, avec prompt interactif pour les cas ambigus. Le repo jumeau learn-claude-code introduit le même mécanisme dans sa session 3 (gate à trois issues allow/ask/deny) ; la version ccfs le rend *déclaratif* (YAML) et le branche par enveloppement du dispatch plutôt que dans la boucle.

Point d'architecture à retenir : la boucle (`stream_loop`) et les outils (`run_*`) sont strictement inchangés. La gouvernance s'insère **entre les deux**, dans la table de dispatch — l'endroit exact où [[s02-tool-use]] avait créé le point d'extension.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–22 | Shebang & docstring | Motto, les 3 étages de gouvernance, le pattern Guarded Dispatch |
| 24–27 | Imports stdlib | `os`, `sys`, `typing` |
| 29–42 | Imports core | Outils unitaires (`run_*`), `EXTENDED_TOOLS`, `stream_loop`, `load_rules`, `check_permission` |
| 44–56 | Configuration | `RULES` (chargement du YAML), `SYSTEM` (persona « security protocols active ») |
| 58–90 | **Le mécanisme** | `_guarded()` : le middleware de permission |
| 93–116 | **Le mécanisme** | `PERM_DISPATCH` : la table de dispatch reconstruite, chaque entrée enveloppée |
| 118–163 | REPL | `main()` : boucle de saisie, `stream_loop` avec `PERM_DISPATCH` |
| 166–169 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`RULES` (ligne 48)** : `load_rules()` est appelé **une seule fois au démarrage** et le résultat est passé à chaque `check_permission`. Le commentaire le justifie : politiques cohérentes sur toute la session. Corollaire : éditer le YAML pendant que l'agent tourne n'a aucun effet (voir Pièges).
- **`SYSTEM` (lignes 51–56)** : le prompt prévient le modèle que des protocoles de sécurité sont actifs, qu'un prompt `[PERMISSION]` peut apparaître, et surtout lui donne une stratégie de repli : *« If a command is denied, seek an alternative way to accomplish the task within the permitted bounds. »* Un refus n'est pas une impasse, c'est une donnée que le modèle doit contourner.

### Le fichier `config/permissions.yaml` (53 lignes)

Les regex Python (insensibles à la casse, via `re.IGNORECASE` dans `check_permission`) sont organisées en trois étages, évalués dans cet ordre :

```yaml
always_deny:
  - pattern: "rm -rf /"
    reason: "Recursive root delete blocked"
  - pattern: "curl.*\\| *sh|wget.*\\| *sh"
    reason: "Pipe-to-shell downloads blocked"
always_allow:
  - pattern: "^git (status|log|diff|show|branch|tag)"
    reason: "Read-only git commands are always safe"
ask_user:
  - pattern: "^git (commit|push|merge|rebase|reset)"
    reason: "Git write operations require confirmation"
  - pattern: "\\.env"
    reason: "Accessing .env files requires confirmation"
```

- **`always_deny`** (6 règles) : destruction de la racine, `sudo`, extinction système, écriture sur `/dev/`, fork bomb, téléchargement pipé dans un shell. Blocage immédiat, sans question.
- **`always_allow`** (8 règles) : lecture pure — `ls`, `cat`, `echo`, `pwd`, git en lecture seule, `grep`, `find`, `head`/`tail`/`wc`. Passage silencieux ; ces commandes ne dérangent jamais l'humain.
- **`ask_user`** (7 règles) : les opérations légitimes mais engageantes — `rm`, installations de paquets, git en écriture, `mv`, `chmod`/`chown`, `kill`, et tout ce qui touche un fichier `.env` (la seule règle non ancrée par `^` : elle matche le motif n'importe où, donc aussi `cat .env` — voir Pièges).
- Si aucun étage ne matche : **autorisé par défaut** (commentaire d'en-tête du YAML : *« Evaluation order: always_deny → always_allow → ask_user → default allow »*). C'est un choix permissif, raisonnable pour une démo, inversé dans les environnements stricts.

## Les fonctions, une à une

### `_guarded(tool_name, handler_fn, inp)` — lignes 60–90

Le middleware. Trois arguments : le nom de l'outil, le handler réel à exécuter si la permission passe, et le dict d'arguments fourni par le modèle.

```python
    # Identify the primary 'target' of the command for rule matching.
    # We take the first value in the input dictionary (usually 'command' or 'path').
    # If no input exists, we fallback to checking the tool_name itself.
    check_str: str = str(list(inp.values())[0]) if inp else tool_name

    # Call core.check_permission to evaluate the action against the loaded YAML rules.
    # The function handles console output for DENIED or ASK_USER states.
    is_allowed, reason = check_permission(tool_name, check_str, RULES)

    if not is_allowed:
        # If the check returns False, we short-circuit and never call handler_fn.
        # This prevents the potentially dangerous operation from ever starting.
        return f"Blocked by Permission Policy: {check_str[:80]} (Reason: {reason})"

    # If allowed, proceed to execute the actual tool logic.
    return handler_fn(inp)
```

- **Ligne 78** : la chaîne soumise aux regex est **la première valeur du dict d'entrée** — `command` pour bash, `path` pour read/write/revert, `pattern` pour grep/glob. C'est un raccourci pragmatique : les règles ancrées `^rm ` visent bash, la règle `\.env` attrape aussi bien `cat .env` (bash) que `path=".env"` (read). Mais l'ordre des clés d'un dict reflète l'ordre d'envoi par le modèle — si un jour un outil reçoit ses arguments dans un autre ordre, la mauvaise valeur serait jugée (voir Pièges).
- **Ligne 82** : `check_permission` (de [[core-py]]) fait tout le travail : parcours `always_deny` → `always_allow` → `ask_user`, affichage rouge `[DENIED]` ou prompt jaune `[PERMISSION] ... Allow? [y/N]`, défaut « non » sur Ctrl+C pendant la question. Le retour est un tuple `(bool, raison)`.
- **Lignes 84–87** : en cas de refus, **le handler n'est jamais appelé** (court-circuit) et le message `Blocked by Permission Policy: ...` est renvoyé comme sortie d'outil — donc *au modèle*, via le `tool_result`. Combiné au prompt système, c'est ce qui permet au modèle de chercher une alternative au lieu de réessayer en boucle.
- **Ligne 90** : si autorisé, exécution normale — `_guarded` est transparent.

### `PERM_DISPATCH` — lignes 97–116

La table de dispatch reconstruite, chaque entrée passant par le garde :

```python
PERM_DISPATCH: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "bash":   lambda inp: _guarded(
        "bash",   lambda i: run_bash(i["command"]), inp
    ),
    "read":   lambda inp: _guarded(
        "read",   lambda i: run_read(i.get("path"), i.get("start_line"), i.get("end_line")), inp
    ),
```

Chaque entrée est une double lambda : l'externe (`lambda inp:`) garde la signature attendue par `dispatch_tools` de core.py ; l'interne (`lambda i:`) est le handler réel, passé en argument et appelé seulement si la permission est accordée. Le commentaire (ligne 96) parle de *closure* : chaque lambda interne capture l'implémentation spécifique de son outil. Les six outils sont couverts — y compris `revert` (lignes 113–115), absent de `ASYNC_DISPATCH` de core.py mais bien présent ici.

À noter : `PERM_DISPATCH` est construit à partir des fonctions unitaires `run_*`, pas en enveloppant `EXTENDED_DISPATCH` — c'est plus verbeux mais chaque entrée reste lisible et typée.

### `main()` — lignes 120–163

Le REPL standard du repo : bannière annonçant la source des règles (ligne 129 : `rules from config/permissions.yaml`), saisie cyan protégée par `try/except (EOFError, KeyboardInterrupt)` → `sys.exit(0)` (lignes 136–142), sortie sur vide ou `q`/`exit`/`quit` (lignes 145–147), archivage de la requête, puis :

```python
        # Note: We pass PERM_DISPATCH instead of the raw EXTENDED_DISPATCH.
        # This ensures every model turn is subjected to the permission guard.
        stream_loop(
            messages=history,
            tools=EXTENDED_TOOLS,
            dispatch=PERM_DISPATCH,
            system=SYSTEM
        )
```

- **Lignes 155–160** : le *seul* changement par rapport à [[s14-tools-extended]] est `dispatch=PERM_DISPATCH`. Les schémas (`EXTENDED_TOOLS`) restent identiques : le modèle ne sait pas, au niveau des outils, qu'une gouvernance existe — il ne l'apprend que par le prompt système et par les refus qu'il reçoit.

### Point d'entrée — lignes 166–169

`if __name__ == "__main__": main()` — protection standard.

## Ce qui vient de [[core-py]]

Importés lignes 31–42 :

- **`EXTENDED_TOOLS`** — les 6 schémas d'outils, inchangés (la gouvernance est invisible dans les schémas).
- **`stream_loop`** — la boucle streaming + dispatch ; elle appelle `dispatch[tool_name](input)` sans savoir que l'entrée est gardée.
- **`run_bash`, `run_read`, `run_write`, `run_grep`, `run_glob`, `run_revert`** — les implémentations unitaires, ré-assemblées une à une dans `PERM_DISPATCH` derrière `_guarded`.
- **`load_rules`** — parse `config/permissions.yaml` ; repli sur des règles vides (`{"always_deny": [], ...}`) si le fichier manque.
- **`check_permission`** — le moteur d'évaluation à 4 issues : deny (rouge), allow silencieux, question interactive `[y/N]` (jaune, défaut non), allow par défaut.

## Pièges et détails d'implémentation

- **`load_rules()` au chargement du module, pas à chaque appel** : `RULES` est figé au démarrage (ligne 48). `check_permission` saurait recharger (il appelle `load_rules()` quand `rules=None`), mais s15 lui passe toujours `RULES` — modifier le YAML exige de relancer la session.
- **Seule la *première* valeur d'entrée est jugée** (ligne 78) : pour `write`, c'est `path` qui est évalué, jamais `content` ; pour `grep`, c'est `pattern`. Un contenu malveillant écrit dans un fichier puis exécuté en deux temps passe sous le radar — la gouvernance par regex juge des chaînes, pas des intentions.
- **Défaut permissif** : aucune règle ne matche → autorisé (`"allowed by default (no rule matched)"`). Les regex `always_allow` ancrées en `^` ne couvrent que des commandes *commençant* par la forme sûre ; `ls && rm -rf ~` matche `^ls( |$)`… et passe en silence. Les listes par motifs sont des garde-fous, pas des sandbox.
- **La règle `\.env` n'est pas ancrée** : elle déclenche la confirmation pour *toute* chaîne contenant `.env` — y compris un simple `read` de `.env.example`. Faux positifs assumés pour un secret bien gardé.
- **Le refus est un message, pas une exception** : le modèle reçoit `Blocked by Permission Policy: ...` comme n'importe quelle sortie d'outil, et le prompt système lui dicte la conduite (chercher une alternative). Erreur = donnée, jamais crash — l'invariant du repo.
- **Double couche avec `_ALWAYS_BLOCK`** : même si une règle YAML autorisait `sudo`, `run_bash` de core.py le bloquerait encore via sa blacklist codée en dur. La défense en profondeur n'est pas un accident.
- **`check_permission` lit la réponse au clavier dans `input()`** — pendant un stream, la question `Allow? [y/N]` s'intercale entre les sorties d'outils ; sur un EOF ou Ctrl+C, la réponse par défaut est « n ».

## Lancer la démo

```bash
python s15_permissions.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM), **et le fichier `config/permissions.yaml`** (sans lui, `load_rules` replie sur des règles vides : tout passe). Scénarios à tester au prompt `s15 >>` : « liste les fichiers » (allow silencieux via `^ls`), « supprime test.txt » (prompt jaune `[PERMISSION] ... Allow? [y/N]`), « lance sudo apt update » (rouge `[DENIED]`, et le modèle propose une alternative), « montre-moi le .env » (confirmation requise).

## Liens

- Socle : [[core-py]]
- Session précédente : [[s14-tools-extended]]
- Session suivante : [[s16-event-bus]]
- Sessions liées : [[s02-tool-use]] (la table de dispatch, point d'insertion du garde), [[s16-event-bus]] (interception *dynamique* par hooks, là où s15 est *statique* par règles), [[s21-mcp-runtime]] (autre configuration déclarative en YAML)

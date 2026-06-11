---
title: "s03 · Le système de permission"
session: 03
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s03_permission/code.py"
lignes: 252
tags: [permission, deny-list, approbation-utilisateur, securite]
prev: "s02-tool-use"
next: "s04-hooks"
---

# s03 · Le système de permission

> **En une phrase** : trois barrières (deny list dure, règles contextuelles, approbation utilisateur) s'insèrent devant l'exécution des outils — la boucle ne gagne qu'une ligne : `if not check_permission(block): continue`.

## Rôle dans le harness

L'agent de [[s02-tool-use]] a cinq outils. Les outils fichiers sont bridés par `safe_path`, mais bash reste sans limite : demandez-lui de « nettoyer le projet » et il peut produire `rm -rf /`. Le README pose le principe fondateur de la session : *« Safety can't rely on trusting the model — it needs code: a check before every tool execution. »* La sécurité n'est pas une affaire de confiance envers le modèle, c'est une affaire de code exécuté par le harness.

La solution est un pipeline à trois barrières, traversé dans un ordre fixe par chaque appel d'outil :

| Barrière | Rôle | En cas de correspondance |
|---|---|---|
| 1. Deny list | Opérations interdites pour toujours (`rm -rf /`, `sudo`) | Refus immédiat, sans exécution |
| 2. Règles | Opérations sensibles selon le contexte (écriture hors workspace, `rm`) | Passage à la barrière 3 |
| 3. Approbation | L'humain tranche | `y` → exécution ; sinon refus |

Aucune barrière ne réagit → exécution directe : la voie rapide des opérations ordinaires (lecture, glob…).

Le vrai Claude Code est beaucoup plus riche : le `PermissionResult` connaît **quatre** comportements (`allow`/`deny`/`ask`/`passthrough`), les règles proviennent de **huit sources** fusionnées par priorité (settings utilisateur, projet, local, flags, politique d'entreprise, arguments CLI, commande, session), et un classificateur LLM (`YoloClassifier`) peut auto-approuver en mode auto. Le README assume la simplification : 3 barrières et une seule deny list locale, pour garder le nombre de concepts gérable.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–28 | Docstring | Schéma ASCII des trois barrières, usage |
| 30–47 | Imports & env | Identiques à s02 |
| 49–53 | Configuration | `WORKDIR`, client, `MODEL`, `SYSTEM` (mention de l'approbation) |
| 60–118 | Repris de s02 | `safe_path` + les 5 outils (`run_bash` modifié, voir plus bas) |
| 125–141 | Repris de s02 | `TOOLS` et `TOOL_HANDLERS`, inchangés |
| 149–195 | **Nouveau** | Le pipeline : `DENY_LIST`, `check_deny_list`, `PERMISSION_RULES`, `check_rules`, `ask_user`, `check_permission` |
| 202–231 | Boucle | `agent_loop()` : s02 + insertion de `check_permission()` |
| 234–251 | Point d'entrée | REPL identique à s02 |

## Constantes et configuration

- **`SYSTEM` (ligne 53)** : `"You are a coding agent at {WORKDIR}. All destructive operations require user approval."` — le prompt annonce la règle du jeu au modèle. Information, pas protection : la vraie barrière est dans le code.
- **`DENY_LIST` (ligne 149)** : `["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]` — la liste s'allonge par rapport au `dangerous` de s01/s02 (`mkfs`, `dd if=`, `> /dev/sda`). Elle quitte le corps de `run_bash` pour devenir une constante du pipeline : la politique de sécurité est désormais une donnée, plus un détail d'implémentation d'outil.
- **`PERMISSION_RULES` (lignes 159–166)** : des règles déclaratives — voir l'analyse de `check_rules` ci-dessous.

## Les fonctions, une à une

### `safe_path(p)` — lignes 60–64
Reprise de [[s02-tool-use]] sans modification.

### `run_bash(command)` — lignes 67–74

Reprise de s02, **mais modifiée — et pas seulement en surface** :

```python
def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
```

- La liste `dangerous` interne disparaît : le contrôle remonte dans le pipeline de permission, *avant* l'appel du handler. Séparation des responsabilités : l'outil exécute, le pipeline décide.
- Deux régressions discrètes par rapport à s02 : le `encoding="utf-8", errors="replace"` a disparu (retour au décodage dépendant de la plateforme), et le `except (FileNotFoundError, OSError)` aussi — une `OSError` levée par `subprocess.run` remonterait maintenant jusqu'à `agent_loop` et ferait planter le programme. En pratique avec `shell=True` le cas est rare (le shell existe toujours), mais c'est une perte de robustesse non documentée.

### `run_read` (77–84), `run_write` (87–94), `run_edit` (97–106), `run_glob` (109–118)
Reprises de [[s02-tool-use]] sans modification. `TOOLS` (125–136) et `TOOL_HANDLERS` (138–141) également inchangés.

### `check_deny_list(command)` — lignes 151–155 (Barrière 1)

```python
def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Blocked: '{pattern}' is on the deny list"
    return None
```

Correspondance de sous-chaînes : si un motif de `DENY_LIST` apparaît dans la commande, retour d'un message de blocage ; sinon `None`. La convention de retour `str | None` (raison de blocage ou rien) est le fil conducteur de tout le pipeline — et préfigure la convention des hooks de [[s04-hooks]]. Le README est explicite sur les limites : *« simple string matching is not a reliable security mechanism — command variants and shell expansion can bypass it »* — c'est une démonstration du concept, pas un pare-feu.

### `PERMISSION_RULES` + `check_rules(tool_name, args)` — lignes 159–172 (Barrière 2)

```python
PERMISSION_RULES = [
    {"tools": ["write_file", "edit_file"],
     "check": lambda args: not (WORKDIR / args.get("path", "")).resolve().is_relative_to(WORKDIR),
     "message": "Writing outside workspace"},
    {"tools": ["bash"],
     "check": lambda args: any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
     "message": "Potentially destructive command"},
]

def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None
```

- Chaque règle est un dict à trois clés : `tools` (à quels outils elle s'applique), `check` (un prédicat lambda sur les arguments), `message` (la raison affichée à l'utilisateur). Format déclaratif : ajouter une politique = ajouter un dict, pas modifier une fonction.
- **Règle 1 (lignes 160–162)** : écriture hors workspace. Même logique d'ancrage que `safe_path`, mais ici elle déclenche une *demande d'approbation* au lieu d'une erreur sèche — l'utilisateur peut dire oui. Subtilité : `args.get("path", "")` avec défaut `""` rend la lambda robuste à un input incomplet. (Notez que si l'utilisateur approuve, `safe_path` re-bloquera quand même l'écriture dans le handler — voir Pièges.)
- **Règle 2 (lignes 163–165)** : mots-clés « destructeurs mais légitimes » (`rm `, `> /etc/`, `chmod 777`). Le `"rm "` avec espace final évite de réagir à `rmdir` ou à `format` contenant « rm » — heuristique grossière mais qui montre l'intention : distinguer l'interdit absolu (barrière 1) du douteux-à-confirmer (barrière 2).
- `check_rules` renvoie le message de **la première règle** qui matche : ordre de la liste = priorité.

### `ask_user(tool_name, args, reason)` — lignes 176–180 (Barrière 3)

```python
def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n\033[33m⚠  {reason}\033[0m")
    print(f"   Tool: {tool_name}({args})")
    choice = input("   Allow? [y/N] ").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"
```

Le moment clé : **la boucle d'agent se met en pause au milieu d'un tour** (entre la réponse du modèle et l'envoi des `tool_result`) pour attendre un humain. Le `[y/N]` majuscule sur le N annonce le défaut : tout ce qui n'est pas `y`/`yes` — y compris Entrée à vide — vaut refus. Sécurité par défaut (*fail closed*).

### `check_permission(block)` — lignes 184–195 (le pipeline assemblé)

```python
def check_permission(block) -> bool:
    if block.name == "bash":
        reason = check_deny_list(block.input.get("command", ""))
        if reason:
            print(f"\n\033[31m⛔ {reason}\033[0m")
            return False
    reason = check_rules(block.name, block.input)
    if reason:
        decision = ask_user(block.name, block.input, reason)
        if decision == "deny":
            return False
    return True
```

- **Lignes 185–189** : barrière 1, réservée à bash (seul outil à commandes arbitraires). Si la deny list matche : refus immédiat, **sans question** — pas d'appel à `ask_user`, l'humain ne peut pas outrepasser une interdiction dure.
- **Lignes 190–194** : barrières 2 et 3 chaînées — une règle matche → l'utilisateur tranche. Refus → `False`.
- **Ligne 195** : aucun déclencheur → `True`, exécution directe.
- L'interface est volontairement binaire (`bool`) : la boucle n'a pas besoin de savoir *pourquoi* c'est refusé, juste si elle doit exécuter. Le « pourquoi » est affiché à l'écran, et le modèle reçoit un `"Permission denied."` générique.

### `agent_loop(messages)` — lignes 202–231

Structure de [[s02-tool-use]] intacte ; le changement tient dans le corps de la boucle d'exécution :

```python
        for block in response.content:
            if block.type != "tool_use":
                continue

            print(f"\033[36m> {block.name}\033[0m")

            # s03 change: run through permission pipeline before executing
            if not check_permission(block):
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "Permission denied."})
                continue

            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown: {block.name}"
```

- **Lignes 215–216** : le filtre des blocs s'inverse par rapport à s02 (`if block.type != "tool_use": continue` au lieu d'un `if` englobant) — pur style, ça aplatit l'indentation.
- **Lignes 221–224** : le point central de la session. En cas de refus, on n'exécute pas, **mais on répond quand même** : un `tool_result` avec `"Permission denied."` est ajouté. C'est crucial à deux titres : (1) le protocole de l'API exige un `tool_result` pour *chaque* `tool_use` émis — l'omettre invaliderait la conversation ; (2) le modèle, informé du refus, peut proposer une alternative au lieu de rester bloqué.
- Le refus ne sort pas de la boucle : les autres appels du même tour sont quand même traités, et le tour suivant a lieu normalement.

### Point d'entrée `if __name__ == "__main__"` — lignes 234–251
Repris de [[s02-tool-use]] sans modification (bannière `s03` mise à part).

## Ce qui change par rapport à [[s02-tool-use]]

- **+ `DENY_LIST`** (ligne 149) : extraite de `run_bash`, enrichie (`mkfs`, `dd if=`, `> /dev/sda`).
- **+ `check_deny_list()`** (151–155), **+ `PERMISSION_RULES`** (159–166), **+ `check_rules()`** (168–172), **+ `ask_user()`** (176–180), **+ `check_permission()`** (184–195).
- **`agent_loop`** : insertion du test `if not check_permission(block)` avec réponse `"Permission denied."` (lignes 221–224).
- **`run_bash` modifié** : perd sa liste `dangerous` interne (déplacée dans le pipeline), mais perd aussi — vraisemblablement par accident — l'encodage UTF-8 forcé et le rattrapage de `FileNotFoundError`/`OSError` introduits ou présents en s02.
- **`SYSTEM`** : mentionne désormais l'approbation requise pour les opérations destructrices.
- Modèle de sécurité global : « faire confiance au modèle » → « pipeline à trois barrières dans le harness ».

## Pièges et détails d'implémentation

- **Toujours répondre au `tool_use`** : même refusé, l'appel reçoit un `tool_result` (`"Permission denied."`). Oublier ce point casse le protocole de l'API et prive le modèle du feedback nécessaire pour changer de stratégie.
- **Deny ≠ ask** : la barrière 1 refuse *sans* consulter l'humain ; seule la barrière 2 mène au dialogue. Confondre les deux (tout faire passer par `ask_user`) affaiblit la garantie « jamais, même approuvé ».
- **Refus par défaut** : dans `ask_user`, Entrée à vide = deny. Le chemin paresseux est le chemin sûr.
- **Double contrôle incohérent sur l'écriture hors workspace** : si l'utilisateur approuve une écriture hors workspace (barrière 3), `safe_path` dans `run_write` lèvera quand même `ValueError` → `"Error: Path escapes workspace"`. L'approbation est donc inopérante pour ce cas précis — illustration involontaire de l'intérêt d'un point de décision unique.
- **`run_bash` peut désormais planter la boucle** : sans le `except (FileNotFoundError, OSError)` de s02, une `OSError` traverserait `agent_loop`. Régression silencieuse entre deux sessions « cumulatives ».
- **La correspondance de sous-chaînes est contournable** (`rm -r -f /`, `s\udo`, expansion shell…) — le README le dit explicitement ; le vrai CC combine règles multi-sources, analyse de commande et classificateur LLM.

## Liens

- Session précédente : [[s02-tool-use]]
- Session suivante : [[s04-hooks]]
- Sessions liées : [[s01-agent-loop]] (l'embryon `dangerous` dans `run_bash`), [[s04-hooks]] (cette logique exacte migre dans `permission_hook`), [[s06-subagent]] et [[s15-agent-teams]] (la question « qui approuve ? » en multi-agents)

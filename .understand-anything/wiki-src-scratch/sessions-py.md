---
title: "sessions.py · Persistance des conversations"
phase: "Intégration"
fichier: "src_scratch/sessions.py"
lignes: 120
tags: [sessions, persistance, json, resume, fork]
---

# sessions.py · Persistance des conversations

> **En une phrase** : un fichier JSON lisible par conversation sous `STATE_DIR/sessions` — save, resume, fork, titrage — avec une astuce centrale : les blocs pydantic du SDK sont aplatis en dicts purs que l'API ré-accepte tels quels.

## Rôle dans le harness

Sans persistance, fermer le REPL efface tout. Ce module reprend la mécanique de s17 : chaque session est un fichier `<id>.json` contenant des métadonnées (`id`, `title`, `created`, `updated`, `turns`) et l'historique complet des messages. [[main-py]] sauvegarde automatiquement après chaque tour et expose `:sessions`, `:resume`, `:fork`, `:title`, `:save`.

Le problème technique que tout le module résout est la **sérialisation** : dans l'historique vivant, les tours assistant sont des objets pydantic du SDK (`TextBlock`, `ToolUseBlock`), pas du JSON. `_serialize` les aplatit via `model_dump()` à la sauvegarde ; au rechargement, ils restent des dicts purs — et l'API Anthropic accepte indifféremment objets SDK et dicts, donc un historique rechargé repart sans conversion inverse. C'est ce qui rend `save → load → save` idempotent.

À noter : le bug s17 le plus connu (entrée vide au REPL → message `content:""` → erreur API) n'est pas corrigé ici mais dans [[main-py]], côté saisie — ce module ne voit que des historiques déjà valides.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–7 | Docstring | Le format : meta + messages, blocs aplatis via `model_dump()` |
| 8–13 | Imports | stdlib + `STATE_DIR`, `paint`, `write_json` ([[core-py]]) |
| 15–18 | Constantes | `SESSIONS_DIR` (mkdir à l'import), `_META_KEYS` |
| 21–43 | Helpers privés | `_now`, `_new_id`, `_path`, `_read`, `_write` |
| 46–55 | Sérialisation | `_serialize` — le pivot du module |
| 58–78 | API | `save_session` |
| 81–103 | API | `load_session`, `list_sessions` |
| 106–120 | API | `fork_session`, `set_title` |

## Constantes et configuration

- **`SESSIONS_DIR` (lignes 15–16)** : `STATE_DIR / "sessions"`, créé à l'import (`mkdir(parents=True, exist_ok=True)`) — aucune fonction n'a à vérifier son existence.
- **`_META_KEYS` (ligne 18)** : `("id", "title", "created", "updated", "turns")` — le sous-ensemble du JSON retourné comme meta par `load_session`, sans l'historique.

## Les fonctions, une à une

### `_now()` — lignes 21–22

`datetime.now().isoformat(timespec="seconds")` — horodatage lisible, précision seconde, utilisé pour `created` et `updated`.

### `_new_id()` — lignes 25–27

```python
    return f"{datetime.now():%y%m%d}-{uuid.uuid4().hex[:4]}"
```

Id court et lisible : date du jour + 4 hexas aléatoires (ex. `260611-a3f8`). La date en préfixe rend le tri lexical ≈ tri chronologique et l'id facile à retaper dans `:resume`.

### `_path(sid)` — lignes 30–31

`SESSIONS_DIR / f"{sid}.json"` — la convention de nommage en un seul endroit.

### `_read(sid)` — lignes 34–38

Charge le JSON ; session absente → `FileNotFoundError` avec message explicite (`session <sid> introuvable`), que [[main-py]] laisse remonter comme erreur de commande.

### `_write(data)` — lignes 41–43

```python
def _write(data: dict) -> None:
    data["updated"] = _now()
    write_json(_path(data["id"]), data)
```

Le point de sortie unique : rafraîchit `data["updated"]` puis délègue la sérialisation à `write_json` de [[core-py]] (importé en tête). Le helper mutualisé applique partout la même stratégie — `json.dumps(..., indent=2, ensure_ascii=False)` (accents lisibles dans le fichier) en encodage UTF-8 explicite. Toute écriture passant par là, `updated` ne peut jamais être oublié, et le format JSON est cohérent avec le reste du harness.

### `_serialize(messages)` — lignes 46–55

```python
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [b.model_dump() if hasattr(b, "model_dump") else getattr(b, "__dict__", b)
                 for b in c]
        out.append({"role": m["role"], "content": c})
```

- Un `content` **string** (message user simple) passe tel quel ; une **liste** de blocs est aplatie élément par élément.
- La cascade `model_dump()` → `__dict__` → l'objet lui-même rend la fonction **idempotente** : un bloc pydantic est aplati ; un dict pur (historique rechargé, `tool_result` construit à la main) n'a ni `model_dump` ni `__dict__`, donc le `getattr(b, "__dict__", b)` le retourne intact. On peut resauvegarder un historique mélangeant objets SDK et dicts sans rien casser.
- Seuls `role` et `content` sont conservés — tout champ parasite d'un message est filtré à la sauvegarde.

### `save_session(messages, sid=None, title=None)` — lignes 58–78

Crée ou met à jour ; retourne l'id (que [[main-py]] mémorise dans son `state`).

```python
    if sid and _path(sid).exists():
        try:
            data = _read(sid)  # préserve created/title existants
        except (json.JSONDecodeError, OSError):
            print(paint(f"  [sessions] {sid}.json corrompu, réécrit proprement", "yellow"))
```

- **Lignes 61–65** : si le fichier existe, on le relit pour préserver `created` et `title` ; s'il est corrompu, warning jaune et réécriture propre — la sauvegarde n'échoue jamais à cause d'un fichier malade.
- **Ligne 66** : `sid = sid or _new_id()` — première sauvegarde = création.
- **Lignes 71–74** : auto-titrage comme s17 — faute de titre, le premier message user dont le `content` est une *string* fournit les 50 premiers caractères (repli `"Session"`). Les messages user à contenu liste (les `tool_result`) sont ignorés par le `isinstance(m.get("content"), str)`.
- **Lignes 75–77** : `turns = len(messages)`, sérialisation, `_write` (qui pose `updated`).

### `load_session(sid)` — lignes 81–84

Retourne `(messages, meta)` : les messages sont les dicts purs du JSON, acceptés tels quels par l'API ; la meta est reconstruite par compréhension sur `_META_KEYS`. Aucune désérialisation vers des objets SDK — inutile, voir « Rôle dans le harness ».

### `list_sessions()` — lignes 87–103

Tableau texte aligné (`ID / MAJ / TOURS / TITRE`), trié par `updated` décroissant — les sessions actives en tête. Robustesse :

```python
        except Exception:  # un fichier cassé ne casse pas le listing
            print(paint(f"  [sessions] fichier illisible ignoré : {p.name}", "yellow"))
```

Un JSON corrompu est signalé et sauté, le listing continue. L'id est peint en cyan (ligne 100) ; titre tronqué à 40 caractères, date à 16 (`YYYY-MM-DDTHH:MM`). Vide → `"(aucune session)"`, jamais une chaîne vide ambiguë.

### `fork_session(sid)` — lignes 106–113

Recharge la session, lui donne un **nouvel id**, un titre `Fork de <ancien titre tronqué à 30>` et un `created` neuf, puis `_write`. L'original n'est pas touché ; les deux historiques divergent librement ensuite. C'est l'implémentation la plus simple possible du fork : une copie sous un autre nom.

### `set_title(sid, title)` — lignes 116–120

Relit, remplace `title`, `_write` (qui rafraîchit `updated` au passage). Utilisée par la commande `:title` — qui dans [[main-py]] passe en réalité par `save_session(..., title=rest)` pour créer la session si elle n'existe pas encore ; `set_title` reste l'API directe pour une session déjà existante.

## Qui l'utilise

- [[main-py]] — seul importeur. Auto-save après chaque tour du REPL (`save_session(state["messages"], state["sid"])`), et les commandes `:sessions` (`list_sessions`), `:resume` (`load_session`), `:fork` (`fork_session` puis `load_session`), `:title` / `:save` (`save_session`).

## Pièges et détails d'implémentation

- **Pas de verrou ni d'écriture atomique** : deux REPL ouverts sur le même sid s'écrasent mutuellement (dernier écrivain gagne), et un crash en plein `write_json` peut laisser un JSON tronqué — que `save_session` et `list_sessions` savent toutefois absorber sans crash.
- **L'auto-titre est figé à la première sauvegarde** : `if not data.get("title")` (ligne 71) ne recalcule jamais — renommer passe par `:title`. Après une compaction de [[context-py]], le premier message user peut être le résumé : seul le titre d'une session *nouvelle* sauvegardée à ce moment-là en hériterait.
- **`turns` compte les messages, pas les échanges** : un tour utilisateur→assistant avec 3 allers-retours d'outils pèse 8 « turns ». C'est un indicateur de volume, pas de conversations.
- **`list_sessions` lit chaque fichier en entier** juste pour 4 champs de meta — O(n × taille des historiques). Sans conséquence à l'échelle d'un usage personnel, à revoir si les sessions se comptent en centaines.
- **`fork_session` conserve `turns` et `messages` tels quels** mais reset `created` : la date de création reflète la naissance du fork, pas celle de la lignée.

## Liens

- Modules liés : [[core-py]] (`STATE_DIR`, `paint`, `write_json`), [[main-py]] (auto-save et commandes `:`), [[context-py]] (la compaction — l'autre mécanisme de survie de l'historique, dans la fenêtre du modèle plutôt que sur disque)

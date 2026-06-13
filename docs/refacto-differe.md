# Refacto différée — pistes de simplification/dédup repérées mais pas faites

> Repérées lors du passage `simplify` du 2026-06-12 sur `packages/`. **Écartées par prudence** :
> elles touchent au comportement déjà vérifié (visuel + smoke) ou ajoutent de la complexité pour un
> gain pas encore nécessaire. À reprendre avec la même batterie de tests (`tests/smoke_*.py` +
> Playwright sur le front : flux/caret, scroll, Entrée, suppression). Le refacto **sûr** a déjà été
> appliqué (mekillm `_observe_call`/`_prepare`/`_usage_from`, front `_msg_shell`/`_md`, CSS mort).

## A. Dédup structurelle du front (à tester soigneusement — touche au comportement)

1. **Unifier rendu *live* (`app.py:_render_event`) et *replay* (`views.py:render_thread`).**
   Les deux rendent les mêmes choses (texte assistant, blocs `[bash]`) par deux chemins : événements
   temps-réel vs messages OpenAI persistés. Ils partagent déjà `render_message`/`render_tool` ; on
   pourrait pousser le partage (normaliser l'historique en « événements » avant de le rejouer). Gain
   réel sur `app.py`, mais risque sur le streaming. *NB : ne pas tenter de fusionner en un seul chemin
   — les deux formats d'entrée sont différents par nature.*

2. **Remplacer les 5 dicts-références par `nonlocal` ou un petit objet d'état.**
   `clock_ref`, `thread_ref`, `thinking_ref`, `stream_ref`, `state` (`app.py`) sont des cellules
   mutables de closure. Un `@dataclass`/objet `UiState` (ou `nonlocal` là où c'est mutéé) réduirait le
   bruit (`stream_ref["body"]` → `state.stream_body`). Churn important sur ~20 sites → bien tester.

3. **`_render_event` if/elif → table de dispatch `{type → handler}`.**
   Contrainte : les handlers ont besoin des closures de `index()` (`stream_ref`, `inner`, …), donc la
   table doit être construite *dans* `index()` — gain de lignes incertain. À évaluer avec l'objet
   d'état du point 2.

4. **`stream_ref["text"]` est de l'état dérivé.** Le label de streaming (`stream_ref["lbl"].text`)
   contient déjà la chaîne accumulée ; on peut supprimer le champ `text` et lire `lbl.text` aux 2
   points de consommation (finalisation, gel sur `RunError`).

5. ~~**Extraire `_bash_cmd(args)`**~~ **(fait — outils étendus, 2026-06-13)** : `views.tool_summary(args)`
   centralise désormais l'extraction du résumé (1er de `command`/`path`/`pattern`), utilisé à la fois par
   `app.py:_render_event` (dict `ev.args`) et `views.py:render_thread` (JSON décodé). **Reste ouvert** :
   `render_thread` parse encore du JSON wire OpenAI — l'idéal serait que l'appelant (ou `sessions.py`)
   fournisse des `tool_calls` déjà normalisés.

## B. Efficacité (utile quand ça montera en charge — pas critique en local mono-utilisateur)

6. **`_scroll_bottom()` par token.** En streaming, un aller-retour `ui.run_javascript` part à chaque
   `AssistantDelta`. Throttler (1 fois sur N, ou seulement aux frontières de tour + 1 fois à la fin).

7. **`set_text(chaîne entière)` par token.** À chaque token on renvoie toute la chaîne accumulée au
   navigateur (coût quadratique sur une longue réponse). Rendu *append-only* ou batché (~50 ms).

8. **`SessionStore.list()` relit/parse tous les fichiers à chaque appel** (appelé à chaque
   `_refresh_sidebar`, donc après chaque tour). Cache `list[SessionMeta]` invalidé sur
   `create`/`save`/`delete`. *Attention : ajoute de l'état — à ne faire que si le nombre de sessions
   grossit.*

9. **`_refresh_sidebar()` reconstruit tout le DOM de la barre latérale** à chaque fin de tour ; seule
   la liste des sessions change. Mise à jour ciblée (ne reconstruire que `.sessions`).

## C. Écartés VOLONTAIREMENT (ne pas « corriger » sans précaution — ça casse quelque chose)

- **`sessions.py:_now_iso` dupliqué avec `observability.now_iso`** : ne **pas** importer depuis
  `mekillm` — `sessions.py` est volontairement sans dépendance (testé seul par `smoke_mekichat` qui
  n'a pas `packages/` sur le `sys.path`). La duplication (2 lignes) paie le découplage.
- **Cacher le chemin de log (`observability._log_file`) à l'import** : casserait
  `smoke_packages` qui pose `MEKILLM_LOG_FILE` au runtime avant d'émettre.
- **Cacher le CSS au niveau module** (`app.py`, au lieu de le relire à chaque page) : perd le
  rechargement CSS « live » pratique en dev (un simple rafraîchissement applique les changements).

## D. Idées d'amélioration (UX / features différées)

1. **Afficher le markdown EN DIRECT pendant le streaming.** Aujourd'hui la bulle de streaming montre
   le **texte brut** (+ caret), puis bascule en markdown rendu seulement à la fin (`AssistantDone` →
   `views.finalize_stream`). But : rendre le **markdown au fil de l'eau** (titres / gras / listes /
   code qui se forment pendant la frappe). *Délicat* : re-parser tout le markdown à chaque token est
   coûteux et peut « flicker » ; prévoir un rendu **incrémental throttlé** (toutes les ~50-100 ms ou
   tous les N tokens) et gérer proprement les blocs partiellement formés (code, listes). Concerne
   `views.render_stream_bubble` / `finalize_stream` et la branche `AssistantDelta` de
   `app.py:_render_event`.

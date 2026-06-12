# Design — `mekichat` : front web (NiceGUI) pour l'agent `packages/`

> Date : 2026-06-12 · Statut : **validé, prêt pour le plan d'implémentation**
> Maquette visuelle : [`2026-06-12-mekichat-mockup.html`](2026-06-12-mekichat-mockup.html) (ouvrir dans un navigateur)

## 1. Objectif

Doter `packages/` d'un **front web en Python** : un dashboard d'agent en **mode conversation type
Discord**. On y voit le **modèle**, l'**heure**, le **session_id**, la **liste des messages**, les
**outils exécutés** (`bash`), et on **dialogue avec l'agent** existant.

Pour l'instant le dashboard = une seule vue : la conversation. L'architecture reste ouverte pour y
greffer d'autres panneaux plus tard (observabilité, tâches, etc.).

## 2. Décisions de cadrage (verrouillées)

| Sujet | Décision | Raison |
|-------|----------|--------|
| Techno front | **NiceGUI** (web, 100 % Python, bâti sur FastAPI + Vue/Quasar) | UI écrite en Python, **même process** que l'agent → on importe `mekicore`/`mekillm` directement, pas d'API HTTP ni de JS à écrire. FastAPI reste dessous si besoin plus tard. |
| Frontière front/back | **Import direct, in-process** | « intégrer facilement notre agent » |
| Streaming | **Oui** (token par token) | demandé ; pièce s13 à ajouter dans mekillm |
| Outils | **Oui** : afficher + exécuter `bash` dans le fil | demandé |
| Persistance | **Oui** : sessions sauvegardées sur disque | demandé ; reprise après redémarrage |
| Multi-sessions | **Oui** : créer / lister / basculer | demandé ; barre latérale |
| Identité visuelle | **Cyberpunk, thème « Phosphore »** (vert phosphore + magenta) | choisi ; cf. §8 + maquette |

Le front ne contient **aucune logique d'agent** : il consomme un flux d'événements et l'affiche.
Toute l'intelligence reste dans `mekicore`/`mekillm` (testable sans UI ; le REPL console en profite).

## 3. Architecture / arborescence

```
packages/
  mekillm/    (existant)  + LLM.stream()              ← brique 1 : streaming (s13)
  mekicore/   (existant)  + events.py, run_agent()    ← brique 2 : boucle qui émet des événements
                          base.agent_loop réexprimé sur run_agent (REPL non-régressé)
  mekichat/   (NOUVEAU)   __init__.py
                          app.py        ← page NiceGUI : layout, CSS, câblage, send handler, thème
                          views.py      ← helpers de rendu (un message, un bloc outil) — garde app.py focalisé
                          sessions.py   ← Session + SessionStore (persistance disque)
.sessions/    (NOUVEAU, racine, gitignoré)  ← une conversation = un fichier <id>.json
.logs/        (existant)                      ← CallRecord JSONL (déjà là)
tests/        + smoke_mekichat.py            ← réseau-free, sans clé API
requirements.txt  + nicegui
```

Respect des règles projet (CLAUDE.md) : tests dans `tests/`, données runtime à la racine
(`.sessions/`, `.logs/`) jamais dans `packages/`, `.env` à la racine. `packages/` reste documenté à
la main dans `docs/wiki-packages/` (à mettre à jour après implémentation).

## 4. Briques back

### 4.1 Streaming dans `mekillm` — `LLM.stream()`
Générateur qui appelle l'API OpenAI en `stream=True` :
- **yield les tokens de texte** au fil de l'eau ;
- **réassemble** les `tool_calls` (qui arrivent fragmentés) + `finish_reason` + `usage` ;
- rend à la fin un `LLMResponse` complet (même forme qu'aujourd'hui) ;
- émet le **même `CallRecord`** d'observabilité (succès comme erreur).

`complete()` reste inchangé (chemin non-streaming).

### 4.2 Boucle à événements dans `mekicore` — `events.py` + `run_agent()`
`run_agent(messages, llm, tools, dispatch, *, stream=True)` : générateur qui **yield des événements
typés** au lieu d'imprimer. Il mute `messages` en place (append assistant + messages `role:"tool"`).

| Événement | Émis quand | Le front en fait… |
|-----------|-----------|-------------------|
| `AssistantDelta(text)` | chaque token streamé | l'ajoute à la bulle assistant en cours |
| `AssistantDone(text)` | fin du texte d'un tour | fige la bulle |
| `ToolStarted(id, name, args)` | l'agent appelle un outil | ajoute un bloc `[bash] …` (repliable) |
| `ToolFinished(id, output)` | l'outil a répondu | remplit la sortie, statut DONE/ERR |
| `RunFinished()` | la boucle est finie | persiste la session |
| `RunError(message)` | exception LLM/outil | bulle d'erreur ; la boucle se termine proprement |

**Compat REPL** : `base.agent_loop` est **réécrit par-dessus `run_agent`** (rend les événements en
`print`). Pour ne pas casser le smoke existant (stub avec seulement `.complete`), `agent_loop` appelle
`run_agent(stream=False)` par défaut → chemin `complete`. Le streaming est **opt-in**.

### 4.3 Sessions persistées — `mekichat/sessions.py`
```python
@dataclass
class Session:
    id: str            # court (uuid/timestamp)
    title: str         # début du 1er message utilisateur
    model: str
    created_at: str    # ISO
    messages: list     # historique au format OpenAI (system/user/assistant/tool)
```
`SessionStore` : **un fichier JSON par session sous `.sessions/`** (cohérent avec `.logs/`).
API : `create()`, `list()` (pour la barre latérale), `load(id)`, `save(session)`.
Dossier surchargeable par env (`MEKICHAT_SESSIONS_DIR`) — utile pour les tests.

## 5. Front NiceGUI — correspondance avec la maquette

| Maquette | NiceGUI |
|----------|---------|
| Look « Phosphore » complet | `ui.add_head_html(...)` : Google Fonts (Chakra Petch + Share Tech Mono) + la feuille CSS de la maquette telle quelle |
| Toolbar palettes (bonus) | `ui.row` ; chaque bouton fait `body.setAttribute('data-theme', …)` (échange de variables CSS) |
| Barre latérale sessions | `ui.left_drawer` : liste cliquable + bouton *nouvelle session* |
| En-tête modèle/SID/tokens/horloge | `ui.header` + chips ; horloge via `ui.timer(1.0, …)` ; tokens via un hook `observe.add_hook` |
| Fil de messages | conteneur scrollable ; un message = composant (avatar + nom + corps) construit dans `views.py` |
| Bloc `[bash]` | `ui.expansion` stylé (repliable, statut DONE/ERR) |
| Composer | `ui.textarea` + bouton d'envoi (Entrée = envoyer, Maj+Entrée = nouvelle ligne) |

## 6. Flux de données (streaming sans figer l'UI)

NiceGUI est async ; `run_agent` est bloquant (réseau). On **pilote le générateur pas-à-pas** dans un
thread, sans plomberie manuelle :

```python
gen = run_agent(session.messages, llm, TOOLS, DISPATCH, stream=True)
while True:
    ev = await run.io_bound(next, gen, _DONE)   # un pas dans un thread → rend la main à l'event loop
    if ev is _DONE:
        break
    render(ev)                                  # met à jour les éléments NiceGUI
store.save(session)                             # persistance en fin de tour
```

Chaque token = un `next()` → l'UI se rafraîchit entre chaque événement, sans bloquer. Idiomatique
NiceGUI (pas de threads/queues à gérer à la main).

## 7. Gestion d'erreurs

- **Clé API manquante** → bandeau clair au démarrage (`OPENROUTER_API_KEY manquant dans .env`).
- **Erreur LLM** (réseau/provider) → `run_agent` l'attrape → `RunError(msg)` → bulle rouge ; la boucle
  se termine proprement (mekillm a déjà loggé `CallRecord status=error`).
- **Erreur d'outil** → déjà géré (`dispatch` renvoie `Error: …`) → affiché dans le bloc, statut `ERR`.

## 8. Identité visuelle — « Phosphore »

Direction **cyberpunk** calibrée (cf. maquette pour le rendu exact) :
- **Palette par défaut Phosphore** : vert phosphore `#39ff14` (agent/UI) + magenta `#ff2bd6`
  (utilisateur/accents) + jaune `#f7ff12` (outils/danger), fond noir verdâtre.
  3 autres palettes commutables en bonus (Blade Runner, Orange/Teal, Acide).
- **Typo** : Chakra Petch (display/UI) + Share Tech Mono (modèle, session_id, heure, bash).
- **Effets** (calibrés pour l'usage quotidien) : glitch RGB sur la marque, ticker HUD `⚠ LIVE`,
  bandes danger, coins coupés `clip-path` (HUD), scanlines + grain léger, datamosh rare, glow néon,
  caret de streaming. **Retirés** : flicker CRT global, grain statique agressif.
- Disposition Discord : lignes `//USER` / `//AGENT` (avatar + nom + heure + tag), pas des bulles.

Tout est transposable en NiceGUI : la feuille CSS de la maquette est réutilisée telle quelle via
`ui.add_head_html`, et les couleurs sont pilotées par variables (`--p1/--p2/--warn`) → le switch de
thème = un simple `data-theme` sur `<body>`.

## 9. Tests (réseau-free, dans `tests/`)

`tests/smoke_mekichat.py` :
1. **SessionStore** : round-trip sur un dossier temp (`create → append → save → load → list`).
2. **run_agent** : séquence d'événements avec un `StubLLM.stream()` (deltas + 1 tool call + texte
   final) → asserte l'ordre des événements et la mutation de `messages` (messages `role:"tool"`).
3. **mekillm.stream** : réassemblage des `tool_calls` streamés à partir de chunks SDK simulés.

Garder `tests/smoke_packages.py` **vert** (compat `agent_loop`, cf. §4.2).

## 10. Ordre de construction (petit à petit — 3 phases)

Chaque phase est utilisable et testable indépendamment.

1. **Sessions + UI statique** (sans LLM) : `sessions.py` + layout Phosphore qui
   affiche/charge/bascule des sessions persistées, *nouvelle session*. → store smoke + visuel conforme.
2. **Chat + outils, non-streaming** : câbler envoi → `run_agent(stream=False)` (via `complete`) →
   bulles + blocs `[bash]` en direct + persistance par tour. → **agent fonctionnel**.
3. **Streaming** : ajouter `LLM.stream` à mekillm + basculer `run_agent(stream=True)` → tokens live +
   caret.

À la fin de la phase 2, l'app marche déjà ; le streaming (phase 3) est la finition.

## 11. Hors périmètre (YAGNI pour ce MVP)

- Interruption/annulation d'un run en cours (s19) — plus tard.
- Authentification / multi-utilisateur — usage local mono-utilisateur.
- Packaging pip de `mekichat` — import par chemin comme le reste de `packages/`.
- Outils au-delà de `bash` (read/write/grep… s14) — viendront enrichir `DISPATCH` sans toucher au front.
- Coût `$` par appel — dépend du chantier transverse `CallRecord.cost_usd`.

## 12. Risques / points d'attention

- **Réassemblage des `tool_calls` en streaming** : c'est la partie la plus subtile (fragments
  `index`/`id`/`arguments` à concaténer). Bien couverte par le test §9.3.
- **Coût d'un `next()` par token via `io_bound`** : overhead acceptable en local pour le MVP ; si gênant,
  on pourra batcher les deltas plus tard.
- **NiceGUI = nouvelle dépendance** : ajout à `requirements.txt` ; vérifier l'install Windows.

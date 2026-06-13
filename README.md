# mekicode 🤖

> **Construire son propre « agent IA », de zéro, en Python — pour comprendre comment ça marche
> sous le capot, puis en faire un vrai produit.**

`mekicode` est un *agent harness* : la mécanique qui transforme un simple modèle de langage (LLM) en
**agent** capable de *réfléchir, agir, observer le résultat, recommencer*. On l'a écrit à la main, en
français, en s'inspirant de 3 projets de référence — d'abord pour **apprendre**, ensuite pour en tirer
des **paquets réutilisables** et une **vraie appli de chat**.

---

## 🧠 L'idée en une image

Un agent, c'est une **boucle** toute bête :

```
   tu écris ──▶  l'agent RÉFLÉCHIT (appelle le LLM)
                       │
                       ├─▶ il veut juste répondre ?  ──▶  il te répond ✅
                       │
                       └─▶ il a besoin d'un OUTIL ?  ──▶  il lance `bash`,
                                                          lit le résultat,
                                                          et recommence 🔁
```

C'est exactement ce que fait Claude Code, Cursor & co. `mekicode` reconstruit cette boucle pièce par
pièce, sans magie.

Pour rester clair, le code est découpé en **3 paquets**, comme 3 organes :

| Paquet | Analogie | Son job |
|--------|----------|---------|
| 🗣️ **`mekillm`** | la **voix & les oreilles** | parler aux modèles (OpenRouter, ollama, litellm…) et **traduire** leurs réponses dans un format unique |
| 🧠 **`mekicore`** | le **cerveau & les mains** | la boucle *réfléchir → agir*, et ses **outils** (`bash` + `read`/`write`/`edit`/`grep`/`glob`) pour agir pour de vrai |
| 🎭 **`mekichat`** | le **visage** | une **interface web** cyberpunk pour discuter avec l'agent |

Chaque paquet ne connaît que celui d'en dessous : **`mekichat → mekicore → mekillm`**. On peut donc
réutiliser `mekillm` tout seul dans n'importe quel projet.

---

## 🚀 En 30 secondes

```bash
pip install -r requirements.txt          # dépendances (openai, nicegui…)
# mettre sa clé dans .env  (voir .env.example : OPENROUTER_API_KEY, MEKILLM_MODEL)

.\start-chat.ps1                         # ⟶  l'appli web sur http://localhost:8080
# ou : python packages/mekichat/app.py
```

Pas envie d'interface ? Le mode terminal :

```bash
.\start.ps1                              # REPL : python packages/mekicore/main.py
```

---

## ✨ Ce que ça sait faire (la version sans jargon)

- 💬 **Discuter avec un agent qui peut agir** — il ne fait pas que répondre, il peut **lancer des
  commandes shell** (`bash`) pour aller chercher la réponse (compter des fichiers, lire du code, etc.).
- 🛠️ **Lire, écrire et modifier des fichiers** — au-delà de `bash`, l'agent a cinq outils dédiés :
  `read`, `write`, `edit` (remplacement chirurgical d'un fragment), `grep` (recherche regex) et `glob`
  (liste par motif). Ces outils fichiers sont **confinés au dossier du projet** (garde-fou de sécurité ;
  `bash`, lui, reste libre).
- ⌨️ **Streaming** — les mots s'affichent **au fil de l'eau**, comme une vraie frappe, avec un curseur
  clignotant.
- 🧱 **Blocs d'outils colorés & repliables** — quand l'agent utilise un outil, tu **vois** un bloc
  `<glyphe> <NOM>` avec une **couleur dédiée par outil** (bash=ambre, read=cyan, write=vert,
  edit=magenta, grep=violet, glob=bleu). Les blocs sont **repliés par défaut** (clic pour ouvrir) et
  affichent une **info compacte** dans l'en-tête (nombre de lignes lues, commande, `+N -N` lignes
  modifiées, nombre de résultats/fichiers…). L'outil **`edit` montre un diff** (`---` lignes retirées
  en rouge, `+++` ajoutées en vert).
- 💾 **Sessions sauvegardées** — chaque conversation est un fichier ; tu peux fermer, rouvrir,
  retrouver, supprimer.
- 📝 **Markdown** — les réponses sont mises en forme (titres, listes, code).
- 🔌 **Multi-modèle / multi-backend** — un seul `.env` pour basculer entre OpenRouter, ollama (local)
  ou litellm. Aucun code à changer.
- 📊 **Observabilité intégrée** — chaque appel au LLM est tracé (latence, tokens, statut) dans
  `.logs/`, et on peut brancher ses propres *hooks*.
- 🎨 **Look « console de nuit » cyberpunk** — thème néon *Phosphore* (vert + magenta), grille en
  perspective, glitch, scanlines… (les 4 palettes existent dans la maquette).

---

## 📦 Les paquets, fichier par fichier

### 🗣️ `packages/mekillm/` — le provider LLM (réutilisable partout)
Un wrapper du SDK `openai` pointé sur OpenRouter par défaut. Il prend des `messages` et rend une
réponse **normalisée**, identique quel que soit le backend.

| Fichier | À quoi ça sert |
|---------|----------------|
| `config.py` | Résout la config : **arguments > `.env` > défauts** (clé, URL, modèle). |
| `client.py` | Le cœur : la classe **`LLM`** (`complete()` d'un coup, `stream()` token par token), la **normalisation** des réponses (`_normalize`, `_consume_stream`) et les types `LLMResponse` / `ToolCall` / `Usage`. |
| `observability.py` | La **boîte noire** : un `CallRecord` par appel, diffusé vers 3 canaux (logging, JSONL dans `.logs/`, hooks). |
| `__init__.py` | L'API publique : `mekillm.LLM`, `mekillm.complete`, `mekillm.observe`. |

### 🧠 `packages/mekicore/` — le mini-harness (la boucle agent)
La boucle perception-action au format OpenAI, branchée sur `mekillm`.

| Fichier | À quoi ça sert |
|---------|----------------|
| `tools.py` | Les **six outils** : `bash` (avec garde-fous, non confiné) + `read`/`write`/`edit`/`grep`/`glob` **confinés au workspace** (`_safe_path`). Leurs schémas `TOOLS` (ce que le modèle voit) et la table `DISPATCH` (ce qu'on exécute). |
| `events.py` | Les **événements** émis par la boucle : `ThinkingStarted`, `AssistantDelta` (streaming), `AssistantDone`, `ToolStarted`/`ToolFinished`, `RunFinished`, `RunError`. |
| `base.py` | **`run_agent`** : la boucle qui *émet des événements* (consommée par le front) ; **`agent_loop`** : la même chose mais pour le terminal (rend les événements en `print`). |
| `main.py` | Le **REPL** : tape une requête, l'agent boucle, recommence. |

### 🎭 `packages/mekichat/` — le front web (NiceGUI)
Une interface web écrite **100 % en Python** (NiceGUI), qui tourne **dans le même process** que l'agent.

| Fichier | À quoi ça sert |
|---------|----------------|
| `sessions.py` | **Persistance** : un `SessionStore` qui crée / sauve / charge / supprime des sessions (un fichier JSON par conversation, sous `.sessions/`). Pur Python, testable seul. |
| `views.py` | Les **briques de rendu** : une ligne de message (markdown), un **bloc d'outil générique** `▣ <nom>` (read/write/edit/grep/glob, plus seulement bash), l'indicateur « PROCESSING… », la bulle de streaming. |
| `app.py` | La **page** : barre latérale des sessions, en-tête (modèle / session), fil de discussion, zone de saisie. C'est elle qui pilote `run_agent` en streaming et affiche tout en direct. |
| `static/mekichat.css` | Le **thème cyberpunk Phosphore** (variables CSS, glitch, scanlines, coins biseautés…). |
| `__init__.py` | Les exports (`Session`, `SessionStore`…). |

---

## 🧪 Tester (sans clé API, sans réseau)

```bash
python tests/smoke_packages.py     # mekillm + mekicore (LLM stubé, agent loop, streaming…)
python tests/smoke_mekichat.py     # mekichat : persistance des sessions
```

Tout est conçu pour passer **hors-ligne** : on stubbe le SDK et le provider.

---

## 🗂️ Où est quoi ?

```
packages/        le code « produit » (mekillm, mekicore, mekichat)
tests/           les tests (réseau-free) — à la racine
docs/            la doc détaillée → commencer par docs/README.md
  ├── wiki-packages/    le wiki manuel de packages/ (architecture + 1 page par paquet)
  ├── superpowers/      les specs & plans de conception (historique daté)
  └── refacto-differe.md  les pistes de simplification repérées mais pas (encore) faites
ROADMAP.md       l'avancement + les features restantes
CLAUDE.md        les règles du projet
.logs/ .sessions/  données runtime (gitignorées), à la racine — jamais dans packages/
src_scratch/     (à part) la refonte d'étude complète, 23 sessions — backend Anthropic
inspiration/     les repos de référence (non versionnés)
```

> 📚 Pour aller plus loin : **[`docs/README.md`](docs/README.md)** (sommaire), l'architecture des
> paquets, et l'état d'avancement dans **[`ROADMAP.md`](ROADMAP.md)**.

---

*Projet perso d'apprentissage : du « comment marche un agent » jusqu'à une appli de chat qui streame.
Tout en français, tout fait main. 🛠️*

hello world

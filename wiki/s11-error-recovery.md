---
title: "s11 · Récupération d'erreurs"
session: 11
phase: "Contexte & mémoire"
fichier: "inspiration/learn-claude-code/s11_error_recovery/code.py"
lignes: 366
tags: [erreurs, retry, backoff, resilience, fallback-model]
prev: "s10-system-prompt"
next: "s12-task-system"
---

# s11 · Récupération d'erreurs

> **En une phrase** : l'appel LLM est enveloppé de trois chemins de récupération — escalade de `max_tokens` puis prompt de continuation, compact réactif sur dépassement de contexte, backoff exponentiel avec jitter et modèle de repli sur 429/529.

## Rôle dans le harness

Jusqu'à s10, le moindre incident API faisait planter l'agent : un `529 overloaded` et c'est fini — pas de retry, pas de changement de modèle, pas de réduction de contexte. Or, comme le dit le README, *« in production, API errors are the norm »*. Les trois modes d'échec les plus fréquents : **sortie tronquée** (le modèle épuise `max_tokens` en pleine phrase), **dépassement de contexte** (trop long même après compaction), et **pannes transitoires** (429 rate limit / 529 surcharge).

La session conserve intégralement la boucle et l'assemblage de prompt de [[s10-system-prompt]] ; le seul changement est que l'appel LLM est enveloppé dans un `try/except` à plusieurs étages, chaque étage traitant sa classe d'erreur, et qu'après récupération un `continue` renvoie en haut de la boucle. Trois patrons : (1) `max_tokens` → escalade 8K→64K sans réémettre la sortie tronquée, puis prompt de continuation (3 max) ; (2) `prompt_too_long` → compact réactif puis un seul retry ; (3) 429/529 → backoff exponentiel avec jitter (10 essais max), bascule vers `FALLBACK_MODEL` après 3 surcharges consécutives.

Le vrai Claude Code va beaucoup plus loin : le README recense **plus d'une douzaine de codes de transition** évalués après chaque appel (`collapse_drain_retry`, `aborted_streaming`, `stop_hook_blocking`, `token_budget_continuation`…), une formule de backoff identique (`min(500 × 2^attempt, 32000) + jitter 0–25 %`, `withRetry.ts`), le même prompt de continuation (`query.ts:1225-1227`), et une détection de rendements décroissants (3 continuations consécutives gagnant < 500 tokens → arrêt). La version pédagogique se concentre sur les 3 chemins les plus courants ; l'architecture en couches (retry interne / except externe / inspection de `stop_reason`) est la même.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–25 | Docstring | les 3 chemins de récupération, schéma ASCII du flux |
| 27–48 | Imports & configuration | dotenv, `PRIMARY_MODEL`, `FALLBACK_MODEL` (optionnel) |
| 50–61 | Constantes | seuils de retry, `CONTINUATION_PROMPT` |
| 63–99 | Repris de [[s10-system-prompt]] | `PROMPT_SECTIONS`, `assemble_system_prompt`, `get_system_prompt` |
| 102–158 | Repris de s02–s03 | `safe_path`, 3 outils, `TOOLS`, `TOOL_HANDLERS` |
| 161–244 | **NOUVEAU : récupération d'erreurs** | `RecoveryState`, `retry_delay`, `with_retry`, `is_prompt_too_long_error`, `reactive_compact` |
| 247–260 | Contexte | `update_context` (repris de s10) |
| 263–340 | `agent_loop` | les 3 chemins câblés autour de l'appel LLM |
| 343–365 | REPL | affichage de **tous** les messages assistant du tour |

## Constantes et configuration

- `PRIMARY_MODEL = os.environ["MODEL_ID"]` — ligne 47 ; `FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")` — ligne 48, optionnel (`None` si absent).
- `ESCALATED_MAX_TOKENS = 64000` / `DEFAULT_MAX_TOKENS = 8000` — lignes 52–53 : le budget de sortie est multiplié par 8 à la première troncature.
- `MAX_RECOVERY_RETRIES = 3` — ligne 54 : nombre max de prompts de continuation après l'escalade.
- `MAX_RETRIES = 10` — ligne 55 : essais max dans `with_retry` pour les erreurs transitoires.
- `BASE_DELAY_MS = 500` — ligne 56 : base du backoff exponentiel.
- `MAX_CONSECUTIVE_529 = 3` — ligne 57 : seuil de bascule vers le modèle de repli.
- `CONTINUATION_PROMPT` — lignes 58–61 : `"Output token limit hit. Resume directly — no apology, no recap. Pick up mid-thought."` — version condensée du prompt réel de CC.

## Les fonctions, une à une

### `PROMPT_SECTIONS` et `assemble_system_prompt(context)` — lignes 65–80 (repris de [[s10-system-prompt]])

Dict de 4 fragments (`identity`, `tools`, `workspace`, `memory`) et assembleur qui joint les 3 sections fixes plus, si `context["memories"]` est non vide, la section mémoire. Repris de s10 sans changement fonctionnel (la construction de la liste est juste condensée).

### `get_system_prompt(context)` — lignes 86–99 (repris de [[s10-system-prompt]])

Cache déterministe : le contexte est sérialisé par `json.dumps(..., sort_keys=True)` (ligne 88) et comparé à la dernière clé ; en cas de hit, le prompt précédent est retourné sans réassemblage. Identique à s10 (docstring en moins, logs `[cache hit]` / `[assembled]` conservés).

### Outils — lignes 104–158 (repris de [[s02-tool-use]])

`safe_path` (104–108), `run_bash` (111–118), `run_read` (121–128), `run_write` (131–138), `TOOLS` (141–156), `TOOL_HANDLERS` (158) : les 3 outils de base, inchangés. À noter : le schéma de `read_file` expose un paramètre `limit` (ligne 149) depuis s10.

### `class RecoveryState` — lignes 163–170

L'état de récupération, porté par le tour entier (instancié au début d'`agent_loop`) :

```python
class RecoveryState:
    """Track recovery attempts across the loop."""
    def __init__(self):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = PRIMARY_MODEL
```

- `has_escalated` / `has_attempted_reactive_compact` : des **drapeaux à sens unique** — l'escalade et le compact réactif n'ont droit qu'à une chance par tour utilisateur.
- `recovery_count` : compteur de prompts de continuation (plafonné à 3).
- `consecutive_529` : remis à zéro à chaque succès, incrémenté à chaque 529 — c'est lui qui déclenche la bascule de `current_model`.
- `current_model` : le modèle effectif ; une fois basculé sur `FALLBACK_MODEL`, il le reste jusqu'à la fin du tour.

### `retry_delay(attempt, retry_after=None)` — lignes 173–179

```python
def retry_delay(attempt, retry_after=None):
    """Exponential backoff with jitter. Retry-After takes priority."""
    if retry_after:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter
```

- Ligne 177 : doublement à chaque essai (0,5 s → 1 s → 2 s → …), plafonné à 32 s, converti en secondes — la même formule que `withRetry.ts:530-548` dans CC.
- Ligne 178 : jitter aléatoire de 0 à 25 % de la base, pour désynchroniser des clients qui retenteraient tous au même instant (*thundering herd*).
- Ligne 175 : un éventuel `Retry-After` serveur serait prioritaire… mais aucun appelant ne le passe jamais (voir Pièges).

### `with_retry(fn, state)` — lignes 182–223

Le wrapper des erreurs **transitoires**. Appelle `fn()` jusqu'à `MAX_RETRIES` fois ; tout ce qui n'est ni 429 ni 529 est relancé immédiatement vers le handler externe.

```python
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__
            msg = str(e).lower()

            # 429 rate limit -> exponential backoff
            if "ratelimit" in name.lower() or "429" in msg:
                delay = retry_delay(attempt)
                ...
                time.sleep(delay)
                continue
```

- Ligne 188 : un succès remet `consecutive_529` à zéro — seules les surcharges **consécutives** comptent.
- Lignes 191–192 : la classification se fait par **inspection de chaînes** (nom de la classe d'exception + message en minuscules), pas par `isinstance` — zéro dépendance aux types du SDK, au prix d'une certaine fragilité.

```python
            if "overloaded" in name.lower() or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    if FALLBACK_MODEL:
                        state.current_model = FALLBACK_MODEL
                        state.consecutive_529 = 0
                        print(...)
                    else:
                        state.consecutive_529 = 0
                        print(...)
                delay = retry_delay(attempt)
                ...
                time.sleep(delay)
                continue

            # Not transient -> re-raise for outer try/except
            raise
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")
```

- Lignes 204–214 : au 3e 529 consécutif, bascule vers `FALLBACK_MODEL` **si configuré** ; sinon, le compteur est quand même remis à zéro pour éviter de réafficher le message à chaque essai. Le changement de modèle prend effet au prochain appel de `fn` car le lambda passé par `agent_loop` relit `state.current_model`… via son argument par défaut — voir le piège dans `agent_loop`.
- Ligne 222 : le `raise` nu préserve la trace ; le `prompt_too_long` et les autres erreurs traversent donc `with_retry` sans consommer de retries.
- Ligne 223 : après 10 échecs transitoires, une `RuntimeError` synthétique remonte — elle sera traitée comme « unrecoverable » par la boucle.

### `is_prompt_too_long_error(e)` — lignes 226–232

Prédicat par sous-chaînes sur le message d'erreur : `("prompt" et "long")`, ou les codes `prompt_is_too_long`, `context_length_exceeded`, `max_context_window`. Couvre les variantes de formulation de l'API Anthropic et de proxys compatibles.

### `reactive_compact(messages)` — lignes 235–244

Le compact d'urgence, volontairement simplifié :

```python
def reactive_compact(messages: list) -> list:
    """Emergency compact — teaching version keeps last N messages.
    Real CC generates a compact summary via LLM, then retries with
    the compacted message list. Teaching version simplifies to tail
    retention since s08/s09 already cover LLM-based compact."""
    print("  \033[31m[reactive compact] trimming to last 5 messages\033[0m")
    tail = messages[-5:]
    return [{"role": "user",
             "content": "[Reactive compact] Earlier conversation trimmed. "
                        "Continue from where you left off."}, *tail]
```

- Garde les 5 derniers messages derrière un marqueur — pas d'appel LLM, contrairement au `reactive_compact` de [[s08-context-compact]]/[[s09-memory]] qui résume l'historique. La docstring assume cette simplification : le résumé LLM est déjà couvert par s08/s09.
- Attention : contrairement à la version s08/s09, il n'y a **aucune vérification d'appariement** `tool_use`/`tool_result` — voir Pièges.

### `update_context(context, messages)` — lignes 249–260 (repris de [[s10-system-prompt]])

Dérive le contexte de l'état réel : liste des outils, workspace, et contenu de `.memory/MEMORY.md` s'il existe et n'est pas vide. Identique à s10.

### `agent_loop(messages, context)` — lignes 265–340

La boucle où les trois chemins se rejoignent. Structure : `with_retry` à l'intérieur du `try`, `except` pour `prompt_too_long` et l'irrécupérable, puis inspection de `stop_reason` avant l'append.

```python
    system = get_system_prompt(context)
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    while True:
        try:
            response = with_retry(
                lambda mt=max_tokens, mdl=state.current_model:
                    client.messages.create(
                        model=mdl, system=system, messages=messages,
                        tools=TOOLS, max_tokens=mt),
                state)
```

- Lignes 274–279 : le lambda fige `max_tokens` et `current_model` **par arguments par défaut** (`mt=max_tokens, mdl=state.current_model`), évaluation au moment de la création du lambda — l'idiome Python classique contre le *late binding* des closures. Conséquence subtile : si `with_retry` bascule le modèle au 3e 529, les retries **restants de ce même appel** utilisent encore l'ancien `mdl` ; le nouveau modèle ne sert qu'à l'itération suivante de la boucle.

```python
        except Exception as e:
            # Path 2: prompt_too_long -> reactive compact (once)
            if is_prompt_too_long_error(e):
                if not state.has_attempted_reactive_compact:
                    messages[:] = reactive_compact(messages)
                    state.has_attempted_reactive_compact = True
                    continue
                print("  \033[31m[unrecoverable] still too long after compact\033[0m")
                messages.append({"role": "assistant", "content": [
                    {"type": "text",
                     "text": "[Error] Context too large, cannot continue."}]})
                return
```

- Lignes 282–291 : **chemin 2**. Un seul compact réactif autorisé (drapeau) ; s'il ne suffit pas, on abandonne — recompacter ne rendrait pas l'historique plus petit. L'échec est consigné comme un message assistant texte : il apparaît dans la transcription et le REPL l'affichera.
- Lignes 294–298 : tout le reste est irrécupérable — nom + 200 premiers caractères du message dans l'historique, et retour.

```python
        # ── Path 1: max_tokens -> escalate or continue ──
        if response.stop_reason == "max_tokens":
            # First escalation: don't append truncated output, retry same request
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                ...
                continue
            # 64K still truncated: save truncated output + continuation prompt
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                ...
                continue
            print("  \033[31m[max_tokens] recovery limit reached\033[0m")
            return

        # Normal completion: append assistant response
        messages.append({"role": "assistant", "content": response.content})
```

- Lignes 301–307 : **chemin 1**, première troncature : la sortie tronquée est **jetée** (pas d'append), `max_tokens` passe à 64K et `continue` réémet exactement la même requête — le modèle repart de zéro avec 8 fois plus de place. C'est le point que le README martèle : *« messages unchanged, same request with more tokens »*.
- Lignes 310–316 : si 64K ne suffit toujours pas, changement de stratégie : on **conserve** la sortie tronquée et on ajoute le `CONTINUATION_PROMPT` comme tour utilisateur, jusqu'à 3 fois. Le modèle doit reprendre « mid-thought », sans excuse ni récapitulatif.
- Ligne 318 : au-delà, on sort — continuer ne produirait plus rien d'utile (CC formalise cela en « diminishing returns detection »).
- Ligne 321 : l'append « normal » n'a lieu **qu'après** le test `max_tokens` — l'ordre est essentiel pour que l'escalade puisse rejouer la même requête.
- Lignes 326–340 : exécution d'outils standard, puis `update_context` + `get_system_prompt` recalculés après chaque salve d'outils (le cache de s10 absorbe le coût si rien n'a changé).

### REPL — lignes 343–365

Différence notable avec s10 : le REPL note `turn_start = len(history)` avant l'appel (ligne 355) puis affiche les blocs texte de **tous** les messages assistant ajoutés pendant le tour (lignes 359–364) — nécessaire car un tour avec continuations ou erreur consignée produit plusieurs messages assistant, pas seulement le dernier.

## Ce qui change par rapport à [[s10-system-prompt]]

- **Nouveau bloc « Error Recovery »** (lignes 161–244) : `RecoveryState`, `retry_delay`, `with_retry`, `is_prompt_too_long_error`, `reactive_compact`.
- **Nouvelles constantes** (lignes 52–61) : `ESCALATED_MAX_TOKENS`, `DEFAULT_MAX_TOKENS`, `MAX_RECOVERY_RETRIES`, `MAX_RETRIES`, `BASE_DELAY_MS`, `MAX_CONSECUTIVE_529`, `CONTINUATION_PROMPT` ; plus `PRIMARY_MODEL`/`FALLBACK_MODEL` au lieu d'un unique `MODEL`.
- **`agent_loop` réécrite autour de l'appel LLM** : `client.messages.create` nu en s10 → `with_retry(lambda…)` dans un `try/except`, gestion de `stop_reason == "max_tokens"` avant l'append, `max_tokens` devenu variable locale.
- **REPL** : affichage de tous les messages assistant du tour (`turn_start`) au lieu du seul dernier message.
- **Inchangé** : les 3 outils, l'assemblage de prompt (`PROMPT_SECTIONS`, `assemble_system_prompt`, `get_system_prompt`), `update_context`. Le tableau « Changes from s10 » du README confirme : outils identiques, seule la résilience s'ajoute.

## Pièges et détails d'implémentation

- **`retry_after` est un paramètre mort** : `retry_delay` lui donne la priorité, mais `with_retry` appelle toujours `retry_delay(attempt)` sans extraire l'en-tête `Retry-After` de l'exception. Le branchement existe, le câblage manque.
- **Classification d'erreurs par sous-chaînes** : `"429" in msg` matcherait aussi un message contenant « 429 » par coïncidence (un chemin de fichier, par exemple). Pragmatique et indépendant du SDK, mais à durcir en production (CC utilise des types et codes d'erreur dédiés).
- **`reactive_compact` peut casser l'appariement tool_use/tool_result** : `messages[-5:]` peut commencer par un message user de `tool_result` dont l'assistant `tool_use` a été coupé → erreur 400 de l'API au retry. La version s08/s09 ajustait la borne avec `_is_tool_result_message` / `_message_has_tool_use` ; cette garde a disparu dans la simplification.
- **L'escalade est collante** : une fois `max_tokens` passé à 64000, il le reste pour tout le tour (et `has_escalated` interdit une nouvelle « première » escalade). Chaque appel suivant du tour paie le gros budget de sortie.
- **Bascule de modèle à retardement** : à cause des arguments par défaut du lambda, le `FALLBACK_MODEL` ne sert qu'à la prochaine itération de la boucle externe, pas aux retries restants de l'appel en cours.
- **Les erreurs sont historisées comme messages assistant** (`[Error] …`) : le modèle les verra au tour suivant — c'est voulu (il peut s'adapter), mais cela signifie aussi qu'un texte d'erreur devient du contexte conversationnel.

## Liens

- Session précédente : [[s10-system-prompt]]
- Session suivante : [[s12-task-system]]
- Sessions liées : [[s08-context-compact]] (le compact réactif original, avec résumé LLM), [[s09-memory]] (pipeline complet dont s11 est le filet de sécurité), [[s01-agent-loop]] (la boucle nue que s11 blinde)

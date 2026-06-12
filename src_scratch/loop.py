"""loop.py — LA boucle d'agent unique du harness.

Fusionne : boucle perception-action (s01), streaming (s13), permissions (s15),
hooks pre/post_tool (s16), exécution parallèle (s18), interruptions Ctrl+C (s19)
et prompt caching + stats (s20). Le SDK anthropic est synchrone : chaque appel
streamé est déporté dans un thread via asyncio.to_thread (pattern s18/s20).
"""
import asyncio
import copy
import queue as _queue
import signal
import time

from core import client, MODEL, DEFAULT_SYSTEM, check_permission, drain_queue, emit, paint
from tools import TOOLS, DISPATCH, ASYNC_DISPATCH, drain_notifications


# --- s20 : statistiques de cache ----------------------------------------------

class CacheStats:
    """Comptabilité HIT/MISS depuis response.usage (tolérante aux backends sans cache)."""

    def __init__(self) -> None:
        self.calls = 0    # appels API enregistrés
        self.hits = 0     # tours avec lecture cache
        self.written = 0  # tokens écrits en cache (MISS)
        self.read = 0     # tokens relus depuis le cache (HIT)

    def record(self, usage) -> None:
        """Cumule les compteurs et affiche le verdict du tour, comme s20."""
        self.calls += 1
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.written += written
        self.read += read
        if read:
            self.hits += 1
        if written:  # un tour qui écrit ET lit n'affiche que le MISS (if/elif de s20)
            print(paint(f"  [cache] MISS → {written} tokens écrits en cache", "dim"))
        elif read:
            print(paint(f"  [cache] HIT  → {read} tokens relus (≈{int(read * 0.9)} économisés)", "dim"))

    def summary(self) -> str:
        return (f"[cache] appels={self.calls} hits={self.hits} | écrits={self.written} "
                f"| relus={self.read} | économie ≈{int(self.read * 0.9)} tokens")


CACHE = CacheStats()


# --- s19 : interruptions Ctrl+C -------------------------------------------------

class Interrupts:
    """Ctrl+C portable via signal.signal (asyncio.add_signal_handler n'existe pas
    sous Windows). 1er Ctrl+C : collecte une instruction utilisateur et la met en
    file pour le tour suivant ; 2 Ctrl+C en moins de 2 s : KeyboardInterrupt normal.
    """

    def __init__(self) -> None:
        self._queue: _queue.Queue = _queue.Queue()
        self._last = 0.0

    def install(self) -> None:
        """Pose le handler SIGINT (à appeler une fois, depuis le thread principal)."""
        signal.signal(signal.SIGINT, self._handler)

    def _handler(self, signum, frame):
        now = time.monotonic()
        if now - self._last < 2.0:
            raise KeyboardInterrupt  # double Ctrl+C rapproché = sortie
        self._last = now
        try:
            text = input(paint("\n[interrupt] instruction (vide = pause) > ", "red")).strip()
        except (EOFError, RuntimeError, KeyboardInterrupt):
            text = ""
        self._queue.put("[INTERRUPT] " + (text or
            "L'utilisateur a appuyé sur Ctrl+C. Stoppe ta séquence en cours, "
            "résume ton avancement et attends ses instructions."))

    def drain(self) -> list[str]:
        """Vide la file d'interruptions sans bloquer."""
        return drain_queue(self._queue)


INTERRUPTS = Interrupts()


# --- Gardes communes (hooks s16 + permissions s15) ------------------------------

def _precheck(block, permissions: bool, hooks: bool) -> str | None:
    """Affiche l'appel, applique veto de hook puis permission.
    Renvoie le tool_result pré-fabriqué si bloqué, None si l'exécution peut partir."""
    first = str(next(iter(block.input.values()), "")) if block.input else ""
    print(paint(f"[{block.name}] {first[:80]}", "yellow"))
    if hooks and not emit("pre_tool", {"tool": block.name, "input": block.input}):
        return "Blocked by hook"
    if permissions:
        # Jugement sur la PREMIÈRE valeur de l'input (sémantique s15) : c'est elle que
        # visent les motifs ancrés du config.yaml (^ls, ^rm…) — la repr du dict complet
        # commencerait par "{" et ne matcherait jamais.
        ok, reason = check_permission(block.name, first)
        if not ok:
            return reason if reason.startswith("Denied") else f"Denied: {reason}"
    return None


def _finish(block, output: str, hooks: bool) -> dict:
    """Affiche l'extrait de sortie, émet post_tool, fabrique le tool_result."""
    print(str(output)[:300])
    if hooks:
        emit("post_tool", {"tool": block.name, "input": block.input, "output": output})
    return {"type": "tool_result", "tool_use_id": block.id, "content": str(output)}


async def dispatch_tools_async(content, dispatch=None, permissions=True, hooks=True) -> list[dict]:
    """Exécute les tool_use d'une réponse : gardes séquentielles (les prompts
    ask_user ne se parallélisent pas) puis asyncio.gather sur les handlers
    autorisés (s18). Une exception de handler devient un tool_result Error —
    elle ne fait jamais tomber le lot."""
    dispatch = dispatch or ASYNC_DISPATCH
    blocks = [b for b in content if b.type == "tool_use"]
    outputs: dict[str, str] = {}
    runnable = []
    for b in blocks:
        blocked = _precheck(b, permissions, hooks)
        if blocked is not None:
            outputs[b.id] = blocked
        else:
            runnable.append(b)

    async def _run(b):
        handler = dispatch.get(b.name)
        if handler is None:
            return f"Error: Unknown tool '{b.name}'"
        try:
            return str(await handler(b.input))
        except Exception as e:
            return f"Error: {e}"

    for b, out in zip(runnable, await asyncio.gather(*(_run(b) for b in runnable))):
        outputs[b.id] = out
    return [_finish(b, outputs[b.id], hooks) for b in blocks]


def dispatch_tools(content, dispatch=None, permissions=True, hooks=True) -> list[dict]:
    """Équivalent séquentiel synchrone de dispatch_tools_async (mêmes gardes)."""
    dispatch = dispatch or DISPATCH
    results = []
    for b in (b for b in content if b.type == "tool_use"):
        output = _precheck(b, permissions, hooks)
        if output is None:
            handler = dispatch.get(b.name)
            if handler is None:
                output = f"Error: Unknown tool '{b.name}'"
            else:
                try:
                    output = str(handler(b.input))
                except Exception as e:
                    output = f"Error: {e}"
        results.append(_finish(b, output, hooks))
    return results


# --- Appel API streamé (s13 + s20) ----------------------------------------------

async def stream_turn(messages, tools, system, cache=True, extra_kwargs=None):
    """UN appel API streamé ; renvoie le Message final.

    Streaming du SDK synchrone encapsulé via asyncio.to_thread — l'event loop
    reste libre pendant la génération (condition des interrupts s19).
    cache=True : stratégie exacte de s20 — system converti en liste de blocs avec
    cache_control ephemeral sur le dernier, deepcopy des tools avec marqueur sur
    le dernier outil (on ne mute jamais l'objet partagé) ; CACHE.record(usage).
    """
    extra_kwargs = extra_kwargs or {}
    if cache:
        if isinstance(system, str):
            system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if tools:
            tools = copy.deepcopy(tools)
            tools[-1]["cache_control"] = {"type": "ephemeral"}

    def _blocking_stream():
        with client.messages.stream(model=MODEL, system=system, messages=messages,
                                    tools=tools, max_tokens=8000, **extra_kwargs) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
            return stream.get_final_message()

    print(paint("\n> Réflexion...", "cyan"))
    response = await asyncio.to_thread(_blocking_stream)
    print()
    if cache and hasattr(response, "usage"):
        CACHE.record(response.usage)
    return response


# --- La boucle ------------------------------------------------------------------

def _inject_user(messages: list, texts: list[str]) -> None:
    """Injecte des textes côté user en bloc complet — FIX(mekicode) s19 : jamais
    à cheval sur un échange tool_use/tool_result. Si le dernier message est déjà
    user (requête initiale ou tool_results), on y ajoute des blocs texte pour
    préserver l'alternance des rôles ; sinon nouveau message user."""
    if not texts:
        return
    blocks = [{"type": "text", "text": t} for t in texts]
    if messages and messages[-1]["role"] == "user":
        prev = messages[-1]["content"]
        if isinstance(prev, str):
            prev = [{"type": "text", "text": prev}]
        messages[-1]["content"] = list(prev) + blocks
    else:
        messages.append({"role": "user", "content": blocks})


async def agent_loop_async(messages, tools=None, dispatch=None, system=None,
                           parallel=True, cache=True):
    """Boucle perception-action complète. Mute `messages` en place et renvoie la
    réponse finale (stop_reason != tool_use). En tête de chaque tour, injecte les
    notifications de fond (s08) et les interruptions (s19) comme contenu user."""
    tools = tools if tools is not None else TOOLS
    if dispatch is None:
        dispatch = ASYNC_DISPATCH if parallel else DISPATCH
    system = system or DEFAULT_SYSTEM
    while True:
        pending = [f"[notification] {n}" for n in drain_notifications()] + INTERRUPTS.drain()
        _inject_user(messages, pending)
        response = await stream_turn(messages, tools, system, cache=cache)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return response
        if parallel:
            results = await dispatch_tools_async(response.content, dispatch)
        else:
            results = dispatch_tools(response.content, dispatch)
        messages.append({"role": "user", "content": results})


def agent_loop(messages, **kw):
    """Façade synchrone : asyncio.run — utilisable depuis un thread (équipiers, workers)."""
    return asyncio.run(agent_loop_async(messages, **kw))

"""smoke_mekicore_hooks.py — HookBus de mekicore (pre_tool vetoable / post_tool).

Réseau-free, sans clé API. Lancer : python tests/smoke_mekicore_hooks.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekicore"))

from hooks import HookBus  # noqa: E402


class _Resp:
    def __init__(self, tool_calls, finish):
        self.message = {"role": "assistant", "content": ""}
        self.text = ""
        self.finish_reason = finish
        self.tool_calls = tool_calls


class _TC:
    def __init__(self, id, name, args):
        self.id, self.name, self.arguments = id, name, args


def _two_step_llm(tool_name, args):
    """LLM factice : 1er tour → un appel d'outil ; tours suivants → stop."""
    class _LLM:
        def __init__(self):
            self.n = 0

        def complete(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                return _Resp([_TC("1", tool_name, args)], "tool_calls")
            return _Resp([], "stop")
    return _LLM()


def test_post_tool_notify_runs_all():
    bus = HookBus()
    seen = []
    bus.on("post_tool", lambda p: seen.append(("a", p["tool"])))
    bus.on("post_tool", lambda p: seen.append(("b", p["tool"])))
    bus.emit_post_tool("bash", {"command": "ls"}, "out")
    assert seen == [("a", "bash"), ("b", "bash")]


def test_pre_tool_allows_when_no_subscriber():
    bus = HookBus()
    assert bus.emit_pre_tool("bash", {"command": "ls"}) is None


def test_pre_tool_deny_short_circuits():
    bus = HookBus()
    calls = []
    bus.on("pre_tool", lambda p: calls.append(1) or "Denied: nope")
    bus.on("pre_tool", lambda p: calls.append(2) or None)
    reason = bus.emit_pre_tool("bash", {"command": "rm -rf /"})
    assert reason == "Denied: nope"
    assert calls == [1]  # 2e abonné jamais appelé (court-circuit)


def test_pre_tool_subscriber_exception_is_ignored():
    bus = HookBus()

    def boom(_p):
        raise RuntimeError("x")

    bus.on("pre_tool", boom)
    assert bus.emit_pre_tool("read", {"path": "a"}) is None


def test_run_agent_pre_tool_veto_blocks_handler():
    from base import run_agent
    from events import RunFinished, ToolFinished

    executed = []
    dispatch = {"bash": lambda a: executed.append(a) or "ran"}
    bus = HookBus()
    bus.on("pre_tool", lambda p: "Denied: policy" if "rm -rf" in str(p["input"]) else None)

    events = list(run_agent([], _two_step_llm("bash", {"command": "rm -rf /"}), [], dispatch, hooks=bus))
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert executed == [], "handler ne doit pas être appelé quand pre_tool refuse"
    assert finished and "Denied: policy" in finished[0].output
    assert any(isinstance(e, RunFinished) for e in events)


def test_run_agent_post_tool_notified_on_allow():
    from base import run_agent

    posts = []
    bus = HookBus()
    bus.on("post_tool", lambda p: posts.append((p["tool"], p["output"])))
    list(run_agent([], _two_step_llm("read", {"path": "a.txt"}), [], {"read": lambda a: "contenu"}, hooks=bus))
    assert posts == [("read", "contenu")]


def main():
    test_post_tool_notify_runs_all()
    test_pre_tool_allows_when_no_subscriber()
    test_pre_tool_deny_short_circuits()
    test_pre_tool_subscriber_exception_is_ignored()
    test_run_agent_pre_tool_veto_blocks_handler()
    test_run_agent_post_tool_notified_on_allow()
    print("OK smoke_mekicore_hooks")


if __name__ == "__main__":
    main()

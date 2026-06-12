"""smoke_packages.py — non-régression réseau-free de packages/ (mekillm + mekicore).

Aucune dépendance réseau ni clé API : on stubbe la réponse SDK et le provider.
Lancer depuis la racine du projet : python tests/smoke_packages.py
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent      # racine du projet (tests/ → ..)
PKG = ROOT / "packages"
sys.path.insert(0, str(PKG))                        # packages/         → import mekillm
sys.path.insert(0, str(PKG / "mekicore"))           # packages/mekicore → import base, tools

import mekillm  # noqa: E402
from mekillm import Usage  # noqa: E402
from mekillm import observability as observe  # noqa: E402
from mekillm.client import LLMResponse, ToolCall, _normalize  # noqa: E402

import base  # noqa: E402
import tools  # noqa: E402


def test_normalize_text():
    resp = NS(
        choices=[NS(message=NS(content="hi", tool_calls=None), finish_reason="stop")],
        usage=NS(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    out = _normalize(resp)
    assert out.text == "hi"
    assert out.tool_calls == []
    assert out.finish_reason == "stop"
    assert out.usage.total_tokens == 15
    assert out.message == {"role": "assistant", "content": "hi"}


def test_normalize_tool_call():
    tc = NS(id="call_1", function=NS(name="bash", arguments='{"command": "ls"}'))
    resp = NS(
        choices=[NS(message=NS(content=None, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=None,
    )
    out = _normalize(resp)
    assert out.tool_calls[0].name == "bash"
    assert out.tool_calls[0].arguments == {"command": "ls"}
    assert out.finish_reason == "tool_calls"
    assert out.usage.total_tokens == 0
    assert out.message["tool_calls"][0]["function"]["name"] == "bash"


def test_normalize_bad_json_args():
    tc = NS(id="c", function=NS(name="bash", arguments="{not json"))
    resp = NS(
        choices=[NS(message=NS(content=None, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=None,
    )
    out = _normalize(resp)
    assert out.tool_calls[0].arguments == {}  # JSON invalide → dict vide, pas de crash


def test_observability_hook_and_jsonl(log_path):
    seen = []
    observe.add_hook(seen.append)
    rec = observe.CallRecord(
        ts="t", provider="p", model="m", latency_ms=1,
        prompt_tokens=1, completion_tokens=2, total_tokens=3,
        finish_reason="stop", status="ok",
    )
    observe.emit(rec)
    assert seen and seen[0].model == "m"
    assert log_path.exists()
    assert '"model": "m"' in log_path.read_text(encoding="utf-8")


def test_run_bash():
    assert "hello" in tools.run_bash("echo hello")
    assert tools.run_bash("sudo rm") == "Error: dangerous command blocked"


def test_dispatch_tools():
    tc = ToolCall(id="c1", name="bash", arguments={"command": "echo hi"})
    msgs = base.dispatch_tools([tc], tools.DISPATCH)
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "c1"
    assert "hi" in msgs[0]["content"]


def test_dispatch_unknown_tool():
    tc = ToolCall(id="c2", name="nope", arguments={})
    msgs = base.dispatch_tools([tc], tools.DISPATCH)
    assert "Unknown tool" in msgs[0]["content"]


def test_agent_loop_with_stub():
    seq = [
        LLMResponse(
            text="", tool_calls=[ToolCall("c1", "bash", {"command": "echo hi"})],
            finish_reason="tool_calls", usage=Usage(),
            message={"role": "assistant", "content": ""},
        ),
        LLMResponse(
            text="done", tool_calls=[], finish_reason="stop", usage=Usage(),
            message={"role": "assistant", "content": "done"},
        ),
    ]

    class StubLLM:
        def __init__(self):
            self.i = 0

        def complete(self, messages, tools=None):
            r = seq[self.i]
            self.i += 1
            return r

    messages = [{"role": "user", "content": "go"}]
    base.agent_loop(messages, StubLLM(), tools.TOOLS, tools.DISPATCH)
    assert messages[-1]["content"] == "done"
    assert any(m.get("role") == "tool" for m in messages)


def test_run_agent_events():
    seq = [
        LLMResponse(
            text="", tool_calls=[ToolCall("c1", "bash", {"command": "echo hi"})],
            finish_reason="tool_calls", usage=Usage(),
            message={"role": "assistant", "content": ""},
        ),
        LLMResponse(
            text="fini", tool_calls=[], finish_reason="stop", usage=Usage(),
            message={"role": "assistant", "content": "fini"},
        ),
    ]

    class StubLLM:
        def __init__(self):
            self.i = 0

        def complete(self, messages, tools=None):
            r = seq[self.i]
            self.i += 1
            return r

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, StubLLM(), tools.TOOLS, tools.DISPATCH))
    assert [type(e).__name__ for e in evs] == [
        "ThinkingStarted", "ToolStarted", "ToolFinished",
        "ThinkingStarted", "AssistantDone", "RunFinished",
    ]
    assert evs[1].name == "bash" and evs[1].args == {"command": "echo hi"}
    assert "hi" in evs[2].output
    assert evs[4].text == "fini"
    assert any(m.get("role") == "tool" and "hi" in m["content"] for m in msgs)
    assert msgs[-1]["content"] == "fini"


def test_run_agent_error():
    class BoomLLM:
        def complete(self, messages, tools=None):
            raise RuntimeError("boom")

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, BoomLLM(), tools.TOOLS, tools.DISPATCH))
    assert [type(e).__name__ for e in evs] == ["ThinkingStarted", "RunError"]
    assert "boom" in evs[1].message


def test_run_agent_unknown_tool():
    seq = [
        LLMResponse(text="", tool_calls=[ToolCall("c1", "nope", {})],
                    finish_reason="tool_calls", usage=Usage(),
                    message={"role": "assistant", "content": ""}),
        LLMResponse(text="ok", tool_calls=[], finish_reason="stop", usage=Usage(),
                    message={"role": "assistant", "content": "ok"}),
    ]

    class StubLLM:
        def __init__(self):
            self.i = 0

        def complete(self, messages, tools=None):
            r = seq[self.i]
            self.i += 1
            return r

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, StubLLM(), tools.TOOLS, tools.DISPATCH))
    finished = [e for e in evs if type(e).__name__ == "ToolFinished"]
    assert finished and "Unknown tool" in finished[0].output
    assert any(m.get("role") == "tool" and "Unknown tool" in m["content"] for m in msgs)


def test_run_agent_empty_tool_calls():
    bad = LLMResponse(text="", tool_calls=[], finish_reason="tool_calls", usage=Usage(),
                      message={"role": "assistant", "content": ""})

    class StubLLM:
        def complete(self, messages, tools=None):
            return bad

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, StubLLM(), tools.TOOLS, tools.DISPATCH))
    assert [type(e).__name__ for e in evs] == ["ThinkingStarted", "RunError"]
    assert "tool_calls vide" in evs[1].message


def main():
    log_path = Path(tempfile.gettempdir()) / "mekillm_smoke.jsonl"
    if log_path.exists():
        log_path.unlink()
    os.environ["MEKILLM_LOG_FILE"] = str(log_path)

    test_normalize_text()
    test_normalize_tool_call()
    test_normalize_bad_json_args()
    test_observability_hook_and_jsonl(log_path)
    test_run_bash()
    test_dispatch_tools()
    test_dispatch_unknown_tool()
    test_agent_loop_with_stub()
    test_run_agent_events()
    test_run_agent_error()
    test_run_agent_unknown_tool()
    test_run_agent_empty_tool_calls()
    print("OK - tous les smoke tests passent")


if __name__ == "__main__":
    main()

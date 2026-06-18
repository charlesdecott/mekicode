"""smoke_packages.py — non-régression réseau-free de packages/ (mekillm + mekicore).

Aucune dépendance réseau ni clé API : on stubbe la réponse SDK et le provider.
Lancer depuis la racine du projet : python tests/smoke_packages.py
"""
import contextlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packages"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "mekicore"))

import mekillm  # noqa: E402
from mekillm import Usage  # noqa: E402
from mekillm import observability as observe  # noqa: E402
from mekillm.client import LLMResponse, ToolCall, _normalize  # noqa: E402

import base  # noqa: E402
import tools  # noqa: E402


@contextlib.contextmanager
def _ws(d):
    """Pointe MEKICORE_WORKSPACE sur d le temps du bloc (restauré ensuite)."""
    old = os.environ.get("MEKICORE_WORKSPACE")
    os.environ["MEKICORE_WORKSPACE"] = str(d)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MEKICORE_WORKSPACE", None)
        else:
            os.environ["MEKICORE_WORKSPACE"] = old


def seq_llm(seq):
    """LLM factice rejouant `seq` (liste de LLMResponse) un élément par appel de complete()."""
    class _Stub:
        def __init__(self):
            self.i = 0

        def complete(self, messages, tools=None):
            r = seq[self.i]
            self.i += 1
            return r
    return _Stub()


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

    messages = [{"role": "user", "content": "go"}]
    base.agent_loop(messages, seq_llm(seq), tools.TOOLS, tools.DISPATCH)
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

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, seq_llm(seq), tools.TOOLS, tools.DISPATCH))
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

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, seq_llm(seq), tools.TOOLS, tools.DISPATCH))
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


def _drain(gen):
    """Itère gen jusqu'au bout ; mémorise la valeur de return dans _drain.value."""
    try:
        while True:
            yield next(gen)
    except StopIteration as stop:
        _drain.value = stop.value


def test_consume_stream_text():
    from mekillm.client import _consume_stream
    chunks = [
        NS(choices=[NS(delta=NS(content="Bon", tool_calls=None), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content="jour", tool_calls=None), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="stop")], usage=None),
    ]
    tokens = list(_drain(_consume_stream(iter(chunks))))
    resp = _drain.value
    assert tokens == ["Bon", "jour"]
    assert resp.text == "Bonjour"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []
    assert resp.message == {"role": "assistant", "content": "Bonjour"}


def test_consume_stream_tool_call():
    from mekillm.client import _consume_stream
    chunks = [
        NS(choices=[NS(delta=NS(content=None, tool_calls=[
            NS(index=0, id="call_1", function=NS(name="bash", arguments='{"comm'))]), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=[
            NS(index=0, id=None, function=NS(name=None, arguments='and": "ls"}'))]), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="tool_calls")], usage=None),
    ]
    gen = _consume_stream(iter(chunks))
    tokens = list(_drain(gen))
    resp = _drain.value
    assert tokens == []
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "call_1"
    assert resp.tool_calls[0].name == "bash"
    assert resp.tool_calls[0].arguments == {"command": "ls"}
    assert resp.message["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'


def test_consume_stream_empty():
    from mekillm.client import _consume_stream
    tokens = list(_drain(_consume_stream(iter([]))))
    resp = _drain.value
    assert tokens == []
    assert resp.text == "" and resp.tool_calls == [] and resp.finish_reason == ""
    assert resp.message == {"role": "assistant", "content": ""}


def test_consume_stream_text_then_tool():
    from mekillm.client import _consume_stream
    chunks = [
        NS(choices=[NS(delta=NS(content="ok ", tool_calls=None), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=[
            NS(index=0, id="c1", function=NS(name="bash", arguments='{"command": "ls"}'))]), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="tool_calls")], usage=None),
    ]
    tokens = list(_drain(_consume_stream(iter(chunks))))
    resp = _drain.value
    assert tokens == ["ok "]
    assert resp.text == "ok "
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].arguments == {"command": "ls"}


def test_run_agent_streaming():
    class StubLLM:
        model = "stub"

        def stream(self, messages, tools=None):
            for t in ["Sa", "lut"]:
                yield t
            return LLMResponse(
                text="Salut", tool_calls=[], finish_reason="stop", usage=Usage(),
                message={"role": "assistant", "content": "Salut"},
            )

    msgs = [{"role": "user", "content": "hi"}]
    evs = list(base.run_agent(msgs, StubLLM(), tools.TOOLS, tools.DISPATCH, stream=True))
    assert [type(e).__name__ for e in evs] == [
        "ThinkingStarted", "AssistantDelta", "AssistantDelta", "AssistantDone", "RunFinished",
    ]
    assert evs[1].text == "Sa" and evs[2].text == "lut"
    assert evs[3].text == "Salut"
    assert msgs[-1]["content"] == "Salut"


def test_llm_wrappers_stub():
    # instance LLM sans __init__ (pas de clé requise) + client SDK stubé
    llm = mekillm.LLM.__new__(mekillm.LLM)
    llm.model = "stub-model"
    sdk_resp = NS(
        choices=[NS(message=NS(content="ok", tool_calls=None), finish_reason="stop")],
        usage=NS(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )
    chunks = [NS(choices=[NS(delta=NS(content="ok", tool_calls=None), finish_reason="stop")], usage=None)]

    class _Completions:
        def create(self, **params):
            return chunks if params.get("stream") else sdk_resp

    llm._client = NS(chat=NS(completions=_Completions()))

    seen = []
    observe.add_hook(seen.append)

    out = llm.complete([{"role": "user", "content": "hi"}])
    assert out.text == "ok" and out.finish_reason == "stop" and out.usage.total_tokens == 3

    toks = list(_drain(llm.stream([{"role": "user", "content": "hi"}])))
    sout = _drain.value
    assert toks == ["ok"] and sout.text == "ok" and sout.finish_reason == "stop"

    assert len([r for r in seen if r.model == "stub-model"]) == 2


def test_is_transient_classification():
    from mekillm.client import _is_transient
    assert _is_transient(RuntimeError("JSON error injected into SSE stream"))
    assert _is_transient(Exception("Provider returned error: overloaded"))
    assert _is_transient(Exception("HTTP 429 rate limit exceeded"))
    assert not _is_transient(ValueError("invalid model name"))
    assert not _is_transient(Exception("bad request: messages required"))


def test_stream_retries_on_transient_error():
    """stream() retente sur une erreur transitoire puis réussit (tokens de la tentative réussie)."""
    llm = mekillm.LLM.__new__(mekillm.LLM)
    llm.model = "stub-model"
    good = [NS(choices=[NS(delta=NS(content="hello", tool_calls=None), finish_reason=None)], usage=None),
            NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="stop")], usage=None)]

    class _Flaky:
        calls = 0
        def create(self, **params):
            type(self).calls += 1
            if self.calls == 1:
                raise RuntimeError("JSON error injected into SSE stream")
            return iter(good)

    llm._client = NS(chat=NS(completions=_Flaky()))
    os.environ["MEKILLM_RETRIES"] = "2"
    try:
        toks = list(_drain(llm.stream([{"role": "user", "content": "hi"}])))
    finally:
        os.environ.pop("MEKILLM_RETRIES", None)
    resp = _drain.value
    assert _Flaky.calls == 2                      # 1 échec transitoire + 1 succès
    assert toks == ["hello"] and resp.text == "hello" and resp.finish_reason == "stop"


def test_stream_no_retry_on_permanent_error():
    """Une erreur NON transitoire (faute de requête) n'est pas retentée."""
    llm = mekillm.LLM.__new__(mekillm.LLM)
    llm.model = "stub-model"

    class _Bad:
        calls = 0
        def create(self, **params):
            type(self).calls += 1
            raise ValueError("invalid request: bad messages")

    llm._client = NS(chat=NS(completions=_Bad()))
    try:
        list(_drain(llm.stream([{"role": "user", "content": "hi"}])))
        assert False, "devait lever"
    except ValueError:
        pass
    assert _Bad.calls == 1                        # pas de retry sur erreur permanente


def test_safe_path_confine():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        root = Path(d).resolve()
        assert tools._safe_path("a/b.txt") == root / "a" / "b.txt"
        assert tools._safe_path(".") == root
        for bad in ["../escape.txt", "../../etc/passwd"]:
            try:
                tools._safe_path(bad)
                assert False, f"aurait dû refuser {bad}"
            except ValueError:
                pass


def test_write_read_roundtrip():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        assert tools.write_file("sub/a.txt", "café ☕").startswith("écrit")
        assert (Path(d) / "sub" / "a.txt").is_file()
        assert tools.read_file("sub/a.txt") == "café ☕"
        assert tools.read_file("absent.txt").startswith("Error")
        assert tools.write_file("../escape.txt", "x").startswith("Error")     # confiné (hors du workspace)
        assert tools.write_file("bad\x00name.txt", "x").startswith("Error")  # null byte → Error, pas de crash


def test_edit_unique_and_ambiguous():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        tools.write_file("f.py", "a = 1\nb = 2\na = 1\n")
        assert tools.edit_file("f.py", "b = 2", "b = 3") == "édité f.py"
        assert tools.read_file("f.py") == "a = 1\nb = 3\na = 1\n"
        assert tools.edit_file("f.py", "a = 1", "a = 9").startswith("Error")  # 2 occurrences → ambigu
        assert tools.edit_file("f.py", "zzz", "x").startswith("Error")
        (Path(d) / "bin.dat").write_bytes(b"\xff\xfe\x00binary")
        assert tools.edit_file("bin.dat", "x", "y").startswith("Error")   # non-UTF-8 → Error, pas de crash


def test_grep_and_glob():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        tools.write_file("pkg/a.py", "import os\ndef hello():\n    return 42\n")
        tools.write_file("pkg/b.py", "x = 1\n")
        tools.write_file("notes.txt", "rien\n")
        g = tools.grep_files(r"def \w+", "pkg").replace("\\", "/")
        assert "a.py:2" in g and "def hello" in g
        assert tools.grep_files("zzznope", ".") == "(aucun résultat)"
        assert tools.grep_files("(", ".").startswith("Error")
        files = tools.glob_files("pkg/*.py").replace("\\", "/")
        assert "pkg/a.py" in files and "pkg/b.py" in files and "notes.txt" not in files
        assert tools.glob_files("**/*.py").count("\n") >= 1            # récursif
        assert tools.glob_files("../*") == "(aucun fichier)"   # confinement : pas de fuite hors workspace
        assert tools.grep_files("x", "bad\x00dir").startswith("Error")  # null byte → Error, pas de crash


def test_tools_registered():
    names = {t["function"]["name"] for t in tools.TOOLS}
    assert names == {"bash", "read", "write", "edit", "grep", "glob"}
    assert set(tools.DISPATCH) == names
    with tempfile.TemporaryDirectory() as d, _ws(d):
        assert tools.DISPATCH["write"]({"path": "x.txt", "content": "hi"}).startswith("écrit")
        assert tools.DISPATCH["read"]({"path": "x.txt"}) == "hi"
        assert tools.DISPATCH["glob"]({"pattern": "*.txt"}) == "x.txt"


def test_make_dispatch_confines_to_workspace():
    import tempfile, os
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "packages" / "mekicore"))
    import tools
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        (Path(a) / "x.txt").write_text("dans_A", encoding="utf-8")
        (Path(b) / "x.txt").write_text("dans_B", encoding="utf-8")
        da = tools.make_dispatch(Path(a))
        db = tools.make_dispatch(Path(b))
        assert da["read"]({"path": "x.txt"}) == "dans_A"
        assert db["read"]({"path": "x.txt"}) == "dans_B"          # pas de fuite entre workspaces
        assert "hors du workspace" in da["read"]({"path": "../x.txt"})  # confinement
        out = da["bash"]({"command": "pwd"})
        assert os.path.basename(a) in out                          # bash s'exécute dans le workspace


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
    test_consume_stream_text()
    test_consume_stream_tool_call()
    test_consume_stream_empty()
    test_consume_stream_text_then_tool()
    test_run_agent_streaming()
    test_llm_wrappers_stub()
    test_is_transient_classification()
    test_stream_retries_on_transient_error()
    test_stream_no_retry_on_permanent_error()
    test_safe_path_confine()
    test_write_read_roundtrip()
    test_edit_unique_and_ambiguous()
    test_grep_and_glob()
    test_tools_registered()
    test_make_dispatch_confines_to_workspace()
    print("OK - tous les smoke tests passent")


if __name__ == "__main__":
    main()

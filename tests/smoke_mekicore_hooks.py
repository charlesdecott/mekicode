"""smoke_mekicore_hooks.py — HookBus de mekicore (pre_tool vetoable / post_tool).

Réseau-free, sans clé API. Lancer : python tests/smoke_mekicore_hooks.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekicore"))

from hooks import HookBus  # noqa: E402


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


def main():
    test_post_tool_notify_runs_all()
    test_pre_tool_allows_when_no_subscriber()
    test_pre_tool_deny_short_circuits()
    test_pre_tool_subscriber_exception_is_ignored()
    print("OK smoke_mekicore_hooks")


if __name__ == "__main__":
    main()

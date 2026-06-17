"""smoke_permissions.py — moteur de permissions s15 (3 tiers + couches) + store projet.

Réseau-free, sans clé API. Lancer : python tests/smoke_permissions.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekicore"))
sys.path.insert(0, str(ROOT / "packages"))

from permissions import (  # noqa: E402
    ALLOW, ASK, DENY, check_permission, load_rules,
)

RULES = {
    "always_deny": [{"pattern": r"rm\s+-rf\s+/", "reason": "root"}],
    "always_allow": [{"pattern": r"^ls( |$)", "reason": "ls"}],
    "ask_user": [{"pattern": r"^rm ", "reason": "del"}],
}


def test_deny_wins():
    d = check_permission("bash", "rm -rf /", RULES)
    assert d.kind == DENY and "root" in d.reason


def test_allow():
    assert check_permission("bash", "ls -la", RULES).kind == ALLOW


def test_ask():
    d = check_permission("bash", "rm foo.txt", RULES)
    assert d.kind == ASK and "del" in d.reason


def test_default_allow():
    assert check_permission("bash", "echo hi", RULES).kind == ALLOW


def test_session_override_promotes_to_allow():
    overrides = {"always_allow": [{"pattern": r"^rm ", "reason": "ok session"}]}
    d = check_permission("bash", "rm foo.txt", RULES, overrides=overrides)
    assert d.kind == ALLOW


def test_project_override_blacklist():
    overrides = {"always_deny": [{"pattern": r"^git push", "reason": "no push"}]}
    d = check_permission("bash", "git push origin main", RULES, overrides=overrides)
    assert d.kind == DENY and "no push" in d.reason


def test_load_rules_from_yaml():
    rules = load_rules()
    assert "always_deny" in rules and "ask_user" in rules


def test_project_permissions_roundtrip():
    tmp = ROOT / ".mekicode-test-perms"
    shutil.rmtree(tmp, ignore_errors=True)
    from mekihub.permissions_store import add_project_rule, load_project_overrides
    add_project_rule("proj1", "always_allow", r"^git push", "ok", base_dir=tmp)
    ov = load_project_overrides("proj1", base_dir=tmp)
    assert any(r["pattern"] == r"^git push" for r in ov["always_allow"])
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    for fn in (
        test_deny_wins, test_allow, test_ask, test_default_allow,
        test_session_override_promotes_to_allow, test_project_override_blacklist,
        test_load_rules_from_yaml, test_project_permissions_roundtrip,
    ):
        fn()
    print("OK smoke_permissions")


if __name__ == "__main__":
    main()

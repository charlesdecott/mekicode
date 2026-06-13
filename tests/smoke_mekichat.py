"""smoke_mekichat.py — non-régression réseau-free de packages/mekichat/.

Aucune dépendance réseau, clé API ni NiceGUI : on ne teste que la persistance pure.
Lancer depuis la racine : python tests/smoke_mekichat.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekichat"))  # import sessions
sys.path.insert(0, str(ROOT / "packages"))               # import mekihub

import sessions as S  # noqa: E402


def test_create_and_load():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="gpt-4o-mini", system="sys prompt")
        assert s.id
        assert s.messages[0] == {"role": "system", "content": "sys prompt"}
        loaded = store.load(s.id)
        assert loaded.id == s.id
        assert loaded.model == "gpt-4o-mini"
        assert loaded.messages == s.messages


def test_title_set_from_first_user_message():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="m")
        assert s.title == S._DEFAULT_TITLE
        s.add("user", "Liste les fichiers .py\net compte les lignes")
        assert s.title == "Liste les fichiers .py"      # 1re ligne, tronquée
        s.add("user", "deuxième")
        assert s.title == "Liste les fichiers .py"      # ne change plus ensuite


def test_round_trip_messages():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="m")
        s.add("user", "salut")
        s.add("assistant", "bonjour")
        store.save(s)
        loaded = store.load(s.id)
        assert [m["content"] for m in loaded.messages] == ["salut", "bonjour"]


def test_list_sorted_recent_first():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        a = store.create(model="m")
        a.created_at = "2026-01-01T00:00:00+00:00"; store.save(a)
        b = store.create(model="m")
        b.created_at = "2026-06-01T00:00:00+00:00"; store.save(b)
        metas = store.list()
        assert [m.id for m in metas] == [b.id, a.id]
        assert metas[0].n_messages == len(b.messages)


def test_list_ignores_bad_files():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        store.create(model="m")
        (Path(d) / "junk.json").write_text("{not json", encoding="utf-8")
        assert len(store.list()) == 1   # le fichier corrompu est ignoré, pas de crash


def test_list_ignores_missing_id_files():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        store.create(model="m")
        # JSON valide mais sans clé "id" → doit être ignoré, pas de crash
        (Path(d) / "noid.json").write_text('{"title": "x", "messages": []}', encoding="utf-8")
        assert len(store.list()) == 1


def test_unicode_round_trip():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="m")
        s.add("user", "café ☕ déjà — émojis 🤖")
        store.save(s)
        loaded = store.load(s.id)
        assert loaded.messages[-1]["content"] == "café ☕ déjà — émojis 🤖"


def test_delete():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        a = store.create(model="m")
        b = store.create(model="m")
        store.delete(a.id)
        assert [m.id for m in store.list()] == [b.id]   # a supprimée, b reste
        store.delete("inexistante")                     # pas d'erreur si absente


def test_sessions_reexport_from_mekihub():
    """Vérifie que sessions.py est un ré-export de mekihub.session (même classe, pas une copie)."""
    import sessions as chat_sessions
    from mekihub import session as hub_session
    assert chat_sessions.SessionStore is hub_session.SessionStore   # même classe (ré-export)


def main():
    test_create_and_load()
    test_title_set_from_first_user_message()
    test_round_trip_messages()
    test_list_sorted_recent_first()
    test_list_ignores_bad_files()
    test_list_ignores_missing_id_files()
    test_unicode_round_trip()
    test_delete()
    test_sessions_reexport_from_mekihub()
    print("OK - smoke mekichat passe")


if __name__ == "__main__":
    main()

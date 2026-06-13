import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from mekihub.session import Author, QueueItem, Session, SessionState, SessionStore  # noqa: E402


def test_author_and_queueitem():
    a = Author(id="c1", name="alice", color="#39ff14")
    assert a.name == "alice"
    qi = QueueItem(item_id="q1", author=a, text="salut", ts="2099-01-01T00:00:00+00:00")
    assert qi.author.name == "alice" and qi.text == "salut"


def test_session_authors_separate_from_messages():
    s = Session(id="s1", title="(nouvelle session)", model="m", created_at="2099-01-01T00:00:00+00:00")
    a = Author(id="c1", name="bob", color="#ff2bd6")
    idx = s.add_user("bonjour", author=a)
    assert s.messages[idx] == {"role": "user", "content": "bonjour"}   # OpenAI pur, pas d'auteur
    assert s.authors[idx] == {"name": "bob", "color": "#ff2bd6"}       # attribution séparée


if __name__ == "__main__":
    test_author_and_queueitem()
    test_session_authors_separate_from_messages()
    print("OK - session")

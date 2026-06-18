"""smoke_mekicanvas_fs.py — helpers fs sandboxés du canvas (Sprint 2a).

Réseau-free. Lancer : python tests/smoke_mekicanvas_fs.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekistudio"))

from mekicanvas import fs  # noqa: E402


def test_safe_path_ok_and_escapes():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        assert fs.safe_path(root, "a/b.txt") == (root / "a" / "b.txt").resolve()
        for bad in ("../escape", "../../x", "/etc/passwd", "a/../../x"):
            try:
                fs.safe_path(root, bad)
                assert False, f"doit rejeter {bad}"
            except ValueError:
                pass


def test_list_dir_sorted_and_excludes():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "zsub").mkdir()
        (root / "asub").mkdir()
        (root / "__pycache__").mkdir()
        (root / "b.txt").write_text("x", encoding="utf-8")
        (root / "a.py").write_text("x", encoding="utf-8")
        entries = fs.list_dir(root, "", excludes=["__pycache__"])
        # dossiers d'abord (alpha), puis fichiers (alpha) ; __pycache__ exclu
        assert [e["name"] for e in entries] == ["asub", "zsub", "a.py", "b.txt"]
        assert all(e["kind"] in ("dir", "file") for e in entries)
        assert entries[0]["path"] == "asub" and entries[2]["path"] == "a.py"
        (root / "asub" / "deep.md").write_text("y", encoding="utf-8")
        sub = fs.list_dir(root, "asub")
        assert [e["path"] for e in sub] == ["asub/deep.md"]


def test_read_text_roundtrip_limit_binary():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "f.txt").write_text("héllo\nmonde", encoding="utf-8", newline="")
        assert fs.read_text(root, "f.txt") == "héllo\nmonde"
        (root / "bin.dat").write_bytes(b"\x00\x01\x02\xff")
        try:
            fs.read_text(root, "bin.dat")
            assert False, "doit refuser le binaire"
        except ValueError:
            pass
        (root / "big.txt").write_text("a" * (fs.MAX_BYTES + 10), encoding="utf-8")
        try:
            fs.read_text(root, "big.txt")
            assert False, "doit refuser > MAX_BYTES"
        except ValueError:
            pass


def test_write_text_atomic_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        fs.write_text(root, "sub/new.txt", "contenu\nécrit")
        assert (root / "sub" / "new.txt").read_text(encoding="utf-8") == "contenu\nécrit"
        # pas de fichier .tmp résiduel
        assert not list((root / "sub").glob("*.tmp"))
        fs.write_text(root, "sub/new.txt", "v2")
        assert fs.read_text(root, "sub/new.txt") == "v2"
        try:
            fs.write_text(root, "../evil.txt", "x")
            assert False, "doit rejeter l'échappement"
        except ValueError:
            pass


def main():
    for fn in (test_safe_path_ok_and_escapes, test_list_dir_sorted_and_excludes,
               test_read_text_roundtrip_limit_binary, test_write_text_atomic_roundtrip):
        fn()
    print("OK smoke_mekicanvas_fs")


if __name__ == "__main__":
    main()

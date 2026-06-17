"""smoke_mekicanvas.py — modèle Node/Component, registry/parenting, impulses (purs).

Réseau-free, sans NiceGUI. Lancer : python tests/smoke_mekicanvas.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekistudio"))

from mekicanvas.components.base import HeaderComponent, NodeComponent  # noqa: E402
from mekicanvas.model import CanvasState, Node  # noqa: E402


def test_node_serializes_roundtrip():
    n = Node(kind="kernel", x=1, y=2, root=NodeComponent(children=[HeaderComponent(text="K")]))
    js = n.model_dump_json()
    n2 = Node.model_validate_json(js)
    assert n2.kind == "kernel" and n2.root.children[0].type == "header"
    assert n2.root.children[0].text == "K"


def test_default_canvas_parenting():
    from mekicanvas.registry import default_canvas, reconcile_source_links
    st = reconcile_source_links(default_canvas())
    by_kind = {n.kind: n for n in st.nodes}
    assert by_kind["kernel"].source_id is None
    assert by_kind["chat"].source_id == by_kind["kernel"].id
    assert by_kind["queue"].source_id == by_kind["chat"].id


def test_reconcile_idempotent():
    from mekicanvas.registry import default_canvas, reconcile_source_links
    st = default_canvas()
    a = [(n.kind, n.source_id) for n in reconcile_source_links(st).nodes]
    b = [(n.kind, n.source_id) for n in reconcile_source_links(st).nodes]
    assert a == b


def test_longest_prefix():
    from mekicanvas.parenting import longest_prefix_id
    cands = [("docs", "id1"), ("", "id2"), ("docs/super", "id3")]
    assert longest_prefix_id("docs/super/x.md", cands, strict=False) == "id3"
    assert longest_prefix_id("docs/x.md", cands, strict=False) == "id1"


def test_impulse_read_with_path():
    from mekicanvas.impulses import impulse_for
    it = impulse_for({"type": "tool_result", "name": "read", "file_path": "a/b.py"})
    assert it["kind"] == "comet" and it["target"] == {"by": "file", "value": "a/b.py"}
    assert it["level"] == "strong" and "fallback" in it


def test_impulse_non_read_is_none():
    from mekicanvas.impulses import impulse_for
    assert impulse_for({"type": "tool_result", "name": "write", "file_path": "a"}) is None


def test_impulse_turn_end_and_error():
    from mekicanvas.impulses import impulse_for
    assert impulse_for({"type": "turn_end"})["dismissable"] is True
    assert impulse_for({"type": "tool_result", "is_error": True})["level"] == "error"


def main():
    for fn in (
        test_node_serializes_roundtrip, test_default_canvas_parenting, test_reconcile_idempotent,
        test_longest_prefix, test_impulse_read_with_path, test_impulse_non_read_is_none,
        test_impulse_turn_end_and_error,
    ):
        fn()
    print("OK smoke_mekicanvas")


if __name__ == "__main__":
    main()

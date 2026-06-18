"""component.py — ChatComponent NiceGUI réutilisable.

Le MÊME composant de chat sert dans l'onglet « Chat », dans la node Chat du canvas, et dans le
panneau focus du mode Mix. Encapsule : fil + composer + file + présence + boucle d'abonnement au
hub + rendu des events (17 branches dont PermissionRequested). L'identité `author` est résolue
EN AMONT dans le contexte de page (cf. realtime.author_for_client) et injectée.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

import views


class ChatComponent:
    def __init__(self, container, hub, session_id: str, author, *, on_idle=None):
        self._hub = hub
        self._sid = session_id
        self._author = author
        self._on_idle = on_idle or (lambda: None)
        self._inner = None
        self._thinking = None
        self._stream = {"body": None, "lbl": None, "text": ""}
        self._bars = {"presence": None, "queue": None}
        self._queue_rows: dict = {}
        self._wt_cards: dict = {}
        self._handles: dict = {}
        self._build(container)
        try:
            ui.timer(0.1, self._subscribe_loop, once=True)
        except RuntimeError:
            pass

    def _build(self, container) -> None:
        with container:
            embed = ui.element("div").classes("chat-embed")
            with embed:
                with ui.element("div").classes("presence-row"):
                    self._bars["presence"] = ui.element("div").classes("presence")
                with ui.element("div").classes("thread"):
                    self._inner = ui.element("div").classes("thread-inner")
                    with self._inner:
                        sess = self._hub.store.load(self._sid)
                        views.render_thread(sess.messages, getattr(sess, "authors", None))
                with ui.element("div").classes("queue-bar"):
                    self._bars["queue"] = ui.element("div").classes("queue")
                with ui.element("div").classes("composer"):
                    with ui.element("div").classes("composer-inner"):
                        with ui.element("div").classes("input-wrap"):
                            box = ui.textarea(placeholder="// message à mekicore")
                            box.props("borderless autogrow").classes("ta")

                            async def _flush(_=None) -> None:
                                value = box.value or ""
                                box.set_value("")
                                await self.send(value)

                            async def _on_enter(e) -> None:
                                if not (isinstance(e.args, dict) and e.args.get("shiftKey")):
                                    await _flush()

                            ui.button("▸", on_click=_flush).props("flat").classes("send")
                            box.on("keydown.enter", _on_enter, args=["shiftKey"])

    async def send(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._hub.submit(self._sid, text, author=self._author)

    async def _subscribe_loop(self) -> None:
        self._hub.join(self._sid, self._author)
        try:
            async for event in self._hub.subscribe(self._sid):
                try:
                    self._render_hub_event(event)
                    self._scroll_bottom()
                except RuntimeError as exc:
                    if "deleted" in str(exc):
                        break
                    raise
        finally:
            self._hub.leave(self._sid, self._author)

    def _scroll_bottom(self) -> None:
        try:
            ui.run_javascript("document.querySelectorAll('.thread').forEach(t=>t.scrollTop=t.scrollHeight);")
        except Exception:
            pass

    def _clear_thinking(self) -> None:
        if self._thinking is not None:
            self._thinking.delete()
            self._thinking = None

    def _delete_pending(self, item_id: str) -> None:
        self._hub.delete_pending(self._sid, item_id)

    def _rebuild_queue(self, items) -> None:
        box = self._bars["queue"]
        if box is None:
            return
        box.clear()
        self._queue_rows.clear()
        with box:
            for it in items:
                row = views.render_queue_item(it.item_id, it.author.name, it.author.color,
                                              it.text, self._delete_pending)
                self._queue_rows[it.item_id] = row

    def _set_presence(self, present) -> None:
        box = self._bars["presence"]
        if box is None:
            return
        box.clear()
        with box:
            for a in present:
                ui.label(a.name).classes("pres-chip").style(f"--ac:{a.color}")

    def _render_hub_event(self, event) -> None:
        name = type(event).__name__
        inner = self._inner

        if name == "Snapshot":
            state_ = event.state
            self._queue_rows.clear()
            inner.clear()
            with inner:
                views.render_thread(state_.messages, getattr(state_, "authors", None))
            self._rebuild_queue(getattr(state_, "queue", []) or [])
            self._set_presence(getattr(state_, "presence", []) or [])
            self._stream["body"] = None
            return
        if name == "PresenceChanged":
            self._set_presence(event.present)
            return
        if name == "QueueEnqueued":
            box = self._bars["queue"]
            if box is not None:
                with box:
                    row = views.render_queue_item(event.item_id, event.author_name, event.color,
                                                  event.text, self._delete_pending)
                    self._queue_rows[event.item_id] = row
            return
        if name == "QueueItemDeleted":
            row = self._queue_rows.pop(event.item_id, None)
            if row is not None:
                row.delete()
            return
        if name == "RunStarted":
            row = self._queue_rows.pop(event.item_id, None)
            if row is not None:
                row.delete()
            self._clear_thinking()
            with inner:
                self._thinking = views.render_thinking()
            return
        if name == "MessagePosted":
            self._clear_thinking()
            with inner:
                views.render_user_message(event.text, event.author_name, event.color)
            return
        if name == "AgentDelta":
            self._clear_thinking()
            with inner:
                if self._stream["body"] is None:
                    body, lbl = views.render_stream_bubble()
                    self._stream["body"], self._stream["lbl"], self._stream["text"] = body, lbl, ""
                self._stream["text"] += event.text
                self._stream["lbl"].set_content(self._stream["text"])
            return
        if name == "AgentDone":
            self._clear_thinking()
            with inner:
                if self._stream["body"] is not None:
                    views.finalize_stream(self._stream["body"], event.text)
                    self._stream["body"] = None
                elif event.text:
                    views.render_message({"role": "assistant", "content": event.text})
            return
        if name == "ToolStarted":
            self._clear_thinking()
            with inner:
                args = event.args if isinstance(event.args, dict) else {}
                old = args.get("old") if event.name == "edit" else None
                new = args.get("new") if event.name == "edit" else None
                self._handles[event.id] = views.render_tool(event.name, views.tool_summary(event.args),
                                                            old=old, new=new)
            return
        if name == "ToolFinished":
            with inner:
                handle = self._handles.get(event.id)
                ok = not event.output.startswith("Error")
                out_text = "" if (event.name == "edit" and ok) else event.output
                if handle is not None:
                    views.fill_tool(handle, out_text, ok=ok, name=event.name)
                else:
                    h = views.render_tool(event.name, "", output=out_text, status="DONE" if ok else "ERR")
                    if event.name != "edit":
                        h[2].set_text(views.tool_metric(event.name, event.output))
            return
        if name == "RunError":
            self._clear_thinking()
            with inner:
                if self._stream["body"] is not None:
                    views.finalize_stream(self._stream["body"], self._stream["text"])
                    self._stream["body"] = None
                with ui.element("div").classes("run-error"):
                    ui.label(f"⚠ {event.message}")
            return
        if name == "PermissionRequested":
            with inner:
                card = views.render_permission_request(
                    event.tool, event.target, event.reason, event.options,
                    on_choice=lambda choice, rid=event.request_id: self._hub.resolve_permission(
                        rid, choice, actor=self._author),
                )
            self._handles["perm:" + event.request_id] = card
            return
        if name == "AskRequested":
            with inner:
                card = views.render_ask_request(
                    event.question, event.options,
                    on_answer=lambda ans, rid=event.request_id: self._hub.resolve_ask(rid, ans))
            self._handles["ask:" + event.request_id] = card
            return
        if name == "WorktreeProposed":
            def _approve(pid=event.proposal_id):
                asyncio.create_task(self._hub.approve_worktree(self._sid, pid))

            def _reject(pid=event.proposal_id):
                self._hub.reject_worktree(self._sid, pid)
            with inner:
                card = views.render_worktree_proposal(event.name, event.prompt, _approve, _reject)
            self._wt_cards[event.proposal_id] = card
            return
        if name in ("WorktreeCreated", "WorktreeRejected"):
            card = self._wt_cards.pop(event.proposal_id, None)
            if card is not None:
                card.delete()
            return
        if name in ("RunFinished", "Idle"):
            self._clear_thinking()
            self._stream["body"] = None
            try:
                self._on_idle()
            except Exception:
                pass
            return

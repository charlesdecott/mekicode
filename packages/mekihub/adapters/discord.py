"""discord.py — adaptateur Discord du SessionHub.

Mapping canal Discord -> session. Un message entrant -> hub.submit. Une tâche par session
mappée consomme hub.subscribe et rend la sortie agent (post/edit). discord.py n'est PAS importé
au niveau module (optionnel) : `connect_real()` l'importe à la demande. La logique est testable
via FakeDiscordClient (réseau-free).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class FakeMessage:
    channel_id: str
    author_name: str
    author_id: str
    is_bot: bool
    content: str


class FakeDiscordClient:
    """Capture les envois/éditions au lieu d'appeler Discord."""

    def __init__(self):
        self._messages: list[dict] = []   # {channel_id, text}
        self._guilds: dict[str, str] = {}
        self._categories: dict[str, tuple] = {}
        self._channels: dict[str, tuple] = {}
        self._invites: list[str] = []
        self._seq: int = 0

    def _nid(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"

    async def send(self, channel_id: str, text: str) -> int:
        self._messages.append({"channel_id": channel_id, "text": text})
        return len(self._messages) - 1     # "message id" = index

    async def edit(self, channel_id: str, message_id: int, text: str) -> None:
        self._messages[message_id]["text"] = text

    def sent_texts(self) -> list[str]:
        return [m["text"] for m in self._messages]

    async def create_guild(self, name: str) -> str:
        gid = self._nid("g")
        self._guilds[gid] = name
        return gid

    async def create_category(self, guild_id: str, name: str) -> str:
        cid = self._nid("cat")
        self._categories[cid] = (guild_id, name)
        return cid

    async def create_channel(self, guild_id: str, category_id: str, name: str) -> str:
        chid = self._nid("ch")
        self._channels[chid] = (guild_id, category_id, name)
        return chid

    async def create_invite(self, channel_id: str) -> str:
        inv = "https://discord.gg/" + self._nid("inv")
        self._invites.append(inv)
        return inv

    def category_count(self) -> int:
        return len(self._categories)

    def channel_count(self) -> int:
        return len(self._channels)

    def channel_name(self, channel_id: str) -> str:
        return self._channels[channel_id][2]


try:
    from projects import slugify  # type: ignore  # sys.path posé par mekihub/__init__.py
except ImportError:
    from mekihub.projects import slugify


def _channel_name(session) -> str:
    """Nom Discord d'un canal à partir de la session (scope + titre/id)."""
    if session.scope == "main":
        base = slugify(session.title or session.id) or session.id[:8]
        return f"main-{base[:80]}"
    return f"{slugify(session.scope)}-{session.id[:8]}"


class DiscordProvisioner:
    """Cycle de vie serveur/catégories/canaux Discord, idempotent (piloté par le registre)."""

    def __init__(self, registry, client, *, guild_id=None, admin_user_id=None):
        self.registry = registry
        self.client = client
        self.guild_id = guild_id
        self.admin_user_id = admin_user_id

    async def ensure_server(self):
        if self.guild_id:
            return self.guild_id
        if hasattr(self.client, "create_guild"):
            self.guild_id = await self.client.create_guild("mekicode")
            return self.guild_id
        return None

    async def ensure_project(self, project):
        gid = await self.ensure_server()
        d = dict(project.discord or {})
        if not d.get("cat_main"):
            d["cat_main"] = await self.client.create_category(gid, f"{project.slug}-main")
        if not d.get("cat_worktrees"):
            d["cat_worktrees"] = await self.client.create_category(gid, f"{project.slug}-worktrees")
        d["guild_id"] = gid
        project.discord = d
        self.registry.update(project)
        return d["cat_main"], d["cat_worktrees"]

    async def ensure_channel(self, session):
        if getattr(session, "discord_channel_id", None):
            return session.discord_channel_id
        project = self.registry.get(session.project_id)
        cat_main, cat_wt = await self.ensure_project(project)
        cat = cat_main if session.scope == "main" else cat_wt
        ch = await self.client.create_channel(project.discord["guild_id"], cat, _channel_name(session))
        session.discord_channel_id = ch
        return ch


def _color_from_id(author_id: str) -> str:
    palette = ["#39ff14", "#ff2bd6", "#19e0ff", "#f7ff12", "#b06bff", "#4d8cff"]
    return palette[sum(ord(c) for c in author_id) % len(palette)]


class DiscordAdapter:
    """Branche un client Discord (réel ou factice) sur le SessionHub."""

    def __init__(self, hub, client, channel_session: dict):
        self.hub = hub
        self.client = client
        self.channel_session = channel_session     # channel_id -> session_id
        self._tasks: dict[str, asyncio.Task] = {}

    async def handle_message(self, msg: FakeMessage) -> None:
        if msg.is_bot:
            return
        session_id = self.channel_session.get(msg.channel_id)
        if session_id is None:
            return
        try:
            from session import Author  # type: ignore  # sys.path posé par mekihub/__init__.py
        except ImportError:
            from mekihub.session import Author  # noqa: F401  # fallback si sous-paquet isolé
        author = Author(id=msg.author_id, name=msg.author_name,
                        color=_color_from_id(msg.author_id), source=f"discord:{msg.channel_id}")
        # s'assurer qu'une tâche d'abonnement rend la sortie de ce canal
        if msg.channel_id not in self._tasks or self._tasks[msg.channel_id].done():
            self._tasks[msg.channel_id] = asyncio.create_task(
                self._render_loop(msg.channel_id, session_id)
            )
        self.hub.submit(session_id, msg.content, author=author)

    async def _render_loop(self, channel_id: str, session_id: str) -> None:
        msg_id = None
        buffer = ""
        async for event in self.hub.subscribe(session_id):
            name = type(event).__name__
            if name == "RunStarted":
                buffer = ""
                msg_id = await self.client.send(channel_id, "…")
            elif name == "AgentDelta":
                buffer += event.text
                if msg_id is not None:
                    await self.client.edit(channel_id, msg_id, buffer)
            elif name == "AgentDone":
                if msg_id is not None:
                    await self.client.edit(channel_id, msg_id, event.text)
                msg_id = None
            elif name == "RunError":
                txt = f"⚠ erreur : {event.message}"
                if msg_id is not None:
                    await self.client.edit(channel_id, msg_id, txt)
                else:
                    await self.client.send(channel_id, txt)
                msg_id = None
            elif name == "MessagePosted":
                if getattr(event, "source", None) != f"discord:{channel_id}":
                    await self.client.send(channel_id, f"**{event.author_name}**: {event.text}")
            elif name == "Idle":
                break

    async def flush(self) -> None:
        """Attend que les tâches de rendu en cours se terminent (tests)."""
        await asyncio.gather(*[t for t in self._tasks.values() if not t.done()],
                             return_exceptions=True)

    async def connect_real(self, token: str) -> None:
        """Connexion Discord réelle (discord.py). Importé à la demande ; validation manuelle."""
        import discord  # importé seulement ici (dépendance optionnelle)
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_message(message):  # noqa: ANN001
            await self.handle_message(FakeMessage(
                channel_id=str(message.channel.id), author_name=message.author.display_name,
                author_id=str(message.author.id), is_bot=message.author.bot,
                content=message.content))

        # NB : self.client doit alors être un wrapper qui appelle channel.send/edit ; câblage réel
        # finalisé lors de la validation manuelle avec un vrai token.
        await client.start(token)

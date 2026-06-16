"""discord.py — adaptateur Discord du SessionHub.

Mapping canal Discord -> session. Un message entrant -> hub.submit. Une tâche par session
mappée consomme hub.subscribe et rend la sortie agent (post/edit). discord.py n'est PAS importé
au niveau module (optionnel) : `connect_real()` l'importe à la demande. La logique est testable
via FakeDiscordClient (réseau-free).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field


@dataclass
class FakeMessage:
    channel_id: str
    author_name: str
    author_id: str
    is_bot: bool
    content: str
    message_id: str = ""        # id du message Discord (pour répondre dessus / reference)


class FakeDiscordClient:
    """Capture les envois/éditions au lieu d'appeler Discord."""

    def __init__(self):
        self._messages: list[dict] = []   # {channel_id, text}
        self._guilds: dict[str, str] = {}
        self._categories: dict[str, tuple] = {}
        self._channels: dict[str, tuple] = {}
        self._invites: list[str] = []
        self._deleted: list = []
        self._seq: int = 0

    def _nid(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"

    async def send(self, channel_id: str, text: str, embed: dict | None = None, reply_to=None) -> int:
        self._messages.append({"channel_id": channel_id, "text": text, "embed": embed,
                               "reply_to": reply_to})
        return len(self._messages) - 1     # "message id" = index

    async def edit(self, channel_id: str, message_id: int, text: str, embed: dict | None = None) -> None:
        self._messages[message_id]["text"] = text
        if embed is not None:
            self._messages[message_id]["embed"] = embed

    async def delete(self, channel_id: str, message_id) -> None:
        self._deleted.append(message_id)

    def sent_texts(self) -> list[str]:
        return [m["text"] for m in self._messages]

    def sent_embeds(self) -> list[dict]:
        return [m["embed"] for m in self._messages if m.get("embed")]

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

    async def reconcile(self, store):
        """Parcourt projets+sessions ; crée les canaux manquants (idempotent). Renvoie le nb de créations."""
        created = 0
        for project in self.registry.list():
            await self.ensure_project(project)
            for meta in store.list(project_id=project.id):
                sess = store.load(meta.id)
                if not getattr(sess, "discord_channel_id", None):
                    await self.ensure_channel(sess)
                    store.save(sess)
                    created += 1
        return created


def provisioner_from_env(registry, client):
    """Construit un DiscordProvisioner depuis l'environnement, ou None si pas de token.
    Import-safe : aucun appel réseau ici. `client` = client Discord réel ou factice déjà construit."""
    if not os.environ.get("DISCORD_BOT_TOKEN"):
        return None
    return DiscordProvisioner(registry=registry, client=client,
                              guild_id=os.environ.get("DISCORD_GUILD_ID") or None,
                              admin_user_id=os.environ.get("MEKICODE_ADMIN_USER_ID") or None)


def _color_from_id(author_id: str) -> str:
    palette = ["#39ff14", "#ff2bd6", "#19e0ff", "#f7ff12", "#b06bff", "#4d8cff"]
    return palette[sum(ord(c) for c in author_id) % len(palette)]


def _tool_summary(name: str, args) -> str:
    """Argument le plus parlant d'un outil, tronqué (pour l'en-tête du bloc Discord)."""
    if not isinstance(args, dict) or not args:
        return ""
    key = {"bash": "command", "read": "path", "write": "path", "edit": "path",
           "grep": "pattern", "glob": "pattern"}.get(name)
    val = args.get(key) if key else next(iter(args.values()), "")
    return str(val).replace("\n", " ")[:120]


# Glyphe + couleur par type d'outil (en-tête de carte embed). Couleur = identité de l'outil ;
# le statut reste lisible via le footer (●/✓/✗). En cas d'erreur, la carte vire au rouge.
_TOOL_GLYPH = {"bash": "$", "read": "▤", "write": "✎", "edit": "✂", "grep": "⌕", "glob": "❖",
               "spawn_worktree": "⎇"}
_TOOL_COLOR = {"bash": 0x39FF14, "read": 0x19E0FF, "write": 0xFF2BD6, "edit": 0xB06BFF,
               "grep": 0xF7FF12, "glob": 0xFF8C2B, "spawn_worktree": 0x4D8CFF}
# Libellé de la colonne « argument » selon l'outil.
_TOOL_LABEL = {"bash": "commande", "read": "fichier", "write": "fichier", "edit": "fichier",
               "grep": "motif", "glob": "motif", "spawn_worktree": "worktree"}
_DEFAULT_TOOL_COLOR = 0x8899AA
_ERROR_COLOR = 0xFF3B3B


def _tool_embed(name: str, summary: str, status: str, output) -> dict:
    """Spec d'embed COMPACTE (carte Discord) pour un appel d'outil. status ∈ {running, ok, err}.

    Mise en colonnes via des champs `inline` : une ligne « arg | statut » côte à côte, puis la
    sortie en pleine largeur uniquement si présente. Couleur = type d'outil (rouge si erreur)."""
    color = _ERROR_COLOR if status == "err" else _TOOL_COLOR.get(name, _DEFAULT_TOOL_COLOR)
    statut = {"running": "● en cours…", "ok": "✓ terminé", "err": "✗ erreur"}[status]
    glyph = _TOOL_GLYPH.get(name, "🔧")
    fields = []
    if summary:
        fields.append({"name": _TOOL_LABEL.get(name, "arg"),
                       "value": f"`{summary[:90]}`", "inline": True})
    fields.append({"name": "statut", "value": statut, "inline": True})
    out = str(output).strip() if output is not None else ""
    if out and out != "(no output)":
        fields.append({"name": "sortie", "value": f"```\n{out[:400]}\n```", "inline": False})
    return {"title": f"{glyph} {name}", "color": color, "fields": fields}


class DiscordAdapter:
    """Branche un client Discord (réel ou factice) sur le SessionHub."""

    def __init__(self, hub, client, channel_session: dict, *, tool_style: str = "text"):
        self.hub = hub
        self.client = client
        self.channel_session = channel_session     # channel_id -> session_id
        self.tool_style = tool_style               # "text" (blocs) | "embed" (cartes)
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict = {}                    # channel_id -> {"active","pending","qmsg"}
        self._questions: dict = {}                 # item_id -> message_id de la question (pour reply)

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
        # s'assurer qu'une tâche d'abonnement rend la sortie de ce canal (persistante en prod via
        # start_all ; ici non-persistante pour rester compatible avec flush() des tests)
        if msg.channel_id not in self._tasks or self._tasks[msg.channel_id].done():
            self._tasks[msg.channel_id] = asyncio.create_task(
                self._render_loop(msg.channel_id, session_id)
            )
        item_id = self.hub.submit(session_id, msg.content, author=author)
        if msg.message_id:        # question venue de Discord : l'agent répondra sur ce message
            self._questions[item_id] = msg.message_id

    def _qstate(self, channel_id) -> dict:
        """État de file d'attente par canal : run actif, messages en attente, id de l'embed file."""
        return self._queues.setdefault(channel_id, {"active": False, "pending": {}, "qmsg": None})

    async def _emit(self, channel_id, text="", embed=None, reply_to=None):
        """Poste un message de CONTENU puis re-pose l'embed file d'attente TOUT EN BAS (delete+repost,
        comme le cadre du front). `reply_to` = id de message à référencer. Renvoie l'id du contenu."""
        q = self._qstate(channel_id)
        if q["qmsg"] is not None:        # retire l'embed file : il sera reposté en dessous du contenu
            try:
                await self.client.delete(channel_id, q["qmsg"])
            except Exception:
                pass
            q["qmsg"] = None
        mid = await self.client.send(channel_id, text, embed=embed, reply_to=reply_to)
        await self._sync_queue(channel_id)     # repose la file en bas (si des messages attendent)
        return mid

    async def _sync_queue(self, channel_id):
        """(Re)pose / met à jour / supprime l'embed file d'attente selon l'état du canal.
        Embed jaune compact listant les messages en attente, toujours posé en dernier."""
        q = self._qstate(channel_id)
        pending = q["pending"]
        if pending:
            lines = "\n".join(f"• {v}" for v in list(pending.values())[:10])
            if len(pending) > 10:
                lines += f"\n… (+{len(pending) - 10})"
            embed = {"title": f"⏳ File d'attente ({len(pending)})", "color": 0xF7FF12,
                     "fields": [{"name": "messages en attente", "value": lines[:1000], "inline": False}]}
            if q["qmsg"] is None:
                q["qmsg"] = await self.client.send(channel_id, "", embed=embed)
            else:
                await self.client.edit(channel_id, q["qmsg"], "", embed=embed)
        elif q["qmsg"] is not None:
            try:
                await self.client.delete(channel_id, q["qmsg"])
            except Exception:
                pass
            q["qmsg"] = None

    async def _render_loop(self, channel_id: str, session_id: str, persistent: bool = False) -> None:
        msg_id = None
        buffer = ""
        last_edit = 0.0                # throttle des éditions de streaming (anti rate-limit Discord)
        tool_msgs: dict = {}           # tool_call_id -> {"mid", "summary"}
        current_item = None            # item_id du run en cours (→ message question pour le reply)
        q = self._qstate(channel_id)   # état de file partagé pour ce canal
        async for event in self.hub.subscribe(session_id):
            name = type(event).__name__
            if name == "Idle":         # hors try : doit toujours boucler/sortir proprement
                q["active"] = False
                if q["pending"] or q["qmsg"] is not None:
                    q["pending"].clear()
                    await self._sync_queue(channel_id)
                if persistent:
                    continue           # miroir permanent : on reste abonné entre les runs
                break
            try:
                if name == "RunStarted":
                    buffer = ""
                    msg_id = None      # ne PAS poster ici : la question (MessagePosted) doit précéder
                    tool_msgs.clear()
                    current_item = event.item_id
                    q["active"] = True
                    if q["pending"].pop(event.item_id, None) is not None:
                        await self._sync_queue(channel_id)
                elif name == "RunFinished":
                    q["active"] = False
                    self._questions.pop(current_item, None)   # nettoyage de la question traitée
                    current_item = None
                elif name == "QueueEnqueued":
                    if q["active"]:    # n'affiche que ce qui attend DERRIÈRE un run en cours
                        q["pending"][event.item_id] = f"**{event.author_name}**: {event.text[:70]}"
                        await self._sync_queue(channel_id)
                elif name == "QueueItemDeleted":
                    self._questions.pop(event.item_id, None)
                    if q["pending"].pop(event.item_id, None) is not None:
                        await self._sync_queue(channel_id)
                elif name == "AgentDelta":
                    buffer += event.text
                    now = asyncio.get_event_loop().time()
                    if msg_id is None:        # 1er fragment : on RÉPOND au message de la question
                        msg_id = await self._emit(channel_id, buffer or "…",
                                                  reply_to=self._questions.get(current_item))
                        last_edit = now
                    elif now - last_edit >= 1.2:      # ~1 édition / 1.2s pendant le stream
                        await self.client.edit(channel_id, msg_id, buffer)
                        last_edit = now
                elif name == "AgentDone":
                    if msg_id is not None:    # édition finale garantie (texte complet)
                        await self.client.edit(channel_id, msg_id, event.text)
                    elif event.text:          # réponse sans streaming (ex. outil seul) : répondre
                        await self._emit(channel_id, event.text,
                                         reply_to=self._questions.get(current_item))
                    msg_id = None
                elif name == "ToolStarted":
                    summary = _tool_summary(event.name, event.args)
                    if self.tool_style == "embed":
                        mid = await self._emit(
                            channel_id, "", embed=_tool_embed(event.name, summary, "running", None))
                    else:
                        head = f"🔧 `{event.name}`" + (f" · `{summary}`" if summary else "")
                        mid = await self._emit(channel_id, head[:2000])
                    tool_msgs[event.id] = {"mid": mid, "summary": summary}
                elif name == "ToolFinished":
                    info = tool_msgs.pop(event.id, None)
                    mid = info["mid"] if info else None
                    summary = info["summary"] if info else ""
                    out = str(event.output).strip()
                    ok = not out.startswith("Error")
                    if self.tool_style == "embed":
                        embed = _tool_embed(event.name, summary, "ok" if ok else "err", event.output)
                        if mid is not None:
                            await self.client.edit(channel_id, mid, "", embed=embed)
                        else:
                            await self._emit(channel_id, "", embed=embed)
                    else:
                        block = f"\n```\n{out[:600]}\n```" if out and out != "(no output)" else ""
                        txt = f"🔧 `{event.name}` {'✓' if ok else '✗'}{block}"
                        if mid is not None:
                            await self.client.edit(channel_id, mid, txt[:2000])
                        else:
                            await self._emit(channel_id, txt[:2000])
                elif name == "RunError":
                    txt = f"⚠ erreur : {event.message}"
                    if msg_id is not None:
                        await self.client.edit(channel_id, msg_id, txt)
                    else:
                        await self._emit(channel_id, txt)
                    msg_id = None
                    self._questions.pop(current_item, None)
                    current_item = None
                elif name == "MessagePosted":
                    if getattr(event, "source", None) != f"discord:{channel_id}":
                        # question venue du front web : on poste le miroir et l'agent y répondra
                        mirror = await self._emit(channel_id, f"**{event.author_name}**: {event.text}")
                        if current_item is not None:
                            self._questions[current_item] = mirror
            except Exception as e:     # JAMAIS tuer la boucle persistante sur une erreur Discord
                print(f"[discord] rendu '{name}' sur {channel_id} échoué : {type(e).__name__}: {e}")

    async def flush(self) -> None:
        """Attend que les tâches de rendu en cours se terminent (tests)."""
        await asyncio.gather(*[t for t in self._tasks.values() if not t.done()],
                             return_exceptions=True)

    def add_mapping(self, channel_id: str, session_id: str) -> None:
        """Enregistre un canal↔session et démarre son rendu persistant (miroir sortant à chaud)."""
        self.channel_session[channel_id] = session_id
        if channel_id not in self._tasks or self._tasks[channel_id].done():
            self._tasks[channel_id] = asyncio.create_task(
                self._render_loop(channel_id, session_id, persistent=True))

    async def start_all(self) -> None:
        """Démarre un rendu persistant pour chaque canal déjà mappé (miroir bidirectionnel)."""
        for channel_id, session_id in list(self.channel_session.items()):
            if channel_id not in self._tasks or self._tasks[channel_id].done():
                self._tasks[channel_id] = asyncio.create_task(
                    self._render_loop(channel_id, session_id, persistent=True))

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


class RealDiscordClient:
    """Adapte un `discord.Client` à l'interface attendue par DiscordProvisioner/DiscordAdapter
    (send/edit/create_guild/create_category/create_channel/create_invite). Tous les ids sont des str."""

    def __init__(self, client):
        self.client = client     # discord.Client (déjà connecté quand on l'utilise)

    async def _channel(self, channel_id):
        cid = int(channel_id)
        return self.client.get_channel(cid) or await self.client.fetch_channel(cid)

    async def _guild(self, guild_id):
        gid = int(guild_id)
        return self.client.get_guild(gid) or await self.client.fetch_guild(gid)

    @staticmethod
    def _build_embed(spec: dict):
        import discord
        e = discord.Embed(title=spec.get("title"), description=spec.get("description"),
                          color=spec.get("color"))
        for f in spec.get("fields", []):
            e.add_field(name=f.get("name", "—"), value=f.get("value", ""), inline=f.get("inline", False))
        if spec.get("footer"):
            e.set_footer(text=spec["footer"])
        return e

    async def send(self, channel_id, text, embed=None, reply_to=None) -> str:
        import discord
        ch = await self._channel(channel_id)
        kw = {}
        if reply_to:        # répond au message d'origine (référence visible dans Discord)
            kw["reference"] = discord.MessageReference(
                message_id=int(reply_to), channel_id=int(channel_id), fail_if_not_exists=False)
        if embed is not None:
            msg = await ch.send(content=(text or None), embed=self._build_embed(embed), **kw)
        else:
            msg = await ch.send((text or "…")[:2000], **kw)
        return str(msg.id)

    async def edit(self, channel_id, message_id, text, embed=None) -> None:
        ch = await self._channel(channel_id)
        msg = await ch.fetch_message(int(message_id))
        if embed is not None:
            await msg.edit(content=(text or None), embed=self._build_embed(embed))
        else:
            await msg.edit(content=(text or "…")[:2000])

    async def create_guild(self, name) -> str:
        g = await self.client.create_guild(name=name)
        return str(g.id)

    async def create_category(self, guild_id, name) -> str:
        g = await self._guild(guild_id)
        cat = await g.create_category(name[:100])
        return str(cat.id)

    async def create_channel(self, guild_id, category_id, name) -> str:
        g = await self._guild(guild_id)
        cat = g.get_channel(int(category_id))
        ch = await g.create_text_channel(name[:100], category=cat)
        return str(ch.id)

    async def create_invite(self, channel_id) -> str:
        ch = await self._channel(channel_id)
        inv = await ch.create_invite(max_age=0, max_uses=0, reason="mekicode admin invite")
        return inv.url

    async def delete(self, channel_id, message_id) -> None:
        ch = await self._channel(channel_id)
        msg = await ch.fetch_message(int(message_id))
        await msg.delete()


async def run_discord(hub, registry, store, *, token, guild_id=None, admin_user_id=None,
                      holder=None) -> None:
    """Démarre le bot Discord réel et le branche sur le hub (provisioning + miroir bidirectionnel).

    Bloque sur `client.start(token)` (à lancer dans une tâche asyncio). À `on_ready` : reconcilie
    les canaux (catégories <projet>-main/-worktrees + un canal par session), construit le mapping
    canal→session et démarre un rendu persistant par canal. `holder` (dict optionnel) reçoit
    `adapter`/`provisioner` pour le câblage à chaud des nouvelles sessions.
    """
    import discord
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    real = RealDiscordClient(client)
    prov = DiscordProvisioner(registry=registry, client=real,
                              guild_id=guild_id, admin_user_id=admin_user_id)
    hub.provisioner = prov
    # Style d'affichage des appels d'outils : "embed" (cartes, défaut) ou "text" (blocs).
    tool_style = (os.environ.get("MEKICHAT_DISCORD_TOOL_STYLE") or "embed").lower()
    adapter = DiscordAdapter(hub=hub, client=real, channel_session={}, tool_style=tool_style)
    if holder is not None:
        holder["adapter"] = adapter
        holder["provisioner"] = prov
        holder["client"] = client

    @client.event
    async def on_ready():
        try:
            n = await prov.reconcile(store)
            for project in registry.list():
                for meta in store.list(project_id=project.id):
                    sess = store.load(meta.id)
                    chan = getattr(sess, "discord_channel_id", None)
                    if chan:
                        adapter.channel_session[str(chan)] = sess.id
            await adapter.start_all()
            print(f"[discord] prêt — {client.user} · {n} canal(aux) créé(s) · "
                  f"{len(adapter.channel_session)} canal(aux) mappé(s)")
        except Exception as e:      # never-raise : un échec de provisioning ne tue pas le bot
            print(f"[discord] erreur on_ready : {type(e).__name__}: {e}")

    @client.event
    async def on_message(message):  # noqa: ANN001
        await adapter.handle_message(FakeMessage(
            channel_id=str(message.channel.id), author_name=message.author.display_name,
            author_id=str(message.author.id), is_bot=message.author.bot,
            content=message.content or "", message_id=str(message.id)))

    await client.start(token)

"""
ChatCLI interactive API walkthrough.

A human-in-the-loop test tool: it drives the backend the way the real client
does and prints every request/response (and every WebSocket frame) as a
readable panel, so you can watch the flows and judge whether they look right.
It is meant to be read, run, and extended — add a step by copying an existing
one.

PREREQUISITES (all local, see src/backend):
  1. MariaDB up, with the `chatcli` schema.
  2. Flask REST API running:   python src/backend/main.py            (port 5123)
  3. FastAPI WebSocket running: python src/backend/app/websockets/main.py (port 8765)
  4. src/backend/.env present (used here only to mint an invite code straight
     in the DB, since registration is invite-gated).

RUN:
    python main.py
and pick a section from the menu.

Scope: REST (auth/profile/chat) + WebSocket chat (send/edit/delete/typing/
presence). Calls are intentionally excluded (not functional this release).
"""
import os
import json
import time
import random
import string
import asyncio
from pathlib import Path
from dataclasses import dataclass

import requests
import pymysql
import websockets
from dotenv import dotenv_values

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule

console = Console()

# Endpoints (override via env if your setup differs).
BASE_URL = os.getenv("CHATCLI_BASE_URL", "http://localhost:5123")
WS_URL = os.getenv("CHATCLI_WS_URL", "ws://localhost:8765/ws")

# The backend .env, two levels up from this file (src/backend/.env). Used only
# to insert an invite code, because registration now requires one.
ENV_PATH = Path(__file__).resolve().parents[2] / "backend" / ".env"

# Every account created here uses this password (meets the backend policy).
TEST_PASSWORD = "Aa123456!"


# ============================ Small helpers ============================ #

def _rand_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _pretty(data) -> str:
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return str(data)


@dataclass
class UserTokens:
    username: str
    email: str
    password: str
    access_token: str
    refresh_token: str


# ============================ Invite minting ============================ #
# Registration is invite-gated, so before we can register test accounts we
# drop a fresh, high-use invite code straight into the DB (same table the
# admin tool make_invite.py writes to).

_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gen_invite(groups: int = 3, size: int = 4) -> str:
    raw = "".join(random.choice(_INVITE_ALPHABET) for _ in range(groups * size))
    return "-".join(raw[i:i + size] for i in range(0, len(raw), size))


def mint_invite(max_uses: int = 100) -> str:
    """Insert a random invite code with plenty of uses and return it."""
    env = dotenv_values(ENV_PATH)
    conn = pymysql.connect(
        host=env.get("DB_HOST", "localhost"),
        user=env.get("DB_USER", "root"),
        password=env.get("DB_PASSWORD", ""),
        database=env.get("DB_NAME", "chatcli"),
        port=int(env.get("DB_PORT", 3306) or 3306),
        autocommit=True,
    )
    try:
        code = _gen_invite()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO invite_codes (code, max_uses) VALUES (%s, %s)",
                (code, max_uses),
            )
        console.print(Panel(f"Minted invite code [bold]{code}[/bold] (max_uses={max_uses})",
                            title="DB", border_style="blue"))
        return code
    finally:
        conn.close()


# ============================ REST helpers ============================ #

def api_post(path: str, json_data: dict):
    url = BASE_URL + path
    console.print(Rule(f"[bold cyan]POST {url}"))
    console.print(Panel(_pretty(json_data), title="Payload", border_style="cyan"))

    resp = requests.post(url, json=json_data)
    console.print(f"[bold]Status:[/bold] [magenta]{resp.status_code}[/magenta]")

    try:
        body = resp.json()
        console.print(Panel(_pretty(body), title="Response JSON", border_style="green"))
    except Exception:
        text = (resp.text or "")[:300]
        body = {"_raw": text}
        console.print(Panel(text, title="Raw Text", border_style="yellow"))

    resp.raise_for_status()
    return body


# ============================ REST building blocks ============================ #

def register_and_login(name: str, invite_code: str) -> UserTokens:
    """Register one account (with the shared invite) and log it in."""
    username = f"{name}_{_rand_suffix()}"
    email = f"{username}@example.com"

    console.print(Rule(f"[bold blue]New user: {username}[/bold blue]"))

    api_post("/user/register", {
        "username": username,
        "password": TEST_PASSWORD,
        "email": email,
        "invite_code": invite_code,
    })
    time.sleep(0.1)

    login = api_post("/user/login", {"username": username, "password": TEST_PASSWORD})
    return UserTokens(
        username=username,
        email=email,
        password=TEST_PASSWORD,
        access_token=login["access_token"],
        refresh_token=login["refresh_token"],
    )


# ============================ REST walkthrough ============================ #

def rest_walkthrough():
    """
    Exercise the HTTP surface: register -> login -> refresh -> profile ->
    submit-profile -> change-password -> chat CRUD -> logout. Destructive to
    the accounts it creates (they get logged out / password-changed), so it
    always works on fresh throwaway users.
    """
    console.print(Rule("[bold white]REST walkthrough[/bold white]"))
    invite = mint_invite()

    user = register_and_login("rest", invite)
    peer = register_and_login("peer", invite)

    # --- token refresh ---
    api_post("/user/refresh-token", {"refresh_token": user.refresh_token})

    # --- profile read + update ---
    # Changing only the username avoids the email-change path, which sends a
    # verification email and therefore needs working SMTP. Email change and
    # password reset are email-dependent and are not exercised offline.
    api_post("/user/profile", {"session_token": user.access_token})
    api_post("/user/submit-profile", {
        "session_token": user.access_token,
        "username": user.username + "_v2",
        "email": user.email,
    })

    # --- private chat: create + read + archive/unarchive ---
    console.print(Rule(f"[bold magenta]Private chat: {user.username} <-> {peer.username}[/bold magenta]"))
    api_post("/chat/fetch-chats", {"session_token": user.access_token})
    create = api_post("/chat/create-chat", {
        "session_token": user.access_token,
        "receiver": peer.username,
    })
    chat_id = create.get("chatID") or create.get("chatId") or create.get("chat_id")
    if chat_id is None:
        raise RuntimeError("create-chat did not return a chat id")
    console.print(Panel(f"Private chat ID: {chat_id}", border_style="magenta"))

    api_post("/chat/messages", {"session_token": user.access_token, "chatID": chat_id, "limit": 50})
    api_post("/chat/archive-chat", {"session_token": user.access_token, "chatID": chat_id})
    api_post("/chat/fetch-archived", {"session_token": user.access_token})
    api_post("/chat/unarchive-chat", {"session_token": user.access_token, "chatID": chat_id})

    # --- group chat: create + members + add + read ---
    # get-members is group-only (private chats 404 it), so it lives here.
    third = register_and_login("groupie", invite)
    console.print(Rule(f"[bold magenta]Group chat owned by {user.username}[/bold magenta]"))
    gcreate = api_post("/chat/create-group", {
        "session_token": user.access_token,
        "name": "Test Group",
        "members": [peer.username],
    })
    group_id = gcreate.get("chatID") or gcreate.get("chatId") or gcreate.get("chat_id")
    if group_id is None:
        raise RuntimeError("create-group did not return a chat id")
    console.print(Panel(f"Group chat ID: {group_id}", border_style="magenta"))

    api_post("/chat/get-members", {"session_token": user.access_token, "chatID": group_id})
    api_post("/chat/add-members", {
        "session_token": user.access_token, "chatID": group_id, "members": [third.username],
    })
    api_post("/chat/get-members", {"session_token": user.access_token, "chatID": group_id})
    api_post("/chat/messages", {"session_token": user.access_token, "chatID": group_id, "limit": 50})

    # --- password change + logout (destructive; do last) ---
    api_post("/user/change-password", {
        "session_token": user.access_token,
        "current_password": user.password,
        "new_password": "Bb123456!",
    })
    api_post("/user/logout-all", {"session_token": peer.access_token})

    console.print(Panel("[bold green]REST walkthrough complete[/bold green]", border_style="green"))


# ============================ WebSocket helpers ============================ #

def _show_frame(direction: str, who: str, data: dict):
    """direction: '>>' sent, '<<' received."""
    color = "cyan" if direction == ">>" else "green"
    console.print(Panel(_pretty(data), title=f"{direction} {who}", border_style=color))


async def ws_connect_auth(who: str, token: str):
    """Open a WS, run the auth handshake, and return the live connection."""
    ws = await websockets.connect(WS_URL)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    _show_frame(">>", who, {"type": "auth", "token": f"{token[:8]}..."})

    # Server sends auth_ack then online_users right after a good handshake.
    for _ in range(2):
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        _show_frame("<<", who, frame)
    return ws


async def drain(who: str, ws, seconds: float = 1.0):
    """Print whatever the given socket has received within a short window."""
    deadline = asyncio.get_event_loop().time() + seconds
    got = []
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            got.append(frame)
            _show_frame("<<", who, frame)
        except asyncio.TimeoutError:
            break
    if not got:
        console.print(f"[dim]({who} received nothing)[/dim]")
    return got


# ============================ WebSocket walkthrough ============================ #

async def ws_walkthrough():
    """
    Two live clients in one chat. Alice acts; Bob observes. Watch the received
    panels to judge that each action fans out correctly.
    """
    console.print(Rule("[bold white]WebSocket chat walkthrough[/bold white]"))
    invite = mint_invite()

    alice = register_and_login("alice", invite)
    bob = register_and_login("bob", invite)

    # Alice creates the private chat; both are participants.
    create = api_post("/chat/create-chat", {
        "session_token": alice.access_token,
        "receiver": bob.username,
    })
    chat_id = create.get("chatID") or create.get("chatId") or create.get("chat_id")
    if chat_id is None:
        raise RuntimeError("create-chat did not return a chat id")
    console.print(Panel(f"Chat ID: {chat_id}", border_style="magenta"))

    # Connect Alice first, then Bob (so Alice should see Bob come online).
    ws_a = await ws_connect_auth("alice", alice.access_token)
    ws_b = await ws_connect_auth("bob", bob.access_token)

    console.print(Rule("[cyan]presence: Bob just connected -> Alice should get user_status[/cyan]"))
    await drain("alice", ws_a, 1.0)

    # Both subscribe to the chat.
    for who, ws in (("alice", ws_a), ("bob", ws_b)):
        await ws.send(json.dumps({"type": "join_chat", "chatID": chat_id}))
        _show_frame(">>", who, {"type": "join_chat", "chatID": chat_id})
    await asyncio.sleep(0.3)

    # 1) Alice posts a message -> Bob should receive new_message.
    console.print(Rule("[cyan]1. post_msg (watch Bob for new_message; note if Alice gets a duplicate)[/cyan]"))
    await ws_a.send(json.dumps({"type": "post_msg", "chatID": chat_id, "text": "hello bob"}))
    _show_frame(">>", "alice", {"type": "post_msg", "chatID": chat_id, "text": "hello bob"})
    a_frames = await drain("alice", ws_a, 1.0)
    b_frames = await drain("bob", ws_b, 1.0)

    # Grab the new message id so we can edit/delete it.
    message_id = None
    for f in a_frames + b_frames:
        if f.get("type") in ("new_message",) and f.get("messageID"):
            message_id = f["messageID"]
            break

    if message_id is None:
        console.print("[bold red]No messageID seen; skipping edit/delete.[/bold red]")
    else:
        # 2) Edit -> both should see edited_message.
        console.print(Rule("[cyan]2. edit_msg (watch for edited_message)[/cyan]"))
        await ws_a.send(json.dumps({"type": "edit_msg", "chatID": chat_id,
                                    "messageID": message_id, "text": "hello bob (edited)"}))
        _show_frame(">>", "alice", {"type": "edit_msg", "messageID": message_id})
        await drain("alice", ws_a, 1.0)
        await drain("bob", ws_b, 1.0)

        # 3) Delete -> both should see deleted_message.
        console.print(Rule("[cyan]3. delete_msg (watch for deleted_message)[/cyan]"))
        await ws_a.send(json.dumps({"type": "delete_msg", "chatID": chat_id, "messageID": message_id}))
        _show_frame(">>", "alice", {"type": "delete_msg", "messageID": message_id})
        await drain("alice", ws_a, 1.0)
        await drain("bob", ws_b, 1.0)

    # 4) Typing -> Bob should see user_typing, Alice should not (sender excluded).
    console.print(Rule("[cyan]4. typing (Bob should see user_typing; Alice should not)[/cyan]"))
    await ws_a.send(json.dumps({"type": "typing", "chatID": chat_id}))
    _show_frame(">>", "alice", {"type": "typing", "chatID": chat_id})
    await drain("bob", ws_b, 1.0)
    await drain("alice", ws_a, 0.5)

    await ws_a.close()
    await ws_b.close()
    console.print(Panel("[bold green]WebSocket walkthrough complete[/bold green]", border_style="green"))


# ============================ Menu ============================ #

def main():
    console.print(Rule("[bold white]ChatCLI API walkthrough[/bold white]"))
    console.print(Panel(
        f"REST: [cyan]{BASE_URL}[/cyan]\nWS:   [cyan]{WS_URL}[/cyan]\n"
        "Make sure both backends and the DB are running.",
        title="Targets", border_style="blue",
    ))

    while True:
        choice = Prompt.ask(
            "\nRun which section?",
            choices=["rest", "ws", "both", "q"],
            default="both",
        )
        try:
            if choice == "rest":
                rest_walkthrough()
            elif choice == "ws":
                asyncio.run(ws_walkthrough())
            elif choice == "both":
                rest_walkthrough()
                asyncio.run(ws_walkthrough())
            elif choice == "q":
                break
        except requests.HTTPError as e:
            console.print(Panel(f"HTTP error: {e}", title="FAILED", border_style="red"))
        except Exception as e:
            console.print(Panel(f"{type(e).__name__}: {e}", title="FAILED", border_style="red"))


if __name__ == "__main__":
    main()

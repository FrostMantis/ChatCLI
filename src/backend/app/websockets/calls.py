import logging
import uuid
import mariadb
import db_helper as db
import services
from fastapi import WebSocket
from livekit import api
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --- LiveKit Configuration ---
LIVEKIT_KEY = os.getenv("LIVEKIT_KEY")
LIVEKIT_SECRET = os.getenv("LIVEKIT_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")

def generate_lk_token(username: str, chat_id: str):
    """Generates the JWT token required for LiveKit."""
    # The room name is the chatID to keep everyone in the same space
    token = api.AccessToken(LIVEKIT_KEY, LIVEKIT_SECRET) \
        .with_identity(username) \
        .with_name(username) \
        .with_grants(api.VideoGrants(
            room_join=True, 
            room=str(chat_id)
        ))
    return token.to_jwt()

# --- Call Logic Functions ---

async def call_invite(ws: WebSocket, chatID: int):
    """Starts a call and generates a LiveKit token for the initiator."""
    caller = getattr(ws.state, "username", None)
    if not caller: 
        return

    # 1. Generate the token for the initiator
    token = generate_lk_token(caller, str(chatID))

    # 2. Inform the group that a call started
    payload = {
        "type": "call_invite",
        "chatID": chatID,
        "caller": caller,
        "lk_token": token,
        "lk_url": LIVEKIT_URL
    }
    
    # Broadcast to everyone in the chat
    await services.broadcast_call_to_chat_participants(chatID, payload)
    return payload

async def call_accept(ws: WebSocket, chatID: int, call_id: str = None):
    """Generates a token for the user joining the call."""
    username = getattr(ws.state, "username", None)
    if not username: 
        return

    # Generate a token for the person joining
    token = generate_lk_token(username, str(chatID))

    return {
        "type": "call_accepted",
        "chatID": chatID,
        "lk_token": token,
        "lk_url": LIVEKIT_URL
    }

async def call_decline(ws: WebSocket, chatID: int) -> None:
    """Decline the current call for this chat (if any), deriving user from `ws`."""
    username = getattr(ws.state, "username", None)
    if not username:
        return
    call_id = services.pending_calls.get(chatID)
    if not call_id:
        return

    session = services.call_sessions.get(call_id)
    payload = {
        "type": "call_declined",
        "chatID": chatID,
        "call_id": call_id,
        "by": username,
        "initiator": session.get("initiator") if session else None,
    }
    await services.broadcast_call_to_chat_participants(chatID, payload)

    services.pending_calls.pop(chatID, None)
    if call_id in services.call_sessions:
        services.call_sessions.pop(call_id, None)

async def call_end(ws: WebSocket, chatID: int) -> None:
    """End the current call for this chat (if any), deriving user from `ws`."""
    username = getattr(ws.state, "username", None)
    if not username:
        return
    call_id = services.pending_calls.get(chatID)
    if not call_id:
        await services.send_to_user(username, {
            "type": "call_error",
            "chatID": chatID,
            "code": "CALL_NOT_FOUND",
        })
        return

    session = services.call_sessions.get(call_id)
    if session:
        session["state"] = "ended"
        services.call_sessions[call_id] = session

    payload = {
        "type": "call_ended",
        "chatID": chatID,
        "call_id": call_id,
        "ended_by": username,
        "initiator": session.get("initiator") if session else None,
    }
    await services.broadcast_call_to_chat_participants(chatID, payload)

    services.pending_calls.pop(chatID, None)
    services.call_sessions.pop(call_id, None)
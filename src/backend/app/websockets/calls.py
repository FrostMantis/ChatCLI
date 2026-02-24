import logging
import uuid
import mariadb
import db_helper as db
import services
from fastapi import WebSocket

logger = logging.getLogger(__name__)

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


## LIVEKIT

from livekit import api
import os

# Use the keys from your LiveKit logs
LIVEKIT_KEY = "devkey"
LIVEKIT_SECRET = "secret"
LIVEKIT_URL = "ws://172.27.27.16:7880"

def generate_livekit_token(username: str, chat_id: str):
    # The room name is the chatID to keep everyone in the same space
    token = api.AccessToken(LIVEKIT_KEY, LIVEKIT_SECRET) \
        .with_identity(username) \
        .with_name(username) \
        .with_grants(api.VideoGrants(
            room_join=True, 
            room=str(chat_id)
        ))
    return token.to_jwt()

async def call_invite(ws, chatID: int):
    caller = getattr(ws.state, "username", None)
    if not caller: return

    # 1. Generate the token for the initiator
    token = generate_lk_token(caller, chatID)

    # 2. Inform the group that a call started
    payload = {
        "type": "call_invite",
        "chatID": chatID,
        "caller": caller,
        "lk_token": token,  # Send token to the person who started it
        "lk_url": LIVEKIT_URL
    }
    
    # Broadcast to everyone in the chat
    await services.broadcast_call_to_chat_participants(chatID, payload)

async def call_accept(ws, chatID: int, call_id: str):
    username = getattr(ws.state, "username", None)
    if not username: return

    # Generate a token for the person joining
    token = generate_lk_token(username, chatID)

    return {
        "type": "call_accepted",
        "chatID": chatID,
        "lk_token": token,
        "lk_url": LIVEKIT_URL
    }
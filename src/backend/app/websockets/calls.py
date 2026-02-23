import logging
import uuid
import mariadb
import db_helper as db
import services
from fastapi import WebSocket

logger = logging.getLogger(__name__)


async def call_invite(ws: WebSocket, chatID: int) -> None:
    """Start a new call in the given chat, deriving caller from `ws`."""
    caller = getattr(ws.state, "username", None)
    if not caller:
        return
    # Basic validation: ensure chat exists and caller is a participant
    try:
        participants_rows = await db.fetch_records(
            table="participants",
            where_clause="chatID = %s",
            params=(chatID,),
        )
        if not participants_rows:
            await services.send_to_user(caller, {
                "type": "call_error",
                "chatID": chatID,
                "code": "CHAT_NOT_FOUND",
            })
            return

        user_row = await db.fetch_records(
            table="users",
            where_clause="username = %s AND disabled = FALSE AND deleted = FALSE",
            params=(caller,),
            fetch_all=False,
        )
        if not user_row or user_row["userID"] not in [row["userID"] for row in participants_rows]:
            await services.send_to_user(caller, {
                "type": "call_error",
                "chatID": chatID,
                "code": "NOT_IN_CHAT",
            })
            return
    except mariadb.Error as e:
        logger.error("DB error in call_invite for %s in chat %s: %s", caller, chatID, e, exc_info=e)
        await services.send_to_user(caller, {
            "type": "call_error",
            "chatID": chatID,
            "code": "INTERNAL_ERROR",
        })
        return

    # Check if a call is already pending/active for this chat
    existing_cid = services.pending_calls.get(chatID)
    if existing_cid:
        existing = services.call_sessions.get(existing_cid)
        if existing and existing.get("state") != "ended":
            await services.send_to_user(caller, {
                "type": "call_error",
                "chatID": chatID,
                "code": "CHAT_BUSY",
            })
            return

    # Create new call session
    call_id = str(uuid.uuid4())
    services.call_sessions[call_id] = {
        "chatID": chatID,
        "initiator": caller,
        "state": "ringing",
    }
    services.pending_calls[chatID] = call_id

    # Notify the entire chat (group or private)
    payload = {
        "type": "call_state",
        "chatID": chatID,
        "call_id": call_id,
        "initiator": caller,
        "state": "ringing",
    }
    logger.debug(f"Broadcasting call invite in chat {chatID} with call_id {call_id} by {caller}")
    await services.broadcast_call_to_chat_participants(chatID, payload)


async def call_accept(ws: WebSocket, chatID: int, call_id: str) -> None:
    """Accept a pending call for the given chat and call id, deriving user from `ws`."""
    username = getattr(ws.state, "username", None)
    if not username:
        return
    current_cid = services.pending_calls.get(chatID)
    if not current_cid or current_cid != call_id:
        await services.send_to_user(username, {
            "type": "call_error",
            "chatID": chatID,
            "call_id": call_id,
            "code": "CALL_NOT_FOUND",
        })
        return

    session = services.call_sessions.get(call_id)
    if not session:
        await services.send_to_user(username, {
            "type": "call_error",
            "chatID": chatID,
            "call_id": call_id,
            "code": "CALL_NOT_FOUND",
        })
        return

    if session.get("chatID") != chatID:
        await services.send_to_user(username, {
            "type": "call_error",
            "chatID": chatID,
            "call_id": call_id,
            "code": "CALL_CHAT_MISMATCH",
        })
        return

    state = session.get("state")
    if state != "ringing":
        await services.send_to_user(username, {
            "type": "call_error",
            "chatID": chatID,
            "call_id": call_id,
            "code": "CALL_NOT_RINGING",
            "state": state,
        })
        return

    # Mark the call as active
    session["state"] = "active"
    services.call_sessions[call_id] = session

    # Broadcast updated state to the whole chat
    await services.broadcast_call_to_chat_participants(chatID, {
        "type": "call_state",
        "chatID": chatID,
        "call_id": call_id,
        "initiator": session.get("initiator"),
        "state": "active",
    })

    # Optional explicit accepted event
    await services.broadcast_call_to_chat_participants(chatID, {
        "type": "call_accepted",
        "chatID": chatID,
        "call_id": call_id,
        "accepted_by": username,
        "initiator": session.get("initiator"),
    })


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
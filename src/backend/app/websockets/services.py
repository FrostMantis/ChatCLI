import logging
import hashlib
import mariadb
from fastapi import WebSocket, status
from db_helper import fetch_records, insert_record, update_records
from datetime import datetime
import calls

logger = logging.getLogger(__name__)

# In-memory connection & subscription registries
active_connections: dict[str, WebSocket] = {} # username -> WebSocket ; stores all active ws connections
active_call_connections: dict[str, WebSocket] = {} # username -> WebSocket ; stores all active call ws connectionsabout:blank#blocked
chat_subscriptions: dict[int, set[WebSocket]] = {} # chatID -> set of WebSockets ; stores ws connections subscribed to each chat
idle_subscriptions: set[WebSocket] = set() # stores ws connections subscribed to idle notifications
pending_calls: dict[int, dict] = {} # chatID -> call_id ; stores pending call IDs per chat
call_sessions: dict[str, dict] = {} # call_id -> session dict ; stores active call sessions
user_status: dict[str, bool] = {} # username -> online status (True/False)

def reset_variables():
    """
    Resets all in-memory variables. Used on server startup.
    """
    global active_connections, chat_subscriptions, idle_subscriptions, pending_calls, call_sessions, user_status
    active_connections = {}
    chat_subscriptions = {}
    idle_subscriptions = set()
    pending_calls = {}
    call_sessions = {}
    user_status = {}

async def authenticate(websocket: WebSocket, msg: dict) -> str | None:
    """
    Token-only auth handshake over WebSocket.
    """
    # Validate payload
    if msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    # Hash token
    token_plain = msg["token"]
    token_hash = hashlib.sha256(token_plain.encode()).hexdigest()

    # Lookup session
    try:
        sessions = await fetch_records(
            table="session_tokens",
            where_clause="session_token = %s AND revoked = FALSE AND expires_at > CURRENT_TIMESTAMP()",
            params=(token_hash,),
            fetch_all=True
        )
    except mariadb.Error as e:
        logger.error("DB error during session lookup: %s", e, exc_info=e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return None
    except Exception as e:
        logger.error("Unexpected error during session lookup: %s", e, exc_info=e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return None

    if not sessions:
        logger.warning("Invalid or expired session token.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    user_id = sessions[0]["userID"]

    # Fetch user record
    try:
        users = await fetch_records(
            table="users",
            where_clause="userID = %s AND disabled = FALSE AND deleted = FALSE",
            params=(user_id,),
            fetch_all=True
        )
    except mariadb.Error as e:
        logger.error("DB error during user lookup: %s", e, exc_info=e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return None
    except Exception as e:
        logger.error("Unexpected error during user lookup: %s", e, exc_info=e)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return None

    if not users:
        logger.error("Session valid but no active user found (userID=%s).", user_id)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return None

    username = users[0]["username"]
    
    websocket.state.username = username
    logger.info("User authenticated: %s (userID=%s)", username, user_id)
    return username

async def join_chat(ws: WebSocket, chatID: int):
    username = getattr(ws.state, "username", None)
    if not username:
        return {"type": "error", "message": "Unauthenticated."}
    participant = await fetch_records(
        table="participants",
        where_clause="chatID = %s AND userID = (SELECT userID FROM users WHERE username = %s)",
        params=(chatID, username),
        fetch_all=True
    )
    if not participant:
        return { "type": "error", "message": "Access denied for this chat." }
    try:
        chat_subscriptions.setdefault(chatID, set()).add(ws)
        await emit_call_state(ws, chatID)
    except Exception as e:
        logger.error("Error adding %s to chat %s: %s", username, chatID, e, exc_info=e)

async def leave_chat(ws: WebSocket, chatID: int):
    username = getattr(ws.state, "username", None)
    try:
        chat_subscriptions.get(chatID, set()).discard(ws)
        logger.debug("%s left chat %s", username, chatID)
    except Exception as e:
        logger.error("Error removing %s from chat %s: %s", username, chatID, e, exc_info=e)

async def post_msg(ws: WebSocket, chatID: int, text, messageID = 0) -> dict | None:
    """
    Inserts and broadcasts a message. Returns the payload or error payload dict.
    """
    username = getattr(ws.state, "username", None)
    if not username or chatID is None or text is None:
        return {"type": "error", "message": "Invalid message content."}

    logger.debug("post_msg called: username=%s, chatID=%s, messageID=%s", username, chatID, messageID)

    users = await fetch_records("users", "username = %s", (username,), True)
    if not users: return {"type": "error", "message": "User not found."}
    user_id = users[0]["userID"]

    if messageID != 0:
        existing = await fetch_records("messages", "messageID = %s", (messageID,), True)
        if not existing:
            return {"type": "error", "message": "Message not found."}
        if existing[0]["userID"] != user_id:
            return {"type": "error", "message": "Unauthorized: You can only edit your own messages."}
        return_type = "edited_message"
    else:
        participant = await fetch_records("participants", "chatID=%s AND userID=%s", (chatID, user_id), True)
        if not participant:
            return {"type": "error", "message": "Access denied."}
        return_type = "new_message"

    try:
        if messageID == 0:
            messageID = await insert_record("messages", {"chatID": chatID, "userID": user_id, "message": text})
        else:
            await update_records("messages", {"message": text, "edited_at": datetime.now()}, "messageID=%s", (messageID,))

        rows = await fetch_records(
            table="messages",
            where_clause="messageID = %s",
            params=(messageID,),
            fetch_all=True
        )

        if not rows:
            return None
        row = rows[0]

        # Helper to safely convert datetime to ISO format
        def to_iso(dt_obj):
            if dt_obj is None:
                return None
            if isinstance(dt_obj, datetime):
                return dt_obj.isoformat()
            return str(dt_obj)

        payload = {
            "type": return_type,
            "messageID": row["messageID"],
            "chatID": row["chatID"],
            "userID": row["userID"],
            "username": username,
            "message": row["message"],
            "timestamp": to_iso(row["timestamp"]),
            "edited_at": to_iso(row["edited_at"]),
            "deleted_at": to_iso(row["deleted_at"])
        }
        await broadcast_chat(chatID, payload)
        return payload
    except Exception as e:
        logger.error("Error processing message: %s", e)
        return {"type": "error", "message": "Database error."}

async def broadcast_typing(ws: WebSocket, chatID: int):
    username = getattr(ws.state, "username", None)
    if not username:
        return
    payload = {"type": "user_typing", "username": username, "chatID": chatID}
    await broadcast_chat(chatID, payload, exclude_ws={ws})

async def notify_status(username: str, is_online: bool):
    """
    Notify only users related to the given user about their status change.
    Updates the global user_status dictionary.
    """
    try:
        # Update the user_status dictionary
        user_status[username] = is_online

        # Fetch all chat IDs the user is part of
        user_chats = await fetch_records(
            table="participants",
            where_clause="userID = (SELECT userID FROM users WHERE username = %s)",
            params=(username,),
            fetch_all=True
        )
        chatIDs = {row["chatID"] for row in user_chats}

        # Fetch all usernames of participants in those chats
        related_users = set()
        for chatID in chatIDs:
            participants = await fetch_records(
                table="participants",
                where_clause="chatID = %s",
                params=(chatID,),
                fetch_all=True
            )
            related_users.update(
                row["userID"] for row in participants if row["userID"] != username
            )

        # Fetch usernames for related user IDs
        related_usernames = []
        for user_id in related_users:
            user_row = await fetch_records(
                table="users",
                where_clause="userID = %s AND disabled = FALSE AND deleted = FALSE",
                params=(user_id,),
                fetch_all=False
            )
            if user_row:
                related_usernames.append(user_row["username"])

        # Notify only related users
        payload = {"type": "user_status", "username": username, "online": is_online}
        for related_username in related_usernames:
            ws = active_connections.get(related_username)
            if ws:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Removing dead connection for %s: %s", related_username, e)
                    active_connections.pop(related_username, None)
    except Exception as e:
        logger.error("Failed to notify status for %s: %s", username, e, exc_info=e)

async def get_online_users_for_user(username: str) -> list[str]:
    """
    Get a list of online users who share common chats with the given user.
    """
    try:
        # Fetch all chat IDs the user is part of
        user_chats = await fetch_records(
            table="participants",
            where_clause="userID = (SELECT userID FROM users WHERE username = %s)",
            params=(username,),
            fetch_all=True
        )
        chatIDs = {row["chatID"] for row in user_chats}

        # Fetch all usernames of participants in those chats
        related_users = set()
        for chatID in chatIDs:
            participants = await fetch_records(
                table="participants",
                where_clause="chatID = %s",
                params=(chatID,),
                fetch_all=True
            )
            related_users.update(
                row["userID"] for row in participants if row["userID"] != username
            )

        # Fetch usernames for related user IDs
        online_users = []
        for user_id in related_users:
            user_row = await fetch_records(
                table="users",
                where_clause="userID = %s AND disabled = FALSE AND deleted = FALSE",
                params=(user_id,),
                fetch_all=False
            )
            if user_row and user_status.get(user_row["username"], False):
                online_users.append(user_row["username"])

        return online_users
    except Exception as e:
        logger.error("Failed to get online users for %s: %s", username, e, exc_info=e)
        return []

async def send_to_user(username: str, payload: dict) -> bool:
    """
    Best-effort send to a specific online user.
    Returns True if a connection existed and we attempted a send.
    """
    ws = active_connections.get(username)
    if not ws:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception as e:
        logger.warning("Dropping dead connection for %s: %s", username, e)
        active_connections.pop(username, None)
        return False

async def broadcast_chat(
    chatID: int,
    payload: dict,
    exclude_users: set[str] | None = None,
    exclude_ws: set | None = None,
) -> None:
    """
    Send to everyone currently subscribed to chatID, excluding:
      - any usernames in exclude_users (mapped via active_connections)
      - any websocket objects in exclude_ws
    """
    subs = chat_subscriptions.get(chatID, set())
    if not subs:
        return

    exc_ws = set(exclude_ws or ())
    if exclude_users:
        for u in exclude_users:
            ws = active_connections.get(u)
            if ws:
                exc_ws.add(ws)

    for ws in set(subs):
        if ws in exc_ws:
            continue
        try:
            await ws.send_json(payload)
        except Exception as e:
            logger.warning("Removing dead connection in chat %s: %s", chatID, e)
            subs.discard(ws)

async def emit_call_state(ws: WebSocket, chatID: int) -> None:
    """Send current call state for a chat to a single websocket, if any."""
    call_id = pending_calls.get(chatID)
    if not call_id:
        return
    session = call_sessions.get(call_id)
    if not session:
        return
    return {
        "type": "call_state",
        "chatID": chatID,
        "call_id": call_id,
        "initiator": session.get("initiator"),
        "state": session.get("state", "ringing"),
    }

async def broadcast_chat_created(ws: WebSocket, chatID: int):
    """
    Broadcast 'chat_created' to all participants of the chat except the creator.
    """
    try:
        creator_username = getattr(ws.state, "username", None)
        # Step 1: fetch userIDs of participants
        participants_rows = await fetch_records(
            table="participants",
            where_clause="chatID = %s",
            params=(chatID,)
        )
        if not participants_rows:
            return

        user_ids = [row["userID"] for row in participants_rows]

        # Step 2: fetch usernames for those userIDs
        usernames = []
        for uid in user_ids:
            user_row = await fetch_records(
                table="users",
                where_clause="userID = %s AND disabled = FALSE AND deleted = FALSE",
                params=(uid,),
                fetch_all=False
            )
            if user_row:
                usernames.append(user_row["username"])

        payload = {
            "type": "chat_created",
            "chatID": chatID,
            "creator": creator_username,
        }

        for username in usernames:
            if username == creator_username:
                continue
            peer_ws = active_connections.get(username)
            if peer_ws:
                try:
                    await peer_ws.send_json(payload)
                except Exception as e:
                    logging.warning("Failed to send chat_created to %s: %s", username, e)
                    active_connections.pop(username, None)

    except Exception as e:
        logging.error("Failed to broadcast chat_created: %s", e)

async def cleanup_connection(username: str, ws: WebSocket) -> None:
    """
    Remove this websocket from all registries and mark the user offline.
    Safe to call even if things are already partially cleaned up.
    """
    # Remove from all chat subscriptions
    for subs in chat_subscriptions.values():
        subs.discard(ws)

    # Remove from idle subscriptions
    idle_subscriptions.discard(ws)

    # Remove from active_connections *only if* this ws is still the one stored
    current_ws = active_connections.get(username)
    if current_ws is ws:
        active_connections.pop(username, None)

    # Notify others the user is offline (also updates user_status)
    try:
        await notify_status(username, is_online=False)
    except Exception as e:
        logger.error("Failed to notify status for %s: %s", username, e, exc_info=e)

async def get_chat_participant_usernames(chatID: int) -> list[str]:
  try:
    participants_rows = await fetch_records(
      table="participants",
      where_clause="chatID = %s",
      params=(chatID,),
      fetch_all=True,
    )
    if not participants_rows:
      return []

    usernames: list[str] = []
    for row in participants_rows:
      user_row = await fetch_records(
        table="users",
        where_clause="userID = %s AND disabled = FALSE AND deleted = FALSE",
        params=(row["userID"],),
        fetch_all=False,
      )
      if user_row:
        usernames.append(user_row["username"])
    return usernames
  except Exception as e:
    logger.error("Failed to get usernames for chat %s: %s", chatID, e, exc_info=e)
    return []

async def broadcast_call_to_chat_participants(chatID: int, payload: dict) -> None:
  """
  Send payload to all ONLINE participants of this chat, via active_connections.
  Does not depend on chat_subscriptions / join_chat.
  """
  usernames = await get_chat_participant_usernames(chatID)
  for username in usernames:
    ws = active_connections.get(username)
    if not ws:
      continue
    try:
      await ws.send_json(payload)
    except Exception as e:
      logger.warning("Removing dead connection for %s: %s", username, e)
      active_connections.pop(username, None)

async def delete_msg(ws: WebSocket, chatID: int, messageID: int) -> dict | None:
    """
    Marks a message as deleted (soft delete) and broadcasts the change.
    """
    username = getattr(ws.state, "username", None)
    logger.debug("delete_msg called: username=%s, chatID=%s, messageID=%s", username, chatID, messageID)
    if not username or chatID is None or messageID is None:
        return {"type": "error", "message": "Invalid request parameters."}

    users = await fetch_records("users", "username = %s", (username,), True)
    if not users: 
        return {"type": "error", "message": "User not found."}
    user_id = users[0]["userID"]

    existing = await fetch_records("messages", "messageID = %s AND chatID = %s", (messageID, chatID), True)
    if not existing:
        return {"type": "error", "message": "Message not found."}
    
    msg_record = existing[0]

    if msg_record["userID"] != user_id:
        return {"type": "error", "message": "Unauthorized: You can only delete your own messages."}
    
    if msg_record["deleted_at"] is not None:
        return {"type": "error", "message": "Message is already deleted."}

    try:
        now = datetime.now()
        await update_records(
            table="messages", 
            data={"message": "--deleted--","deleted_at": now}, 
            where_clause="messageID = %s", 
            params=(messageID,)
        )

        payload = {
            "type": "deleted_message",
            "messageID": messageID,
            "chatID": chatID,
            "deleted_at": now.isoformat()
        }

        await broadcast_chat(chatID, payload)
        return payload

    except Exception as e:
        logger.error("Error deleting message %s: %s", messageID, e)
        return {"type": "error", "message": "Database error during deletion."}


# Call wrappers that accept a WebSocket and forward to the calls module
async def call_invite(ws: WebSocket, chatID: int):
    return await calls.call_invite(ws, chatID)

async def call_accept(ws: WebSocket, chatID: int, call_id: str):
    return await calls.call_accept(ws, chatID, call_id)

async def call_decline(ws: WebSocket, chatID: int):
    return await calls.call_decline(ws, chatID)

async def call_end(ws: WebSocket, chatID: int):
    return await calls.call_end(ws, chatID)
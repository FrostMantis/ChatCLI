import mariadb
from flask import current_app

from app.errors import BadRequest, Unauthorized, Forbidden, NotFound, Conflict, APIError
from app.services.base_services import authenticate_token
from app.database.db_helper import (
    transactional,
    fetch_records,
    get_db,
)


def fetch_chats(data: dict) -> dict:
    """
    data: { session_token: str }
    Returns: { response: [ { chatID, name, type }, ... ] }
    """
    session_token = data.get("session_token")
    if not session_token:
        raise BadRequest("Session token is required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Unable to verify user!")

    # fetch user ID
    users = fetch_records(
        table="users",
        where_clause="LOWER(username) = %s",
        params=(username.lower(),),
        fetch_all=True
    )
    if not users:
        raise NotFound("User not found.")
    user_id = users[0]["userID"]

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT chatID FROM participants WHERE userID = %s AND archived = 0",
            (user_id,)
        )
        chat_ids = [r[0] for r in cur.fetchall()]
    except Exception as e:
        current_app.logger.error("DB error fetching chat IDs", exc_info=e)
        raise APIError()

    if not chat_ids:
        return {"response": []}

    # fetch chat metadata
    fmt = ",".join(["%s"] * len(chat_ids))
    chats = fetch_records(
        table="chats",
        where_clause=f"chatID IN ({fmt})",
        params=tuple(chat_ids),
        fetch_all=True
    )
    group_map = {c["chatID"]: c.get("group_name") for c in chats if c["type"] == "group"}
    private_ids = [c["chatID"] for c in chats if c["type"] == "private"]

    chat_to_user = {}
    id_to_name = {}
    if private_ids:
        fmt2 = ",".join(["%s"] * len(private_ids))
        others = fetch_records(
            table="participants",
            where_clause=f"chatID IN ({fmt2}) AND userID != %s",
            params=(*private_ids, user_id),
            fetch_all=True
        )
        chat_to_user = {r["chatID"]: r["userID"] for r in others}
        user_ids = list(chat_to_user.values())
        if user_ids:
            fmt3 = ",".join(["%s"] * len(user_ids))
            rows = fetch_records(
                table="users",
                where_clause=f"userID IN ({fmt3})",
                params=tuple(user_ids),
                fetch_all=True
            )
            id_to_name = {r["userID"]: r["username"] for r in rows}

    response = []
    for cid in chat_ids:
        if cid in group_map:
            response.append({"chatID": cid, "name": group_map[cid], "type": "group"})
        else:
            peer = chat_to_user.get(cid)
            response.append({"chatID": cid, "name": id_to_name.get(peer, "Unknown"), "type": "private"})

    return {"response": response}


def get_messages(data: dict) -> dict:
    """
    data: { session_token: str, chatID: int, limit (optional) }
    Returns: { messages: [ ... ] }
    """
    username = (data.get("username") or "").lower()
    session_token = data.get("session_token")
    chat_id = data.get("chatID")
    limit = data.get("limit", 50)

    # validate inputs
    if not session_token or chat_id is None:
        raise BadRequest("session_token and chatID are required.")
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        raise BadRequest("limit must be an integer.")
    if limit < 1 or limit > 200:
        raise BadRequest("limit must be between 1 and 200.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Unable to verify user!")

    user_lower = username.lower()
    # check participation
    try:
        parts = fetch_records(
            table="participants",
            where_clause="chatID = %s AND userID = (SELECT userID FROM users WHERE LOWER(username) = %s)",
            params=(chat_id, user_lower),
            fetch_all=True
        )
    except mariadb.Error as e:
        current_app.logger.error("DB error checking participants", exc_info=e)
        raise APIError()
    if not parts:
        raise NotFound("Chat not found or access denied.")

    # fetch messages
    try:
        rows = fetch_records(
            table="messages",
            where_clause="chatID = %s",
            params=(chat_id,),
            order_by="timestamp DESC",
            limit=limit,
            fetch_all=True
        )
    except mariadb.Error as e:
        current_app.logger.error("DB error fetching messages", exc_info=e)
        raise APIError()

    user_ids = list({r["userID"] for r in rows})
    id_to_username = {}
    if user_ids:
        fmt = ",".join(["%s"] * len(user_ids))
        users = fetch_records(
            table="users",
            where_clause=f"userID IN ({fmt})",
            params=tuple(user_ids),
            fetch_all=True
        )
        id_to_username = {r["userID"]: r["username"] for r in users}

    messages = [
        {
            "messageID": r["messageID"],
            "userID": r["userID"],
            "username": id_to_username.get(r["userID"], "unknown"),
            "message": r["message"],
            "timestamp": r["timestamp"].isoformat(),
            "edited_at": r["edited_at"].isoformat() if r["edited_at"] else None,
            "deleted_at": r["deleted_at"].isoformat() if r["deleted_at"] else None
        }
        for r in reversed(rows)
    ]

    return {"messages": messages}


@transactional
def archive_chat(data: dict) -> dict:
    """
    data: { session_token: str, chatID: int }
    Returns: { message: str }
    """
    session_token = data.get("session_token")
    chat_id = data.get("chatID")
    if not session_token or chat_id is None:
        raise BadRequest("Session token and chatID are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Unable to verify user!")

    users = fetch_records(
        table="users",
        where_clause="LOWER(username) = %s",
        params=(username.lower(),),
        fetch_all=True
    )
    if not users:
        raise NotFound("User not found.")
    user_id = users[0]["userID"]

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE participants SET archived = 1 WHERE chatID = %s AND userID = %s",
            (chat_id, user_id)
        )
        conn.commit()
    except Exception as e:
        current_app.logger.error("Error archiving chat", exc_info=e)
        raise APIError()

    return {"message": "Chat archived"}


def get_members(data: dict) -> dict:
    """
    data: { session_token: str, chatID: int }
    Returns: { members: [username, ...] }
    """
    session_token = data.get("session_token")
    chat_id = data.get("chatID")
    if not session_token or chat_id is None:
        raise BadRequest("session_token and chatID are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Invalid session token.")

    grp = fetch_records(
        table="chats",
        where_clause="chatID=%s AND type='group'",
        params=(chat_id,),
        fetch_all=True
    )
    if not grp:
        raise NotFound("Group not found.")
    
    parts_self = fetch_records(
    table="participants",
    where_clause="chatID = %s AND userID = (SELECT userID FROM users WHERE LOWER(username) = %s)",
    params=(chat_id, username.lower()),
    fetch_all=True
    )
    if not parts_self:
        raise NotFound("Chat not found or access denied.")

    parts = fetch_records(
        table="participants",
        where_clause="chatID=%s",
        params=(chat_id,),
        fetch_all=True
    )
    ids = [p["userID"] for p in parts]
    if not ids:
        return {"members": []}

    fmt = ",".join(["%s"] * len(ids))
    users = fetch_records(
        table="users",
        where_clause=f"userID IN ({fmt})",
        params=tuple(ids),
        fetch_all=True
    )
    names = [u["username"] for u in users]
    return {"members": names}


@transactional
def add_participant(data: dict) -> dict:
    """
    data: { session_token: str, chatID: int, members: [str, ...] }
    Returns: { chatID: int }
    """
    session_token = data.get("session_token")
    chat_id = data.get("chatID")
    new_users = data.get("members", [])

    if not session_token or chat_id is None or not isinstance(new_users, list) or not new_users:
        raise BadRequest("session_token, chatID and members list are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Invalid session token.")

    grp = fetch_records(
        table="chats",
        where_clause="chatID=%s AND type='group'",
        params=(chat_id,),
        fetch_all=True
    )
    if not grp:
        raise NotFound("Group not found.")

    placeholders = ",".join(["%s"] * len(new_users))
    rows = fetch_records(
        table="users",
        where_clause=f"LOWER(username) IN ({placeholders})",
        params=tuple(u.lower() for u in new_users),
        fetch_all=True
    )
    if len(rows) != len(new_users):
        raise NotFound("One or more users not found.")
    user_ids = [r["userID"] for r in rows]

    conn = get_db()
    cur = conn.cursor()
    for uid in set(user_ids):
        try:
            cur.execute(
                "INSERT INTO participants (chatID, userID) VALUES (%s,%s)",
                (chat_id, uid)
            )
        except mariadb.Error:
            pass
    conn.commit()

    return {"chatID": chat_id}


@transactional
def remove_participant(data: dict) -> dict:
    """
    data: { session_token: str, chatID: int, members: [str, ...] }
    Returns: { chatID: int }
    """
    session_token = data.get("session_token")
    chat_id = data.get("chatID")
    rem_users = data.get("members", [])

    if not session_token or chat_id is None or not isinstance(rem_users, list) or not rem_users:
        raise BadRequest("session_token, chatID and members list are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Invalid session token.")

    grp = fetch_records(
        table="chats",
        where_clause="chatID=%s AND type='group'",
        params=(chat_id,),
        fetch_all=True
    )
    if not grp:
        raise NotFound("Group not found.")

    placeholders = ",".join(["%s"] * len(rem_users))
    rows = fetch_records(
        table="users",
        where_clause=f"LOWER(username) IN ({placeholders})",
        params=tuple(u.lower() for u in rem_users),
        fetch_all=True
    )
    if len(rows) != len(rem_users):
        raise NotFound("One or more users not found.")
    user_ids = [r["userID"] for r in rows]

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"DELETE FROM participants WHERE chatID=%s AND userID IN ({placeholders})",
        (chat_id, *user_ids)
    )
    conn.commit()

    return {"chatID": chat_id}


@transactional
def _create_chat_logic(sender_id: int, receiver_id: int) -> int:
    """
    Internal: ensures a private chat exists, reactivates if archived.
    Returns chatID.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT c.chatID
        FROM chats c
        JOIN participants p1 ON c.chatID = p1.chatID AND p1.userID = %s
        JOIN participants p2 ON c.chatID = p2.chatID AND p2.userID = %s
        WHERE c.type = 'private'
        """,
        (sender_id, receiver_id)
    )
    row = cursor.fetchone()
    if row:
        chat_id = row[0]
        cursor.execute(
            """
            UPDATE participants
            SET archived = 0
            WHERE chatID = %s AND userID IN (%s, %s)
            """,
            (chat_id, sender_id, receiver_id)
        )
        return chat_id

    cursor.execute("INSERT INTO chats (type) VALUES ('private')")
    chat_id = cursor.lastrowid
    for uid in (sender_id, receiver_id):
        cursor.execute(
            "INSERT INTO participants (chatID, userID) VALUES (%s,%s)",
            (chat_id, uid)
        )
    return chat_id


def create_chat(data: dict) -> dict:
    """
    data: { session_token: str, receiver: str }
    Returns: { chatID: int }
    """
    session_token = data.get("session_token")
    receiver = (data.get("receiver") or "").lower()
    if not session_token or not receiver:
        raise BadRequest("Session token and receiver are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Unable to verify user!")
    if username.lower() == receiver:
        raise BadRequest("Cannot chat with yourself.")

    try:
        sender = fetch_records(
            table="users",
            where_clause="LOWER(username) = %s",
            params=(username.lower(),),
            fetch_all=True
        )
        rec = fetch_records(
            table="users",
            where_clause="LOWER(username) = %s",
            params=(receiver,),
            fetch_all=True
        )
        if not sender or not rec:
            raise NotFound("User not found.")
        chat_id = _create_chat_logic(sender[0]["userID"], rec[0]["userID"])
    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error creating chat", exc_info=e)
        raise APIError()

    return {"chatID": chat_id}


@transactional
def _create_group_logic(owner_id: int, group_name: str, member_ids: list[int]) -> int:
    """
    Internal: creates a group chat and adds participants.
    Returns chatID.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO chats (type, group_name) VALUES ('group', %s)",
        (group_name,)
    )
    chat_id = cursor.lastrowid
    for uid in {owner_id, *member_ids}:
        cursor.execute(
            "INSERT INTO participants (chatID, userID) VALUES (%s,%s)",
            (chat_id, uid)
        )
    return chat_id


def create_group(data: dict) -> dict:
    """
    data: { session_token: str, name: str, members: [str, ...] }
    Returns: { chatID: int }
    """
    session_token = data.get("session_token")
    name = (data.get("name") or "").strip()
    members = data.get("members")
    if not session_token or not name or not isinstance(members, list) or not members:
        raise BadRequest("token, name and members list are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Invalid session token.")

    try:
        owner = fetch_records(
            table="users",
            where_clause="LOWER(username) = %s",
            params=(username.lower(),),
            fetch_all=True
        )
        if not owner:
            raise NotFound("User not found.")
        ph = ",".join(["%s"] * len(members))
        rows = fetch_records(
            table="users",
            where_clause=f"LOWER(username) IN ({ph})",
            params=tuple(u.lower() for u in members),
            fetch_all=True
        )
        if len(rows) != len(members):
            raise NotFound("One or more members not found.")
        member_ids = [r["userID"] for r in rows]
        chat_id = _create_group_logic(owner[0]["userID"], name, member_ids)
    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error creating group", exc_info=e)
        raise APIError()

    return {"chatID": chat_id}


def fetch_archived(data: dict) -> dict:
    """
    data: { session_token: str }
    Returns: { response: [ { chatID, name, type }, ... ] }
    """
    session_token = data.get("session_token")
    if not session_token:
        raise BadRequest("Session token is required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Unable to verify user!")

    users = fetch_records(
        table="users",
        where_clause="LOWER(username) = %s",
        params=(username.lower(),),
        fetch_all=True
    )
    if not users:
        raise NotFound("User not found.")
    user_id = users[0]["userID"]

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.chatID, 'group' AS type, c.group_name AS name
            FROM participants p
            JOIN chats c ON c.chatID = p.chatID
            WHERE p.userID = %s AND p.archived = 1 AND c.type = 'group'
        """, (user_id,))
        group_rows = cur.fetchall()

        cur.execute("""
            SELECT p.chatID, 'private' AS type, u.username AS name
            FROM participants p
            JOIN chats c ON c.chatID = p.chatID AND c.type = 'private'
            JOIN participants pu ON pu.chatID = p.chatID AND pu.userID != %s
            JOIN users u ON u.userID = pu.userID
            WHERE p.userID = %s AND p.archived = 1
        """, (user_id, user_id))
        private_rows = cur.fetchall()
    except Exception as e:
        current_app.logger.error("DB error fetching archived chats", exc_info=e)
        raise APIError()

    all_rows = group_rows + private_rows
    if not all_rows:
        return {"response": []}

    response = [
        {"chatID": row[0], "type": row[1], "name": row[2]} for row in all_rows
    ]
    return {"response": response}


def unarchive_chat(data: dict) -> dict:
    """
    data: { session_token: str, chatID: int }
    Returns: { message: str }
    """
    session_token = data.get("session_token")
    chat_id = data.get("chatID")
    if not session_token or chat_id is None:
        raise BadRequest("Session token and chatID are required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Unable to verify user!")

    users = fetch_records(
        table="users",
        where_clause="LOWER(username) = %s",
        params=(username.lower(),),
        fetch_all=True
    )
    if not users:
        raise NotFound("User not found.")
    user_id = users[0]["userID"]

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE participants SET archived = 0 WHERE chatID = %s AND userID = %s",
            (chat_id, user_id)
        )
        conn.commit()
    except Exception as e:
        current_app.logger.error("Error unarchiving chat", exc_info=e)
        raise APIError()

    return {"message": "Chat unarchived"}
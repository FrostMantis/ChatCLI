from fastapi import WebSocket
import services
import logging

logger = logging.getLogger(__name__)

async def handle_message(username: str, ws: WebSocket, msg: dict) -> None:
    """
    Route a single inbound WebSocket message for a given user.
    """
    logger.debug("Received message for %s: %s", username, msg)

    try:
        match msg:
            # ----- CHAT MESSAGES / PRESENCE -----

            case {"type": "join_chat", "chatID": chatID}:
                await services.join_chat(username, chatID, ws)

            case {"type": "leave_chat", "chatID": chatID}:
                await services.leave_chat(username, chatID, ws)

            case {"type": "post_msg", "chatID": chatID, "text": text} if isinstance(text, str):
                payload = await services.post_msg(username, chatID, text, ws)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "typing", "chatID": chatID}:
                await services.broadcast_typing(username, chatID)

            case {"type": "chat_created", "chatID": chatID, "creator": creator}:
                payload = await services.broadcast_chat_created(chatID, creator)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "join_idle"}:
                services.idle_subscriptions.add(ws)

            case {"type": "edit_msg", "chatID": chatID, "messageID": messageID, "text": text}:
                payload = await services.post_msg(username, chatID, text, ws, messageID)
                if payload:
                    await ws.send_json(payload)

            case {"type": "edit_msg", "chatID" : chatID, "messageID" : messageID}:
                services.delete_msg(ws, chatID, messageID)
        
            # ----- CALLING CASES -----

            case {"type": "call_invite", "chatID": chatID}:
                payload = await services.calls.call_invite(caller=username, chatID=chatID)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "call_accept", "chatID": chatID, "call_id": call_id}:
                payload = await services.calls.call_accept(username=username, chatID=chatID, call_id=call_id)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "call_decline", "chatID": chatID}:
                payload = await services.calls.call_decline(username=username, chatID=chatID)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "call_end", "chatID": chatID}:
                payload = await services.calls.call_end(username=username, chatID=chatID)
                if payload is not None:
                    await ws.send_json(payload)

            # ----- FALLBACKS -----

            # Known shape but unsupported action
            case {"type": action}:
                raise ValueError(f"Unknown action: {action}")

            # Completely invalid payload
            case _:
                raise ValueError("Invalid message payload")

    except ValueError as ve:
        logger.warning("Value error for user %s: %s", username, ve)
        try:
            await ws.send_json({"type": "error", "message": str(ve)})
        except RuntimeError:
            # WebSocket already closed; nothing else to do
            pass
    except Exception as e:
        logger.error("Error handling message for %s: %s", username, e, exc_info=e)
        try:
            await ws.send_json({"type": "error", "message": "Internal server error"})
        except RuntimeError:
            # WebSocket already closed
            pass
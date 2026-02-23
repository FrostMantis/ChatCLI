from fastapi import WebSocket
import services
import logging

logger = logging.getLogger(__name__)

async def handle_message(ws: WebSocket, msg: dict) -> None:
    """
    Route a single inbound WebSocket message for a given user.
    """
    username = getattr(ws.state, "username", None)
    logger.debug("Received message for %s: %s", username, msg)

    try:
        match msg:
            # ----- CHAT MESSAGES / PRESENCE -----

            case {"type": "join_chat", "chatID": chatID}:
                await services.join_chat(ws, chatID)

            case {"type": "leave_chat", "chatID": chatID}:
                await services.leave_chat(ws, chatID)

            case {"type": "post_msg", "chatID": chatID, "text": text} if isinstance(text, str):
                payload = await services.post_msg(ws, chatID, text)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "typing", "chatID": chatID}:
                await services.broadcast_typing(ws, chatID)

            case {"type": "chat_created", "chatID": chatID}:
                payload = await services.broadcast_chat_created(ws, chatID)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "join_idle"}:
                services.idle_subscriptions.add(ws)

            case {"type": "edit_msg", "chatID": chatID, "messageID": messageID, "text": text}:
                logger.debug("Handling edit_msg: chatID=%s, messageID=%s", chatID, messageID)
                payload = await services.post_msg(ws, chatID, text, messageID)

            case {"type": "delete_msg", "chatID": chatID, "messageID": messageID}:
                logger.debug("Handling delete_msg: chatID=%s, messageID=%s", chatID, messageID)
                payload = await services.delete_msg(ws, chatID, messageID)
        
            # ----- CALLING CASES -----

            case {"type": "call_invite", "chatID": chatID}:
                payload = await services.call_invite(ws, chatID)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "call_accept", "chatID": chatID, "call_id": call_id}:
                payload = await services.call_accept(ws, chatID, call_id)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "call_decline", "chatID": chatID}:
                payload = await services.call_decline(ws, chatID)
                if payload is not None:
                    await ws.send_json(payload)

            case {"type": "call_end", "chatID": chatID}:
                payload = await services.call_end(ws, chatID)
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
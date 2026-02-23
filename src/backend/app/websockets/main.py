import logging
import asyncio  # Add asyncio for lock handling
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
import services
import uvicorn
import handler

# Configure module logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Logging level priority (low → high)
# NOTSET   = 0   → disables filtering
# DEBUG    = 10  → detailed debug info
# INFO     = 20  → general runtime events
# WARNING  = 30  → unexpected but non-fatal issues
# ERROR    = 40  → serious problems in execution
# CRITICAL = 50  → severe errors; program may fail

app = FastAPI()
call_rooms: dict[str, set[WebSocket]] = {}
call_users: dict[str, set[str]] = {}

services.reset_variables()

# Add a lock for managing concurrent connection attempts
connection_locks: dict[str, asyncio.Lock] = {}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # --- AUTH HANDSHAKE ---
    try:
        init_payload = await ws.receive_json()
        username = await services.authenticate(ws, init_payload)
        if not username:
            return
    except Exception as e:
        logger.error("Authentication failed", exc_info=e)
        if ws.application_state != WebSocketState.DISCONNECTED:
            await ws.close(code=1008)
        return

    # --- ONE-USER-AT-A-TIME LOCK ---
    lock = connection_locks.setdefault(username, asyncio.Lock())
    async with lock:
        old_ws = services.active_connections.get(username)

        if old_ws and old_ws is not ws and old_ws.application_state == WebSocketState.CONNECTED:
            try:
                await old_ws.close(code=1000)
            except Exception:
                pass

        services.active_connections[username] = ws

    # --- SEND INITIAL STATE ---
    try:
        await services.notify_status(username, True)
        online_users = await services.get_online_users_for_user(username)
        await ws.send_json({"type": "auth_ack", "status": "ok"})
        await ws.send_json({"type": "online_users", "users": online_users})
    except Exception as e:
        logger.error("Error sending initial state to %s", username, exc_info=e)

    ####################
    # Main message loop#
    ####################

    try:
        while True:
            msg = await ws.receive_json()
            await handler.handle_message(ws, msg)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for user: %s", username)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", username, e, exc_info=e)
    finally:
        await services.cleanup_connection(username, ws)


from fastapi.middleware.cors import CORSMiddleware
connections = {}  # username -> WebSocket
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/call/{call_id}")
async def call_ws(ws: WebSocket, call_id: str):
    await ws.accept()

    # --- AUTH HANDSHAKE ---
    try:
        init_payload = await ws.receive_json()
        username = await services.authenticate(ws, init_payload)
        if not username:
            return
    except Exception as e:
        logger.error("Authentication failed", exc_info=e)
        if ws.application_state != WebSocketState.DISCONNECTED:
            await ws.close(code=1008)
        return

    # --- ONE-USER-AT-A-TIME LOCK ---
    lock = connection_locks.setdefault(username, asyncio.Lock())
    async with lock:
        old_ws = services.active_call_connections.get(username)

        if old_ws and old_ws is not ws and old_ws.application_state == WebSocketState.CONNECTED:
            try:
                await old_ws.close(code=1000)
            except Exception:
                pass

        services.active_call_connections[username] = ws

    sess = services.call_sessions.get(call_id)
    if not sess:
        try:
            await ws.send_json({
                "type": "call_ws_error",
                "call_id": call_id,
                "code": "CALL_NOT_FOUND",
            })
        except Exception:
            pass
        try:
            if ws.application_state != WebSocketState.DISCONNECTED:
                await ws.close(code=1008)
        except RuntimeError:
            logger.warning("Attempted to close an already closed WebSocket for call_id: %s", call_id)
        return

    state = sess.get("state")
    if state not in ("ringing", "active"):
        try:
            await ws.send_json({
                "type": "call_ws_error",
                "call_id": call_id,
                "code": "CALL_NOT_ACTIVE",
                "state": state,
            })
        except Exception:
            pass
        try:
            if ws.application_state != WebSocketState.DISCONNECTED:
                await ws.close(code=1008)
        except RuntimeError:
            logger.warning("Attempted to close an already closed WebSocket for call_id: %s", call_id)
        return

    call_rooms.setdefault(call_id, set()).add(ws)

    try:
        while True:
            data = await ws.receive_json()
            # fan out signaling payload to other participant(s) in this call
            for peer in list(call_rooms.get(call_id, set())):
                if peer is not ws:
                    try:
                        await peer.send_json(data)
                    except Exception:
                        pass
    except WebSocketDisconnect:
        pass
    finally:
        try:
            for peer in list(call_rooms.get(call_id, set())):
                if peer is not ws:
                    try:
                        await peer.send_json({"type": "leave"})
                    except Exception:
                        pass
        except Exception:
            pass

        room = call_rooms.get(call_id, set())
        room.discard(ws)
        if not room:
            call_rooms.pop(call_id, None)
            call_users.pop(call_id, None)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info", use_colors=False)
const HOST_BACKEND = 'chat.puam.be';
const HOST_WEBSOCKET = 'ws.chat.puam.be';
const HOST_LIVEKIT = '127.0.0.1';

const PORT_API     = 5123;
const PORT_WS      = 8765;
const PORT_LIVEKIT = 7880;

module.exports = {
  BASE_URL: `http://${HOST_BACKEND}:${PORT_API}`,
  WS_URL:   `ws://${HOST_WEBSOCKET}:${PORT_WS}/ws`,
  CALL_URL: `ws://${HOST_LIVEKIT}:${PORT_LIVEKIT}`,
  LIVEKIT_IP_URL: `http://${HOST_LIVEKIT}:${PORT_LIVEKIT}`
};
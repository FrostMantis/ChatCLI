const HOST_BACKEND = '172.27.27.29';
const HOST_WEBSOCKET = '172.27.27.29';
const HOST_LIVEKIT = '172.27.27.16';

const PORT_API     = 5123;
const PORT_WS      = 8765;
const PORT_LIVEKIT = 7880;

module.exports = {
  BASE_URL: `http://${HOST_BACKEND}:${PORT_API}`,
  WS_URL:   `ws://${HOST_WEBSOCKET}:${PORT_WS}/ws`,
  CALL_URL: `ws://${HOST_LIVEKIT}:${PORT_LIVEKIT}`,
  LIVEKIT_IP_URL: `http://${HOST_LIVEKIT}:${PORT_LIVEKIT}`
};
import { store } from '../core/store.js';
import { WSSend } from '../sockets/websocket_services.js';

/**
 * Thin wrapper over the global chat WS for call control messages.
 * All messages go to the same WS as chat:
 *   - call_invite
 *   - call_accept
 *   - call_decline
 *   - call_end
 */

export function sendCallInviteViaGlobal(chatID) {
  if (!chatID) return;
  WSSend({
    type: 'call_invite',
    chatID
  });
}

export function sendCallAcceptViaGlobal(chatID) {
  if (!chatID) return;
  const callId = store.call.incomingCallId || store.call.currentCallId;
  if (!callId) {
    console.warn('sendCallAcceptViaGlobal: no call_id available');
    return;
  }
  WSSend({
    type: 'call_accept',
    chatID,
    call_id: callId
  });
}

export function sendCallDeclineViaGlobal(chatID) {
  if (!chatID) return;
  WSSend({
    type: 'call_decline',
    chatID
  });
}

export function sendCallEndViaGlobal(chatID) {
  if (!chatID) return;
  WSSend({
    type: 'call_end',
    chatID
  });
}
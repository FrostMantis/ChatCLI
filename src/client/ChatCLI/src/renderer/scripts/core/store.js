export const store = {
  WS_URL: (window.api && window.api.WS_URL) || '',
  CALL_URL: (window.api && window.api.CALL_URL) || '',

  token: null,
  username: null,

  preventReconnect: false,

  // chat
  currentChatID: null,
  currentChat: null,
  currentChatIsPrivate: false,
  archivedVisible: false,
  archivedChatsData: [],
  currentMembers: [],
  peerUsername: null,
  editingMessageID: null,

  typingUsers: new Set(),
  typingTimeouts: new Map(),
  seenMessageIDs: new Set(),

  // call
  call: {
    callWS: null,
    currentCallId: null,
    pc: null,
    localStream: null,
    remoteStream: null,
    inCall: false,
    joiningArmed: false,
    pendingOffer: null,
    isMuted: false,
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    iceCandidateBuffer: []
  },

  // call UI state machine
  // 'idle' | 'incoming' | 'outgoing' | 'in-call'
  callState: 'idle',
  callIncoming: null,       // { chatID, from, call_id }
  callActiveChatID: null,   // the chat hosting the active call

  // DOM refs (filled in at bootstrap)
  refs: {}
};

export const selfName = () => (store.username || '').toLowerCase();

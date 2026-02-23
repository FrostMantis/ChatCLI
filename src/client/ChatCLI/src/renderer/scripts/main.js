import { store } from './core/store.js';
import { connectWS, WSSend, initChatSocketAutoResume } from './sockets/websocket_services.js';
import { setupModalClosing, showModal, hideModal, showConfirmationModal } from './ui/modals.js';
import { initTypingIndicator } from './ui/typing.js';
import { autoLoginOrRedirect, wireProfileAndAccount, putUsernameInUI } from './auth/session.js';
import { initChatSearch, reapplyChatSearch } from './chats/search.js';
import { apiRequest } from './core/api.js';
import { loadChats, onWSChatCreated } from './chats/chatList.js';
import { handleArchiveChat, archiveChat } from './chats/archive.js';
import { selectChat, sendMessage, updateSendButtonState, onWSNewMessage, onWSTyping, onWSUserStatus, onWSOnlineUsers, onWSEditedMessage, onWSDeletedMessage } from './chats/chatSession.js';
import { openGroupEditor, initGroupEditor } from './chats/groupEditor.js';
import { showToast } from './ui/toasts.js';
import { sendCallInviteViaGlobal, sendCallAcceptViaGlobal, sendCallDeclineViaGlobal, sendCallEndViaGlobal } from './calls/callSockets.js';
import { toggleMute, endCall, joinCall } from './calls/rtc.js';
import { playRingback, stopRingback, playRingtone, stopRingtone, initMedia } from './calls/media.js';



// --- events from ws
window.addEventListener('chat:new-message', onWSNewMessage);
window.addEventListener('chat:edited-message', onWSEditedMessage);
window.addEventListener('chat:deleted-message', onWSDeletedMessage);
window.addEventListener('chat:user-typing', onWSTyping);
window.addEventListener('chat:user-status', onWSUserStatus);
window.addEventListener('chat:chat_created', onWSChatCreated);
window.addEventListener('chat:online-users', onWSOnlineUsers);

// archive UX events
window.addEventListener('chat:archive', (ev) => handleArchiveChat(ev.detail.chatID));
window.addEventListener('chat:reload', async () => { await loadChats(); });

// DOM ready
document.addEventListener('DOMContentLoaded', async () => {
  // Cache DOM refs
  store.refs = {
    chatSearchInput: document.getElementById('chatSearchInput'),
    chatListEl: document.querySelector('.chat-list'),
    messagesEl: document.querySelector('.chat-messages'),
    messageInput: document.querySelector('.message-input'),
    charCounter: document.getElementById('charCounter'),
    sendBtn: document.querySelector('.send-button'),
    logoutBtn: document.querySelector('.logout-button'),
    chatTitle: document.querySelector('.chat-title'),
    editMembersBtn: document.getElementById('manageUsersBtn'),

    placeholder: null,

    // modals
    profileModal: document.getElementById('profileModal'),
    profileForm: document.getElementById('profileForm'),
    closeProfileBtn: document.getElementById('closeProfileModal'),
    cancelProfileBtn: document.getElementById('cancelProfile'),
    disableAccountBtn: document.querySelector('#profileModal button[name="disable"]'),
    deleteAccountBtn: document.querySelector('#profileModal button[name="delete"]'),

    createChatModal: document.getElementById('createChatModal'),
    privateChatSection: document.getElementById('privateChatSection'),
    groupChatSection: document.getElementById('groupChatSection'),
    newChatInput: document.querySelector('#privateChatSection input[name="receiver"]'),
    newGroupNameInput: document.querySelector('#groupChatSection input[name="groupName"]'),
    groupMemberInput: document.querySelector('#groupChatSection input[name="members"]'),
    createChatSubmitBtn: document.getElementById('createChatSubmitBtn'),
    closeCreateChatBtn: document.getElementById('closeCreateChat'),
    cancelCreateChatBtn: document.getElementById('cancelCreateChat'),

    groupEditorModal: document.getElementById('groupEditorModal'),
    groupMemberList: document.querySelector('#groupEditorModal .user-list'),
    editMemberInput: document.querySelector('#groupEditorModal .user-add-input'),
    editMemberAddBtn: document.querySelector('#groupEditorModal .user-add-button'),
    closeGroupEditorBtn: document.getElementById('closeGroupEditor'),
    cancelGroupEditBtn: document.getElementById('cancelGroupEdit'),
    saveGroupChangesBtn: document.getElementById('saveGroupChanges'),

    confirmationModal: document.getElementById('confirmationModal'),
    confirmationTitle: document.getElementById('confirmationTitle'),
    confirmationMessage: document.getElementById('confirmationMessage'),
    closeConfirmationModalBtn: document.getElementById('closeConfirmationModal'),
    cancelConfirmBtn: document.getElementById('cancelConfirmBtn'),
    confirmActionBtn: document.getElementById('confirmActionBtn'),

    resetPasswordModal: document.getElementById('resetPasswordModal'),
    closeResetPasswordModalBtn: document.getElementById('closeResetPasswordModal'),
    cancelResetPasswordBtn: document.getElementById('cancelResetPassword'),
    submitResetPasswordBtn: document.getElementById('submitResetPassword'),

    // calls UI
    statusEl: document.getElementById('status'),
    btnCallPrimary: document.getElementById('btnCallPrimary'),
    remoteAudio: document.getElementById('remoteAudio'),
    btnMute: document.getElementById('btnMute'),
    muteIconUse: document.getElementById('muteIconUse'),
    incomingCallModal: document.getElementById('incomingCallModal'),
    incomingCallClose: document.getElementById('incomingCallClose'),
    incomingCallFromEl: document.getElementById('incomingCallFrom'),
    incomingCallMetaEl: document.getElementById('incomingCallMeta'),
    incomingCallAvatarEl: document.getElementById('incomingCallAvatar'),
    acceptCallBtn: document.getElementById('acceptCallBtn'),
    declineCallBtn: document.getElementById('declineCallBtn'),
  };

  window.addEventListener('media:mic-status', (ev) => {
    const hasMic = !!ev.detail?.hasMic;
    const muteBtn = store.refs.btnMute;
    const muteIconUse = store.refs.muteIconUse;
    if (!muteBtn || !muteIconUse) return;

    if (!hasMic) {
      muteIconUse.setAttribute('href', '#icon-mic-off');
      muteBtn.disabled = true;
      muteBtn.classList.add('no-mic');
      muteBtn.title = 'No microphone detected';
      showToast(
        'This device has no microphone. You can join calls, but others won’t hear you.',
        'error'
      );
    } else {
      muteBtn.disabled = false;
      muteBtn.classList.remove('no-mic');
      muteBtn.title = '';
      muteIconUse.setAttribute('href', '#icon-mic');
    }
  });

  try { endCall('App reloaded'); } catch {}
  store.callState = 'idle';
  store.callActiveChatID = null;
  if (store.call) { store.call.currentCallId = null; }

  window.addEventListener('beforeunload', () => {
    try { endCall('Unload'); } catch {}
    try { store.call?.callWS?.close(); } catch {}
  });

  store.callIncoming = store.callIncoming || null;

  store.refs.incomingCallClose?.addEventListener('click', hideIncomingCallModal);
  store.refs.declineCallBtn?.addEventListener('click', async () => {
    try {
      if (store.callIncoming?.chatID) {
        sendCallDeclineViaGlobal(store.callIncoming.chatID);
      }
    } catch {}
    hideIncomingCallModal();
    stopRingtone();
    store.callIncoming = null;
    store.callState = 'idle';
    window.dispatchEvent(new Event('call:ended'));
  });
  
  const btn = store.refs.acceptCallBtn;
  btn?.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const ringingChat = store.callIncoming?.chatID;
      if (ringingChat && store.currentChatID !== ringingChat) {
        await selectChat(ringingChat);
      }
      if (store.callIncoming?.call_id) store.call.currentCallId = store.callIncoming.call_id;
      sendCallAcceptViaGlobal(ringingChat);
      store.callState = 'in-call';
      store.callActiveChatID = ringingChat ?? store.currentChatID;
    } finally {
      hideIncomingCallModal();
      stopRingtone();
      setTimeout(() => { if (btn.isConnected) btn.disabled = false; }, 1500);
    }
  });
  


  function showIncomingCallModal(from, meta = '') {
    const { incomingCallModal, incomingCallFromEl, incomingCallMetaEl, incomingCallAvatarEl } = store.refs;
    if (!incomingCallModal) return;
    incomingCallFromEl.textContent = from || 'Unknown';
    incomingCallMetaEl.textContent = meta || 'is calling you…';
    if (incomingCallAvatarEl) incomingCallAvatarEl.textContent = (from || '?').slice(0,1).toUpperCase();
  
    incomingCallModal.classList.add('active');
    incomingCallModal.setAttribute('aria-hidden', 'false');
    incomingCallModal.inert = false;
    incomingCallModal.querySelector('#acceptCallBtn')?.focus();
  }
  function hideIncomingCallModal() {
    const m = store.refs.incomingCallModal;
    if (!m) return;
    m.classList.remove('active');
    m.setAttribute('aria-hidden', 'true');
    m.inert = true;
    if (document.activeElement && m.contains(document.activeElement)) {
      document.activeElement.blur();
    }
  }  

  store.refs.btnMute?.addEventListener('click', async () => {
    toggleMute();
  });

  function updateMuteButton() {
    const muteBtn = store.refs.btnMute;
    if (!muteBtn) return;
    const inSameChatAsCall = store.callActiveChatID && store.currentChatID === store.callActiveChatID;
    const shouldShow = store.callState === 'in-call' && inSameChatAsCall;
    muteBtn.style.display = shouldShow ? 'inline-flex' : 'none';
  }

  function updateCallButton() {
    const btn = store.refs.btnCallPrimary;
    if (!btn) return;
    const iconUse = btn.querySelector('use');
    btn.dataset.state = store.callState;

    const isPrivate = store.currentChat?.type === 'private' || store.currentChatIsPrivate === true;
    setCallButtonVisible(!!store.currentChatID && isPrivate); 

    if (store.callState === 'idle') {
      iconUse.setAttribute('href', '#icon-phone');
      btn.setAttribute('aria-label', 'Start call');
    } else if (store.callState === 'incoming') {
      if (store.callIncoming?.chatID === store.currentChatID) {
        btn.setAttribute('aria-label', 'Join call');
      } else {
        btn.setAttribute('aria-label', 'Start call');
      }
    } else if (store.callState === 'outgoing') {
      iconUse.setAttribute('href', '#icon-phone-off');
      btn.setAttribute('aria-label', 'Cancel call');
    } else {
      iconUse.setAttribute('href', '#icon-phone-off');
      btn.setAttribute('aria-label', 'Leave call');
    }

    btn.classList.toggle('incoming', store.callState === 'incoming');
    btn.classList.toggle('in-call',  store.callState === 'in-call');

    updateMuteButton();
  }


  // === Call UI state & helpers ===
  function setCallButtonVisible(visible) {
    const btn = store.refs.btnCallPrimary;
    if (!btn) return;
    btn.style.display = visible ? 'inline-flex' : 'none';
  }
  
  // Call primary button click
  store.refs.btnCallPrimary?.addEventListener('click', async () => {
    try {
      if (!store.currentChatID) {
        showToast('Select a chat first', 'error');
        return;
      }
  
    if (store.callState === 'idle') {
      await initMedia();

      const hasMic =
        store.call.localStream &&
        store.call.localStream.getAudioTracks().length > 0;

      if (!hasMic) { return; }

      sendCallInviteViaGlobal(store.currentChatID);
      store.callState = 'outgoing';
      store.callActiveChatID = store.currentChatID;
      playRingback();
      return;
    }
  
      if (store.callState === 'incoming') {
        const ringingChat = store.callIncoming?.chatID ?? store.currentChatID;
        if (ringingChat && store.currentChatID !== ringingChat) {
          await selectChat(ringingChat);
        }
        if (store.callIncoming?.call_id) {
          store.call.currentCallId = store.callIncoming.call_id;
        }
        sendCallAcceptViaGlobal(ringingChat);
        store.callState = 'in-call';
        store.callActiveChatID = ringingChat;
        return;
      }
  
      if (store.callState === 'outgoing') {
        sendCallEndViaGlobal(store.callActiveChatID);
        endCall('You left');
        store.callState = 'idle';
        store.callActiveChatID = null;
        stopRingback();
        stopRingtone();
        updateCallButton();
        return;
      }

      // else: in-call → leave
      sendCallEndViaGlobal(store.callActiveChatID);
      store.callState = 'idle';
      store.callActiveChatID = null;
      stopRingback();
      stopRingtone();
      endCall('You left');
    } catch (e) {
      console.error(e);
    } finally {
      updateCallButton();
    }
  });

  // React to signaling events from callSockets/rtc
  window.addEventListener('call:incoming', (ev) => {
    const chatID = ev?.detail?.chatID ?? store.currentChatID;
    const from   = ev?.detail?.from ?? ev?.detail?.fromUsername ?? 'Unknown';
    const call_id = ev?.detail?.call_id;
    store.callState = 'incoming';
    store.callIncoming = { chatID, from, call_id };
  
    playRingtone();
    showIncomingCallModal(from, 'is calling you…');
    updateCallButton();
  });
  
  window.addEventListener('call:connected', () => {
    hideIncomingCallModal();
    stopRingback();
    stopRingtone();
    store.callIncoming = null;
    updateCallButton();
  });
  
  window.addEventListener('call:ended', () => {
    hideIncomingCallModal();
    store.callState = 'idle';
    store.callActiveChatID = null;
    store.callIncoming = null;
    stopRingback();
    stopRingtone();
    updateCallButton();
  });  
  window.addEventListener('call:started',  () => {
    store.callState = 'in-call';
    store.callActiveChatID = store.currentChatID;
    updateCallButton();
  });

  window.addEventListener('call:muted', (ev) => {
    const muted = !!ev.detail?.muted;
    store.refs.muteIconUse?.setAttribute('href', muted ? '#icon-mic-off' : '#icon-mic');
  });

  // Initial call button state
  setCallButtonVisible(false);

  window.addEventListener('chat:selected', async (ev) => {
    const { chatID, type } = ev.detail || {};
    store.currentChatID = chatID || null;
    store.currentChat   = chatID ? { id: chatID, type } : null;
    store.currentChatIsPrivate = type === 'private';
  
    if (store.callState !== 'in-call') {
      const isRingingHere =
        store.callState === 'incoming' &&
        store.callIncoming?.chatID === chatID;
      if (!isRingingHere) {
        store.callState = 'idle';
        store.callIncoming = null;
        stopRingback();
        stopRingtone();
      }
    }
  
    updateCallButton();
  });

  // Global WS → call lifecycle bridge
  window.addEventListener('global:msg', async (ev) => {
      const msg = ev.detail || {};
      const self = (store.username || '').toLowerCase();

      switch (msg.type) {

          case 'call_state': {
              const { chatID, call_id, initiator, state } = msg;
              const initName = (initiator || '').toLowerCase();

              if (state === 'ringing') {
                  if (self === initName) {
                      store.call.currentCallId = call_id;
                      store.callState = 'outgoing';
                      store.callActiveChatID = chatID;
                  } else {
                      store.callIncoming = { chatID, from: initiator, call_id };
                      store.callState = 'incoming';
                      window.dispatchEvent(new CustomEvent('call:incoming', {
                        detail: { chatID, from: initiator, call_id }
                      }));
                  }
                  updateCallButton();
                  break;
              }

              if (state === 'active') {

                  store.call.currentCallId = call_id;
                  store.callState = 'in-call';
                  store.callActiveChatID = chatID;

                  const isInitiator = self === initName;
                  if (isInitiator) {
                    stopRingback();
                  }

                  await joinCall({ callId: call_id, isInitiator });
                  updateCallButton();
                  break;
              }

              if (state === 'ended') {
                  endCall('signaling_ended');
                  window.dispatchEvent(new Event('call:ended'));
                  break;
              }

              break;
          }

          case 'call_ended':
              window.dispatchEvent(new Event('call:ended'));
              break;

          case 'call_declined':
              endCall('remote_hangup');
              window.dispatchEvent(new Event('call:ended'));
              break;

          case 'call_error':
              console.error("[CALL_ERROR]", msg);
              if (msg.message) {
                  showToast(msg.message, 'error');
              }
              break;
      }
  });


  // Placeholder
  const placeholder = document.createElement('div');
  placeholder.id = 'no-chat-selected';
  placeholder.textContent = 'Select a chat to start messaging';
  Object.assign(placeholder.style, {
    display: 'flex', justifyContent: 'center', alignItems: 'center',
    height: '100%', color: 'var(--text-secondary)'
  });
  store.refs.messagesEl.appendChild(placeholder);
  store.refs.placeholder = placeholder;

  setupModalClosing();
  initTypingIndicator();
  initGroupEditor();

  window.addEventListener('auth:username-updated', async (ev) => {
    const next = ev.detail?.username;
    if (!next) return;
    putUsernameInUI();
  });

  // auto-login
  const ok = await autoLoginOrRedirect();
  if (!ok) return;

  if (!store.username) {
    try {
      const persisted =
        (await window.secureStore?.get?.('username')) ||
        localStorage.getItem('username');
      if (persisted) store.username = persisted;
    } catch (_) { /* ignore */ }
  }  

  putUsernameInUI();

  // Create chat modal radio switching
  document.querySelectorAll('input[name="chatType"]').forEach(radio => {
    radio.addEventListener('change', function() {
      const { privateChatSection, groupChatSection, newChatInput, newGroupNameInput, groupMemberInput } = store.refs;
      if (this.value === 'private') {
        privateChatSection.classList.remove('hidden');
        groupChatSection.classList.add('hidden');
        if (newGroupNameInput) newGroupNameInput.value = '';
        if (groupMemberInput) groupMemberInput.value = '';
      } else {
        privateChatSection.classList.add('hidden');
        groupChatSection.classList.remove('hidden');
        if (newChatInput) newChatInput.value = '';
      }
    });
  });

  // open create chat modal
  document.getElementById('openCreateChat')?.addEventListener('click', () => {
    const { privateChatSection, groupChatSection, newChatInput, newGroupNameInput, groupMemberInput, createChatModal } = store.refs;
    const selectedType = document.querySelector('input[name="chatType"]:checked')?.value;
    if (selectedType === 'group') {
      privateChatSection.classList.add('hidden');
      groupChatSection.classList.remove('hidden');
    } else {
      privateChatSection.classList.remove('hidden');
      groupChatSection.classList.add('hidden');
    }
    newChatInput.value = '';
    newGroupNameInput.value = '';
    groupMemberInput.value = '';
    showModal(createChatModal);
  });

  // Create chat modal close/cancel
  if (store.refs.closeCreateChatBtn) store.refs.closeCreateChatBtn.addEventListener('click', async () => {
    hideModal(store.refs.createChatModal);
  });
  if (store.refs.cancelCreateChatBtn) store.refs.cancelCreateChatBtn.addEventListener('click', async () => {
    hideModal(store.refs.createChatModal);
  });

  // Create chat submit
  if (store.refs.createChatSubmitBtn) {
    store.refs.createChatSubmitBtn.addEventListener('click', async () => {
      const { newChatInput, newGroupNameInput, groupMemberInput, createChatModal } = store.refs;


      const chatType = document.querySelector('input[name="chatType"]:checked')?.value;
      if (!chatType) return showToast('Please select a chat type', 'error');

      if (chatType === 'private') {
        const receiver = newChatInput.value.trim();
        if (!receiver) return showToast('Please enter a username', 'error');

        try {
          const result = await apiRequest('/chat/create-chat', {
            body: JSON.stringify({ receiver, session_token: store.token })
          });
          const chatID = result.chatID;
          showToast('Private chat created!', 'info');
          try {
            WSSend({ type : 'chat_created', chatID : chatID });
          } catch (err) {showToast(err.message, 'error')}
          hideModal(createChatModal);
          newChatInput.value = '';
          await loadChats();
          selectChat(chatID);
        } catch (err) {
          showToast(err.message || 'Could not create private chat', 'error');
        }
      } else {
        const groupName = newGroupNameInput.value.trim();
        const membersInput = groupMemberInput.value.trim();
        if (!groupName)      return showToast('Please enter a group name', 'error');
        if (!membersInput)   return showToast('Please add at least one member', 'error');

        const members = membersInput.split(',').map(m => m.trim()).filter(Boolean);
        try {
          const result = await apiRequest('/chat/create-group', {
            body: JSON.stringify({ session_token: store.token, name: groupName, members })
          });
          if (!result.chatID) throw new Error('Failed to create group');
          const chatID = result.chatID;
          showToast('Group created!', 'info');
          try {
            WSSend({ type: 'chat_created', chatID : chatID });
          } catch (err) {showToast(err.message + "send chat_created", 'error')}
          hideModal(createChatModal);
          newGroupNameInput.value = '';
          groupMemberInput.value = '';
          await loadChats();
          selectChat(chatID);
        } catch (err) {
          showToast(err.message || 'Could not create group', 'error');
        }
      }
    });
  }

  // Manage group members button
  if (store.refs.editMembersBtn) {
    store.refs.editMembersBtn.addEventListener('click', openGroupEditor);
  }
  store.refs.editMembersBtn.style.display = 'none';

  // Connect chat WS + initial chats (wait for auth token)
  await autoLoginOrRedirect();
  initChatSocketAutoResume();
  connectWS();
  await loadChats();
  reapplyChatSearch();
  updateSendButtonState();
  initChatSearch();

  // Message input events
  if (store.refs.sendBtn) store.refs.sendBtn.addEventListener('click', sendMessage);

  if (store.refs.messageInput) {
    store.refs.messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();

        const input = store.refs.messageInput;
        if (!input) return;

        const text = input.value.trim();
        if (!text) return;

        const len = text.length;

        // If a confirmation modal is already open, don't trigger another send
        const cm = store.refs.confirmationModal;
        const modalOpen = cm && cm.classList.contains('active');
        if (modalOpen) return;

        // For "normal" messages (<= 2048 chars), Enter sends immediately
        if (len <= 2048) {
          sendMessage();
          return;
        }

        // For long messages that require the split/trim confirmation,
        // force the user to click the send button so the modal can't
        // be auto-accepted by the same Enter keypress.
        showToast(
          'Message is too long to send with Enter. Click the send icon to confirm splitting.',
          'info'
        );
      }
  });
    store.refs.messageInput.addEventListener('input', () => {
      const el = store.refs.messageInput;
      el.style.height = 'auto';
      const maxH = 200;
      const needed = el.scrollHeight;
      if (needed <= maxH) { el.style.height = `${needed}px`; el.style.overflowY = 'hidden'; }
      else                { el.style.height = `${maxH}px`;   el.style.overflowY = 'auto'; }
      updateSendButtonState();

      const len = el.value.length;
      const cc = store.refs.charCounter;
      if (len >= 1950) {
        cc.style.display = 'block';
        cc.textContent = len <= 2100 ? `${len}/2048` : 'Message too long';
      } else {
        cc.style.display = 'none';
      }
      el.classList.toggle('error', len > 2048);
      cc.classList.toggle('error', len > 2048);

      if (!store.currentChatID) return;
      WSSend({ type: 'typing', chatID: store.currentChatID });
    });
  }

  // Profile + account wiring
  wireProfileAndAccount();

  // Sidebar archive confirm
  window.addEventListener('chat:confirm-archive', async (ev) => {
    showConfirmationModal(
      'Are you sure you want to archive this chat? You can still rejoin it later.',
      'Archive Chat',
      async () => { 
        await archiveChat(ev.detail.chatID);
      }
    );
  });
});

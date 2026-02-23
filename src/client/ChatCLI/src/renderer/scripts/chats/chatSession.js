import { store } from '../core/store.js';
import { apiRequest } from '../core/api.js';
import { showToast } from '../ui/toasts.js';
import { showConfirmationModal } from '../ui/modals.js';
import { WSSend } from '../sockets/websocket_services.js';
import { updateTypingIndicator } from '../ui/typing.js';
import { loadGroupMembers } from './groupService.js';

const MAX_MESSAGE_LEN = 2048;
const MAX_SPLIT_PARTS = 5;
const HARD_MAX = MAX_MESSAGE_LEN * MAX_SPLIT_PARTS;
const CLUSTER_WINDOW_MS = 5 * 60 * 1000;

// Cluster detection: new cluster if different user or time gap exceeded
function isNewCluster(prevMsgEl, user, tsMs) {
  if (!prevMsgEl) return true;
  const prevUser = prevMsgEl.dataset.username || '';
  const prevTs = Number(prevMsgEl.dataset.ts || 0);
  const sameUser = prevUser.toLowerCase() === (user || '').toLowerCase();
  const closeInTime = Math.abs(tsMs - prevTs) < CLUSTER_WINDOW_MS;
  return !(sameUser && closeInTime);
}

function getAvatarFor(username) {
  return null;
}

function makeInitials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join('') || '?';
}

// Splits a long text into chunks of given size, trying to split on soft breaks
function splitIntoChunks(text, size = MAX_MESSAGE_LEN, maxParts = MAX_SPLIT_PARTS) {
  const chunks = [];
  let i = 0;

  while (i < text.length) {
    const remaining = text.length - i;
    const partsLeft = maxParts - chunks.length;

    if (partsLeft === 1) {
      chunks.push(text.slice(i));
      break;
    }

    const maxEnd = i + Math.min(size, remaining);
    const minEnd = Math.max(i + 1, text.length - (partsLeft - 1) * size);

    let end = maxEnd;

    // soft break if it still leaves room for remaining parts
    if (end < text.length) {
      const soft = Math.max(text.lastIndexOf('\n', end), text.lastIndexOf(' ', end));
      if (soft >= minEnd) end = soft;
    }

    if (end < minEnd) end = minEnd;      // ensure last parts won't overflow
    chunks.push(text.slice(i, end));
    i = end;
  }

  return chunks;
}

export function updateSendButtonState() {
  const { messageInput, sendBtn } = store.refs;
  const hasContent = messageInput.value.trim().length > 0;
  sendBtn.classList.toggle('disabled', !hasContent);
  sendBtn.disabled = !hasContent;
}

// Selects a chat by ID, or clears selection if null/undefined
export async function selectChat(chatID) {
  const { messagesEl, chatTitle, editMembersBtn } = store.refs;

  // Normalize once
  const targetId = chatID == null ? null : parseInt(chatID, 10);

  // No chat selected → show welcome / hide composer/header and notify listeners
  if (!targetId) {
    store.currentChatID = null;
    store.currentChat = null;
    store.currentChatIsPrivate = false;
    store.peerUsername = null;

    messagesEl.innerHTML = '';
    const welcomeMessage = document.createElement('div');
    welcomeMessage.id = 'no-chat-selected';
    welcomeMessage.innerHTML = `
      <div style="text-align: center; padding: 20px;">
        <h2 style="margin-bottom: 10px;">Welcome to ChatCLI</h2>
        <p style="color: var(--text-secondary)">Select a chat to start messaging</p>
      </div>
    `;
    messagesEl.appendChild(welcomeMessage);

    document.querySelector('.chat-input').classList.add('hidden');
    document.querySelector('.chat-header').style.display = 'none';
    if (editMembersBtn) editMembersBtn.style.display = 'none';

    // let the rest of the app know that no chat is selected
    window.dispatchEvent(new CustomEvent('chat:selected', {
      detail: { chatID: null, type: null }
    }));
    return;
  }

  // Already on this chat? keep UX snappy and bail
  if (store.currentChatID === targetId) {
    store.refs.messageInput?.focus();
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return;
  }

  // Find the clicked chat item
  const chatItem = store.refs.chatListEl.querySelector(`[data-chat-id="${targetId}"]`);
  if (!chatItem) {
    console.error('Chat item not found');
    return;
  }

  // Derive name & type from the list item
  const name = chatItem.dataset.username || 'Unknown Chat';
  const type = chatItem.dataset.type || 'private'; // 'private' | 'group'
  const isGroup = type === 'group';

  // Show header + composer
  document.querySelector('.chat-header').style.display = 'flex';
  chatTitle.textContent = name;
  if (editMembersBtn) editMembersBtn.style.display = isGroup ? 'block' : 'none';
  document.querySelector('.chat-input').classList.remove('hidden');
  store.refs.typingIndicator.style.display = 'none';

  // Clear typing state
  store.typingUsers.clear();
  store.typingTimeouts.forEach(timeout => clearTimeout(timeout));
  store.typingTimeouts.clear();

  // Leave previous chat (only when switching)
  if (store.currentChatID != null) {
    WSSend({ type: 'leave_chat', chatID: store.currentChatID });
  }

  // Join new chat
  store.currentChatID = targetId;
  store.currentChat   = { id: targetId, type };
  store.currentChatIsPrivate = !isGroup;
  store.peerUsername = isGroup ? null : name;

  messagesEl.innerHTML = '';
  WSSend({ type: 'join_chat', chatID: targetId });

  // Group extras
  if (isGroup) {
    loadGroupMembers(targetId);
    if (editMembersBtn) editMembersBtn.style.display = 'block';
  } else if (editMembersBtn) {
    editMembersBtn.style.display = 'none';
  }

  // Load history
  try {
    const history = await apiRequest('/chat/messages', {
      body: JSON.stringify({ session_token: store.token, chatID: targetId })
    });
    if (Array.isArray(history?.messages)) {
      history.messages.forEach(msg => appendMessage({
        username: msg.username,
        message: msg.message,
        timestamp: msg.timestamp,
        messageID: msg.messageID,
        edited_at: msg.edited_at,
        deleted_at: msg.deleted_at
      }));
    }
  } catch (err) {
    console.error('history fetch error:', err);
    showToast('Failed to load message history: ' + (err.message || 'Unknown error'), 'error');
  }

  // Cancel edit mode when switching chats
  if (store.editingMessageID) {
    cancelEditingMessage();
  }

  // Mark active in list
  document.querySelectorAll('.chat-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.chatId, 10) === targetId);
  });

  // Focus input
  window.dispatchEvent(new CustomEvent('chat:selected', {
    detail: { chatID: targetId, type }
  }));
}


export function appendMessage({ username: msgUser, message, timestamp, messageID, edited_at, deleted_at }) {
  const { messagesEl } = store.refs;

  const ts = new Date(timestamp);
  const tsMs = ts.getTime();
  const timeHHmm = ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const formatted = `${ts.toLocaleDateString()}, ${timeHHmm}`;

  const lastMsg = messagesEl.lastElementChild?.classList?.contains('message')
    ? messagesEl.lastElementChild
    : null;

  const startNewCluster = isNewCluster(lastMsg, msgUser, tsMs);

  const wrap = document.createElement('div');
  wrap.className = 'message ' + (startNewCluster ? 'message--cluster-start' : 'message--cluster-continue');
  wrap.dataset.username = msgUser;
  wrap.dataset.ts = String(tsMs);
  if (messageID) wrap.dataset.messageId = String(messageID);

  // Left rail: avatar for cluster start; for continuations add a hover-time
  const leftRail = document.createElement('div');
  leftRail.className = 'message-rail' + (startNewCluster ? '' : ' spacer');

  if (startNewCluster) {
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    const avatarUrl = getAvatarFor(msgUser);
    if (avatarUrl) {
      const img = document.createElement('img');
      img.src = avatarUrl;
      img.alt = `${msgUser} avatar`;
      avatar.appendChild(img);
    } else {
      const chip = document.createElement('span');
      chip.className = 'avatar-initials';
      chip.textContent = makeInitials(msgUser);
      avatar.appendChild(chip);
    }
    leftRail.appendChild(avatar);
  } else {
    // add hover time placeholder for continuations
    const hoverTime = document.createElement('span');
    hoverTime.className = 'hover-time';
    hoverTime.textContent = timeHHmm; // e.g. "14:07"
    leftRail.appendChild(hoverTime);
  }

  // Right column
  const right = document.createElement('div');
  right.className = 'message-body';

  if (startNewCluster) {
    const header = document.createElement('div');
    header.className = 'message-header';

    const userEl = document.createElement('span');
    userEl.className = 'message-sender';
    if (msgUser.toLowerCase() === (store.username || '').toLowerCase()) {
      userEl.classList.add('message-sender-self');
    }
    userEl.textContent = msgUser;

    const timeEl = document.createElement('span');
    timeEl.className = 'message-time';
    timeEl.textContent = formatted;

    header.append(userEl, timeEl);
    right.appendChild(header);
  }

  // Show "(deleted)" for deleted messages
  const isDeleted = deleted_at !== null && deleted_at !== undefined;
  
  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  if (isDeleted) {
    bubble.textContent = '(message deleted)';
    bubble.style.fontStyle = 'italic';
    bubble.style.opacity = '0.6';
  } else {
    bubble.textContent = message;
  }
  right.appendChild(bubble);

  // Show edit indicator
  if (edited_at !== null && edited_at !== undefined) {
    const editIndicator = document.createElement('span');
    editIndicator.className = 'edit-indicator';
    editIndicator.textContent = '(edited)';
    editIndicator.style.fontSize = '0.85em';
    editIndicator.style.opacity = '0.7';
    editIndicator.style.marginLeft = '0.5em';
    bubble.appendChild(editIndicator);
  }

  // Add edit/delete buttons for own messages (only if not deleted)
  if (!isDeleted && msgUser.toLowerCase() === (store.username || '').toLowerCase()) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    actions.style.display = 'flex';
    actions.style.gap = '8px';
    actions.style.marginTop = '4px';
    actions.style.fontSize = '0.85em';

    const editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.className = 'message-action-btn';
    editBtn.style.background = 'none';
    editBtn.style.border = 'none';
    editBtn.style.color = 'var(--text-link, #0066cc)';
    editBtn.style.cursor = 'pointer';
    editBtn.style.padding = '0';
    editBtn.onclick = () => startEditingMessage(messageID, message);

    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = 'Delete';
    deleteBtn.className = 'message-action-btn';
    deleteBtn.style.background = 'none';
    deleteBtn.style.border = 'none';
    deleteBtn.style.color = 'var(--text-danger, #d32f2f)';
    deleteBtn.style.cursor = 'pointer';
    deleteBtn.style.padding = '0';
    deleteBtn.onclick = () => confirmDeleteMessage(messageID);

    actions.append(editBtn, deleteBtn);
    right.appendChild(actions);
  }

  wrap.append(leftRail, right);
  messagesEl.appendChild(wrap);

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Edit/Delete message handlers
function startEditingMessage(messageID, currentText) {
  const { messageInput } = store.refs;
  store.editingMessageID = messageID;
  messageInput.value = currentText;
  messageInput.focus();
  messageInput.placeholder = 'Editing message... (press Escape to cancel)';
  messageInput.style.backgroundColor = 'var(--bg-edit-mode, #f5f5f5)';
  updateSendButtonState();
}

function cancelEditingMessage() {
  const { messageInput } = store.refs;
  store.editingMessageID = null;
  messageInput.value = '';
  messageInput.placeholder = 'Type a message...';
  messageInput.style.backgroundColor = '';
  updateSendButtonState();
}

function confirmDeleteMessage(messageID) {
  showConfirmationModal(
    'Are you sure you want to delete this message?',
    'Delete Message',
    () => deleteMessage(messageID)
  );
}

async function deleteMessage(messageID) {
  try {
    console.log('Sending delete_msg:', { type: 'delete_msg', chatID: store.currentChatID, messageID });
    WSSend({
      type: 'delete_msg',
      chatID: store.currentChatID,
      messageID
    });
  } catch (err) {
    console.error('Delete message error:', err);
    showToast('Failed to delete message', 'error');
  }
}

export async function sendMessage() {
  const { messageInput, charCounter } = store.refs;
  if (!store.currentChatID) return showToast('Select a chat first.', 'error');

  const raw = messageInput.value;
  const text = raw.trim();
  if (!text) return;

  const len = text.length;

  if (len <= MAX_MESSAGE_LEN) {
    if (store.editingMessageID) {
      console.log('Sending edit_msg:', { type: 'edit_msg', chatID: store.currentChatID, messageID: store.editingMessageID, text });
      WSSend({
        type: 'edit_msg',
        chatID: store.currentChatID,
        messageID: store.editingMessageID,
        text
      });
      cancelEditingMessage();
    } else {
      console.log('Sending post_msg:', { type: 'post_msg', chatID: store.currentChatID, text });
      WSSend({ type: 'post_msg', chatID: store.currentChatID, text });
    }
    messageInput.value = '';
    messageInput.style.height = 'auto';
    updateSendButtonState();
    if (charCounter) charCounter.style.display = 'none';
    return;
  }

  // Cancel edit if user tries to split a message into chunks
  if (store.editingMessageID) {
    showToast('Cannot split edited message into multiple parts', 'error');
    return;
  }

  if (len > HARD_MAX) {
    const over = len - HARD_MAX;

    const overflowRaw = text.slice(HARD_MAX).trimStart();
    let overflowSnippet = '';
    if (overflowRaw.length > 0) {
      const words = overflowRaw.split(/\s+/).slice(0, 8).join(' ');
      const hasMore = overflowRaw.length > words.length;
      overflowSnippet =
        `\n\nAnything after the limit will NOT be sent. ` +
        `The first part that will be dropped starts with:\n` +
        `"${words}${hasMore ? '…' : ''}"`;
    }

    showConfirmationModal(
      `Your message is ${len} characters, exceeding the limit of ${HARD_MAX} ` +
      `(${over} characters too long).\n\n` +
      `Send the first ${HARD_MAX} characters, split into 5 messages?` +
      overflowSnippet,
      'Message Too Long',
      async () => {
        const trimmed = text.slice(0, HARD_MAX);
        const chunks = splitIntoChunks(trimmed, MAX_MESSAGE_LEN, MAX_SPLIT_PARTS);
        for (const chunk of chunks) {
          WSSend({ type: 'post_msg', chatID: store.currentChatID, text: chunk });
        }
        messageInput.value = '';
        messageInput.style.height = 'auto';
        updateSendButtonState();
        if (charCounter) charCounter.style.display = 'none';
        showToast(`Sent in ${chunks.length} parts (trimmed to the limit).`, 'info');
      }
    );
    return;
  }

  const chunks = splitIntoChunks(text, MAX_MESSAGE_LEN, MAX_SPLIT_PARTS);
  showConfirmationModal(
    `Your message is ${len} characters and will be split into ${chunks.length} ` +
    `message${chunks.length > 1 ? 's' : ''}. Continue?`,
    'Split Message?',
    async () => {
      for (const chunk of chunks) {
        WSSend({ type: 'post_msg', chatID: store.currentChatID, text: chunk });
      }
      messageInput.value = '';
      messageInput.style.height = 'auto';
      updateSendButtonState();
      if (charCounter) charCounter.style.display = 'none';
      showToast(`Sent in ${chunks.length} parts.`, 'info');
    }
  );
}

// Handle Escape key to cancel edit mode
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && store.editingMessageID) {
    cancelEditingMessage();
  }
});

// WS event handlers (hooked by main.js)
export function onWSNewMessage({ detail: msg }) {
  if (msg.chatID === store.currentChatID) {
    appendMessage({
      username: msg.username,
      message: msg.message,
      timestamp: msg.timestamp,
      messageID: msg.messageID,
      edited_at: msg.edited_at,
      deleted_at: msg.deleted_at
    });
  } else {
    const preview = store.refs.chatListEl
      .querySelector(`.chat-item[data-chat-id="${msg.chatID}"] .chat-preview`);
    if (preview) preview.textContent = msg.message.slice(0, 50);
  }
}

export function onWSEditedMessage({ detail: msg }) {
  console.log('onWSEditedMessage received:', msg);
  // Find message element by messageID
  const msgEl = document.querySelector(`[data-message-id="${msg.messageID}"]`);
  console.log('Found message element:', msgEl);
  if (msgEl) {
    // Update the message text in the bubble
    const bubble = msgEl.querySelector('.message-bubble');
    if (bubble) {
      // Clear existing content
      bubble.textContent = msg.message;
      // Add edit indicator
      const editIndicator = document.createElement('span');
      editIndicator.className = 'edit-indicator';
      editIndicator.textContent = '(edited)';
      editIndicator.style.fontSize = '0.85em';
      editIndicator.style.opacity = '0.7';
      editIndicator.style.marginLeft = '0.5em';
      bubble.appendChild(editIndicator);
    }
  }
  if (msg.chatID === store.currentChatID) {
    showToast('Message updated', 'info');
  }
}

export function onWSDeletedMessage({ detail: msg }) {
  console.log('onWSDeletedMessage received:', msg);
  // Find message element by messageID
  const msgEl = document.querySelector(`[data-message-id="${msg.messageID}"]`);
  console.log('Found message element:', msgEl);
  if (msgEl) {
    // Update the message text and style to show deletion
    const bubble = msgEl.querySelector('.message-bubble');
    if (bubble) {
      bubble.textContent = '(message deleted)';
      bubble.style.fontStyle = 'italic';
      bubble.style.opacity = '0.6';
    }
    // Remove action buttons
    const actions = msgEl.querySelector('.message-actions');
    if (actions) actions.remove();
  }
  if (msg.chatID === store.currentChatID) {
    showToast('Message deleted', 'info');
  }
}

export function onWSTyping({ detail: username }) {
  if (username.toLowerCase() === (store.username || '').toLowerCase()) return;
  const user = username;
  store.typingUsers.add(user);
  clearTimeout(store.typingTimeouts.get(user));
  store.typingTimeouts.set(user, setTimeout(() => {
    store.typingUsers.delete(user);
    updateTypingIndicator();
  }, 3000));
  updateTypingIndicator();
}

export function onWSUserStatus({ detail: msg }) {
  const chatItems = document.querySelectorAll(`.chat-item[data-username="${msg.username}"]`);
  chatItems.forEach(el => {
    const statusIndicator = el.querySelector('.chat-status');
    if (statusIndicator) {
      statusIndicator.classList.toggle('online', msg.online);
      statusIndicator.classList.toggle('offline', !msg.online);
    }
  });
}

export function onWSOnlineUsers({ detail: onlineUsers }) {
  const chatItems = document.querySelectorAll('.chat-item');
  chatItems.forEach(el => {
    const username = el.dataset.username;
    if (!username) return;

    const statusIndicator = el.querySelector('.chat-status');
    if (statusIndicator) {
      const isOnline = onlineUsers.includes(username);
      statusIndicator.classList.toggle('online', isOnline);
      statusIndicator.classList.toggle('offline', !isOnline);
    }
  });
}
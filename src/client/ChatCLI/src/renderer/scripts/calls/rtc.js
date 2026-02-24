// rtc.js
import { store } from '../core/store.js';

let currentRoom = null;

export async function joinCall(lkUrl, token) {
    if (typeof window.LiveKit === 'undefined') {
        console.error('[RTC] LiveKit library missing. Check index.html script tag.');
        return;
    }

    const LK = window.LiveKit;

    if (currentRoom) {
        await leaveCall();
    }

    currentRoom = new LK.Room({
        adaptiveStream: true,
        dynacast: true,
    });

    currentRoom.on(LK.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === LK.Track.Kind.Audio) {
            track.attach(); 
            console.log(`[RTC] Subscribed to audio track`);
        }
    });

    try {
        console.log(`[RTC] Connecting to ${lkUrl}...`);
        await currentRoom.connect(lkUrl, token);
        await currentRoom.localParticipant.setMicrophoneEnabled(true);

        store.call.isInCall = true;
        store.call.currentCallId = currentRoom.name;
    } catch (error) {
        console.error('[RTC] Connection failed:', error);
        store.call.isInCall = false;
    }
}

export async function leaveCall() {
    if (currentRoom) {
        await currentRoom.disconnect();
        currentRoom = null;
    }
    store.call.isInCall = false;
    store.call.currentCallId = null;
    console.log('[RTC] Left the call');
}

// FIX: Explicitly export endCall so main.js doesn't crash on import
export async function endCall() {
    await leaveCall();
}

export async function toggleMute() {
    if (!currentRoom) return;
    const isEnabled = currentRoom.localParticipant.isMicrophoneEnabled;
    await currentRoom.localParticipant.setMicrophoneEnabled(!isEnabled);
    store.call.isMuted = isEnabled; 
    
    window.dispatchEvent(new CustomEvent('call:muted', { detail: { muted: !isEnabled } }));
}
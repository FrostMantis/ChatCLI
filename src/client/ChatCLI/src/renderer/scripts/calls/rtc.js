// rtc.js
import { store } from '../core/store.js';

let currentRoom = null;

// CDN URLs to try in order
const CDN_URLS = [
  'https://cdn.jsdelivr.net/npm/livekit-client@2.17.2/dist/livekit-client.umd.js',
  'https://unpkg.com/livekit-client@2.17.2/dist/livekit-client.umd.js',
];

let liveKitLoadPromise = null;

function getGlobalLK() {
    return window.LiveKit || window.LiveKitClient;
}

// Helper: dynamically inject LiveKit script
function injectLiveKitScript(cdnUrl = CDN_URLS[0]) {
  if (getGlobalLK()) {
    console.log('[RTC] LiveKit already available on window');
    resolve(getGlobalLK());
    return;
  }
    return new Promise((resolve, reject) => {
        // Check if already loaded
        if (typeof window.LiveKit !== 'undefined') {
            console.log('[RTC] LiveKit already available on window');
            resolve(window.LiveKit);
            return;
        }

        // Check if script with this src already exists
        const existingScript = document.querySelector(`script[src="${cdnUrl}"]`);
        if (existingScript) {
            console.log('[RTC] LiveKit script already in DOM, waiting for load...');
            
            // Wait for it to load
            const checkLoad = () => {
                if (typeof window.LiveKit !== 'undefined') {
                    resolve(window.LiveKit);
                } else {
                    setTimeout(checkLoad, 100);
                }
            };
            
            const timeoutId = setTimeout(() => {
                reject(new Error(`Timeout waiting for cached script ${cdnUrl}`));
            }, 5000);
            
            const originalResolve = resolve;
            resolve = (value) => {
                clearTimeout(timeoutId);
                originalResolve(value);
            };
            
            checkLoad();
            return;
        }

        console.log(`[RTC] Injecting LiveKit script: ${cdnUrl}`);
        const script = document.createElement('script');
        script.src = cdnUrl;
        script.async = true;
        script.crossOrigin = 'anonymous';
        script.referrerPolicy = 'no-referrer';
        
        const timeoutId = setTimeout(() => {
            reject(new Error(`Script load timeout for ${cdnUrl}`));
        }, 8000);
        
        const cleanup = () => clearTimeout(timeoutId);
        
        const handleLoad = () => {
            cleanup();
            console.log('[RTC] LiveKit script loaded from CDN');
            
            // Give it a moment to initialize
            if (typeof window.LiveKit !== 'undefined') {
                console.log('[RTC] ✅ window.LiveKit available immediately');
                resolve(window.LiveKit);
            } else {
                // Wait a bit more
                setTimeout(() => {
                    if (typeof window.LiveKit !== 'undefined') {
                        console.log('[RTC] ✅ window.LiveKit available after delay');
                        resolve(window.LiveKit);
                    } else {
                        reject(new Error('Script loaded but window.LiveKit still not available'));
                    }
                }, 200);
            }
        };
        
        script.onload = handleLoad;
        script.onerror = (err) => {
            cleanup();
            console.error('[RTC] Script load error:', err);
            reject(new Error(`Failed to load from ${cdnUrl}`));
        };
        
        document.head.appendChild(script);
    });
}

async function getLiveKitLibrary() {
    if (liveKitLoadPromise) return liveKitLoadPromise;
    
    liveKitLoadPromise = (async () => {
        // 1. Check current window for either global name
        let LK = window.LiveKit || window.LiveKitClient;
        if (LK) {
            console.log('[RTC] ✅ LiveKit found on window');
            return LK;
        }

        // 2. Try CDN injection with a fallback check for LiveKitClient
        for (const url of CDN_URLS) {
            try {
                console.log(`[RTC] Attempting: ${url}`);
                await injectLiveKitScript(url);
                
                // RE-CHECK both possible names after injection
                LK = window.LiveKit || window.LiveKitClient;
                if (LK) {
                    console.log('[RTC] ✅ LiveKit loaded from CDN');
                    return LK;
                }
            } catch (error) {
                console.warn(`[RTC] Failed ${url}:`, error.message);
            }
        }
        
        throw new Error('LiveKit library not found after loading scripts.');
    })();
    
    return liveKitLoadPromise;
}

export async function joinCall(lkUrl, token) {
    let LK;
    try {
        console.log('[RTC] joinCall: Acquiring LiveKit library...');
        LK = await getLiveKitLibrary();
        console.log('[RTC] joinCall: LiveKit library acquired');
    } catch (error) {
        console.error('[RTC] ❌ Failed to load LiveKit library:', error);
        throw new Error(`Failed to initialize LiveKit: ${error.message}`);
    }

    if (currentRoom) {
        console.log('[RTC] Existing call detected, leaving before joining new call');
        await leaveCall();
    }

    try {
        console.log('[RTC] Creating new Room...');
        currentRoom = new LK.Room({
            adaptiveStream: true,
            dynacast: true,
        });

        currentRoom.on(LK.RoomEvent.TrackSubscribed, (track) => {
            if (track.kind === LK.Track.Kind.Audio) {
                track.attach(); 
                console.log(`[RTC] Subscribed to audio track from ${track.source}`);
            }
        });

        currentRoom.on(LK.RoomEvent.Disconnected, () => {
            console.log('[RTC] Room disconnected');
            store.call.isInCall = false;
        });

        currentRoom.on(LK.RoomEvent.ConnectionQualityChanged, (quality) => {
            console.log(`[RTC] Connection quality: ${quality}`);
        });

        console.log(`[RTC] Connecting to LiveKit server: ${lkUrl}`);
        await currentRoom.connect(lkUrl, token);
        
        console.log('[RTC] Connected! Enabling microphone...');
        await currentRoom.localParticipant.setMicrophoneEnabled(true);

        store.call.isInCall = true;
        store.call.currentCallId = currentRoom.name;
        
        console.log('[RTC] ✅ Successfully joined call:', currentRoom.name);
    } catch (error) {
        console.error('[RTC] ❌ Connection failed:', error);
        currentRoom = null;
        store.call.isInCall = false;
        throw new Error(`Failed to connect to call: ${error.message}`);
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
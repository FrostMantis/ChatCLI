import { showToast } from './ui/toasts.js';

document.addEventListener('DOMContentLoaded', async () => {
  /* =========================
   *  Overlay / Modal helpers
   * ========================= */
  const overlays = {
    welcome:  document.getElementById('welcome-overlay'),
    login:    document.getElementById('login-overlay'),
    register: document.getElementById('register-overlay'),
    verify:   document.getElementById('verify-overlay'),
    reset:    document.getElementById('reset-overlay'),
  };

  try {
    const msg = sessionStorage.getItem('redirect_reason');
    if (msg) {
      showToast(msg, 'warning'); // or 'error' if you prefer
      sessionStorage.removeItem('redirect_reason');
    }
  } catch (_) {}

  function showOverlay(name) {
    Object.entries(overlays).forEach(([k, el]) => {
      if (!el) return;
      el.hidden = (k !== name);
    });
    if (name) {
      if (name === 'welcome') {
        const params = location.search ? location.search : '';
        history.replaceState(null, '', `${params || ' '}`);
      } else {
        const params = location.search ? location.search : '';
        history.replaceState(null, '', `${params}#${name}`);
      }
    }
    if (name === 'verify') updateVerifyUsernameLabel();
    requestAnimationFrame(() => refreshAllGates());
  }

  const openLoginBtn        = document.getElementById('open-login');
  const backToWelcomeBtn    = document.getElementById('back-to-welcome');
  const openRegisterBtn     = document.getElementById('open-register');
  const backFromRegisterBtn = document.getElementById('back-to-welcome-from-register');
  const backFromVerifyBtn   = document.getElementById('back-to-welcome-from-verify');
  const openResetBtn        = document.getElementById('open-reset');
  const backFromResetBtn    = document.getElementById('back-to-login-from-reset');
  const openVerifyFromLoginBtn = document.getElementById('open-verify-from-login');
  const resendCodeBtn       = document.getElementById('resend-code-btn');

  openLoginBtn?.addEventListener('click', () => showOverlay('login'));
  backToWelcomeBtn?.addEventListener('click', () => showOverlay('welcome'));
  openRegisterBtn?.addEventListener('click', () => showOverlay('register'));
  backFromRegisterBtn?.addEventListener('click', () => showOverlay('welcome'));
  backFromVerifyBtn?.addEventListener('click', () => showOverlay('welcome'));
  openResetBtn?.addEventListener('click', () => showOverlay('reset'));
  backFromResetBtn?.addEventListener('click', () => showOverlay('login'));

  const initialTarget = (location.hash || '').replace('#','');
  if (initialTarget && overlays[initialTarget]) showOverlay(initialTarget);
  else showOverlay('welcome');

  resendCodeBtn?.addEventListener('click', async () => {
    const username = getUsernameFromParams();
    if (!username) {
      showToast('Missing username for verification. Please register again.', 'error');
      return;
    }
    try {
      await window.api.request('/user/resend-verification', {
        body: JSON.stringify({ username })
      });
      showToast('Verification code resent! Check your email.', 'info');
    } catch (err) {
      showToast('Failed to resend code: ' + (err.message || 'Server error'), 'error');
    }
  });

  openVerifyFromLoginBtn?.addEventListener('click', () => {
    const usernameInput = document.querySelector('#login-form input[name="username"]');
    const username = usernameInput?.value.trim() || '';

    if (!username) {
      showToast('Please enter your username first to verify your email.', 'error');
      return;
    }

    setUsernameParam(username);
    showOverlay('verify');
  });

  window.addEventListener('hashchange', () => {
    const target = (location.hash || '').replace('#','');
    if (target && overlays[target]) showOverlay(target);
  });

  // URL param helpers for verify
  function getUsernameFromParams() {
    const params = new URLSearchParams(location.search);
    return params.get('username') || '';
  }
  function setUsernameParam(username) {
    const params = new URLSearchParams(location.search);
    if (username) params.set('username', username);
    else params.delete('username');
    const hash = location.hash || '';
    history.replaceState(null, '', `?${params.toString()}${hash}`);
  }
  function updateVerifyUsernameLabel() {
    const el = document.getElementById('verify-username-label');
    if (!el) return;
    const name = getUsernameFromParams();
    el.textContent = name ? name : 'your account';
  }

  /* =========================
   *  Online / Offline + status
   * ========================= */
  const retryBtn = document.getElementById('retry-btn');
  let online = false;
  const CHECK_INTERVAL = 10_000;

  let accessToken = null;
  function setAccess(token) {
    accessToken = token;
    if (window.api && typeof window.api.setAccessToken === 'function') {
      window.api.setAccessToken(token);
    }
  }
  function clearAccess() { setAccess(null); }

  function disableButtons() {
    document.querySelectorAll('[data-requires-online]').forEach(btn => btn.disabled = true);
    window.dispatchEvent(new CustomEvent('online-status-changed', { detail: false }));
  }
  function enableButtons() {
    document.querySelectorAll('[data-requires-online]').forEach(btn => btn.disabled = false);
    window.dispatchEvent(new CustomEvent('online-status-changed', { detail: true }));
  }

  function setServerStatus(isOnline, msg) {
    const statusTextEl = document.querySelector('.status-text');
    if (!statusTextEl) return;
    const dotEl = document.querySelector('.dot');
    if (dotEl) {
      dotEl.style.background = isOnline ? 'var(--accent)' : 'gray';
      dotEl.style.boxShadow = isOnline
        ? '0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent)'
        : 'none';
    }
    statusTextEl.textContent = msg;
  }

  async function tryAutoLoginIfNeeded() {
    // After a WS failure / forced redirect, we skip *one* auto-login attempt
    try {
      if (sessionStorage.getItem('skip_auto_login_once') === '1') {
        sessionStorage.removeItem('skip_auto_login_once');
        return;
      }
    } catch (_) {}

    if (accessToken) return;
    if (!window.secureStore) return;
    const accountId = await window.secureStore.get('username');
    if (!accountId) return;
    if (!window.auth || typeof window.auth.refresh !== 'function') return;

    try {
      const res = await window.auth.refresh(accountId); // { ok, access_token }
      if (res && res.ok && res.access_token) {
        setAccess(res.access_token);
        setTimeout(() => { location.href = 'main.html'; }, 200);
      }
    } catch { /* ignore */ }
  }

  async function checkServer() {
    setServerStatus(false, 'Checking server…');
    try {
      const data = await window.api.verifyConnection({ version: 'electron_app' });
      const ok = (typeof data === 'string') || (data && (data.response || data.message));
      if (ok) {
        online = true;
        setServerStatus(true, 'Server is online');
        enableButtons();
        tryAutoLoginIfNeeded();
      } else {
        const errMsg = data && (data.message || data.error) || 'Unknown error';
        throw new Error(errMsg);
      }
    } catch (err) {
      online = false;
      setServerStatus(false, `Offline: ${err.message}`);
      disableButtons();
    } finally {
      refreshAllGates();
    }
  }

  retryBtn?.addEventListener('click', checkServer);
  setInterval(() => { if (!online) checkServer(); }, CHECK_INTERVAL);
  checkServer();

  /* =========================
   *  FORM GATING (core)
   *  Disable submit buttons unless: online && form.valid && extraRules()
   * ========================= */
  const gates = []; // each: { form, button, extra }

  // --- Password rule validator (Register only) ---
  function passwordStrongEnough(password) {
    // At least one lowercase, one uppercase, one number, one special char, and 8+ chars total
    const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;
    return regex.test(password);
  }

  function bindFormGate(form, submitButton, extraValidator = null, disableOnInvalid = true) {
    // track "touched" and "tried submit" states
    if (!form.__state) form.__state = { tried: false };
    const state = form.__state;
  
    // mark invalid fields only if user tried submit or the field was touched
    function markInvalidFields() {
      const inputs = form.querySelectorAll('input, textarea, select');
      for (const input of inputs) {
        const touched = input.dataset.touched === '1';
        const valid = input.checkValidity();
        if ((state.tried || touched) && !valid) input.classList.add('invalid');
        else input.classList.remove('invalid');
      }
    }
  
    const compute = () => {
      const isVisible = form.closest('.overlay')?.hidden === false;
      const baseValid = form.checkValidity();
      const extraOk   = extraValidator ? extraValidator() : true;
  
      // gating behavior
      const ok = baseValid && extraOk;
      const shouldDisable =
        !online || !isVisible || (disableOnInvalid && !ok);
  
      submitButton.disabled = shouldDisable;
  
      // only mark red *after* attempt or when fields are touched (not immediately on open)
      if (isVisible) markInvalidFields();
    };
  
    // mark an input as "touched" on blur or input
    form.addEventListener('blur', (e) => {
      if (e.target.matches('input, textarea, select')) {
        e.target.dataset.touched = '1';
        compute();
      }
    }, true);
    form.addEventListener('input', compute, true);
    form.addEventListener('change', compute, true);
  
    // when server status changes
    window.addEventListener('online-status-changed', compute);
  
    // intercept submit to show errors if invalid
    form.addEventListener('submit', (e) => {
      const baseValid = form.checkValidity();
      const extraOk   = extraValidator ? extraValidator() : true;
      if (!baseValid || !extraOk) {
        state.tried = true;
        e.preventDefault();
        e.stopImmediatePropagation();
        compute();
        showToast('Please fill all required fields correctly.', 'error');
      }
    }, true);
  
    gates.push({ form, button: submitButton, extra: extraValidator, compute, disableOnInvalid });
    compute();
  }
  
  function refreshAllGates() { gates.forEach(g => g.compute()); }
  

  /* =========================
   *  AUTH: Login
   * ========================= */
  const loginForm = document.getElementById('login-form');
  if (loginForm) {
    const loginSubmitBtn = document.getElementById('login-submit');

    // gate: requires username + password (HTML already has required/minlength)
    bindFormGate(loginForm, loginSubmitBtn, null, /* disableOnInvalid= */ true);

    loginForm.addEventListener('submit', async e => {
      var rememberUserBtn = document.getElementById('remember-user-box').checked;
      e.preventDefault();
      if (loginSubmitBtn.disabled) return;

      loginSubmitBtn.disabled = true;
      loginSubmitBtn.textContent = 'Logging in…';

      try {
        const username = loginForm.username.value.trim();
        const password = loginForm.password.value;
        const res = await window.api.login({ username, password });

        setAccess(res.access_token);

        if (window.secureStore?.set) {
            await window.secureStore.set('session_token', res.access_token);
            await window.secureStore.set('username', username);
        }

        if (window.auth?.storeRefresh && rememberUserBtn) {
          await window.auth.storeRefresh(username, res.refresh_token);
        }

        showToast('Login successful! Redirecting…', 'info');
        setTimeout(() => location.href = 'main.html', 1000);
      } catch (err) {
        showToast('Login failed: ' + (err.message || 'Unknown error'), 'error');
        loginSubmitBtn.textContent = 'Log In';
      } finally {
        refreshAllGates();
      }
    });
  }

/* =========================
 *  AUTH: Register
 * ========================= */
const registerForm = document.getElementById('register-form');
if (registerForm) {
  const registerSubmitBtn = document.getElementById('register-submit');

  // Elements for password rules
  const infoBtn     = registerForm.querySelector('.info[data-for="password"]');
  const ruleUpper   = registerForm.querySelector('.tooltip .rules [data-rule="upper"]');
  const ruleLower   = registerForm.querySelector('.tooltip .rules [data-rule="lower"]');
  const ruleNumber  = registerForm.querySelector('.tooltip .rules [data-rule="number"]');
  const ruleSpecial = registerForm.querySelector('.tooltip .rules [data-rule="special"]');
  const ruleLength  = registerForm.querySelector('.tooltip .rules [data-rule="length"]');

  // Helper: overall password rules
  function passwordStrongEnough(pwd) {
    return /[A-Z]/.test(pwd) &&
           /[a-z]/.test(pwd) &&
           /\d/.test(pwd) &&
           /[^A-Za-z0-9]/.test(pwd) &&
           pwd.length >= 8;
  }

  // Gate function for register (rules + confirm match)
  const passwordRulesOk = () => {
    const p  = registerForm.password?.value ?? '';
    const cp = registerForm.confirm?.value ?? '';
    return passwordStrongEnough(p) && p === cp;
  };

  if (typeof bindFormGate === 'function') {
    bindFormGate(registerForm, registerSubmitBtn, passwordRulesOk, /* disableOnInvalid */ true);
  }

  function updatePwdRulesVisuals(pwd) {
    const rules = {
      upper:   /[A-Z]/.test(pwd),
      lower:   /[a-z]/.test(pwd),
      number:  /\d/.test(pwd),
      special: /[^A-Za-z0-9]/.test(pwd),
      length:  pwd.length >= 8,
    };

    // Toggle each rule row + symbol safely
    ([
      ruleUpper   && [ruleUpper,   rules.upper],
      ruleLower   && [ruleLower,   rules.lower],
      ruleNumber  && [ruleNumber,  rules.number],
      ruleSpecial && [ruleSpecial, rules.special],
      ruleLength  && [ruleLength,  rules.length],
    ].filter(Boolean)).forEach(([el, pass]) => {
      el.classList.toggle('ok',  pass);
      el.classList.toggle('bad', !pass && pwd.length > 0);
      const sym = el.querySelector('.symbol');
      if (sym) sym.textContent = pass ? '✓' : '✗';
    });

    // Tint the ⓘ icon overall (if present)
    const strong = Object.values(rules).every(Boolean);
    if (infoBtn) {
      infoBtn.classList.toggle('valid',  strong && pwd.length > 0);
      infoBtn.classList.toggle('invalid', !strong && pwd.length > 0);
    }
  }

  // Live update rules as user types
  registerForm.password?.addEventListener('input', () => {
    updatePwdRulesVisuals(registerForm.password.value);
    if (typeof refreshAllGates === 'function') refreshAllGates();
  });

  // Run once (covers autofill)
  try { updatePwdRulesVisuals(registerForm.password?.value || ''); } catch {}

  // Confirm must exactly match to clear red
  const confirmInput  = registerForm.querySelector('input[name="confirm"]');
  const passwordInput = registerForm.querySelector('input[name="password"]');
  function updateConfirmMatchVisual() {
    if (!confirmInput || !passwordInput) return;
    const same = passwordInput.value === confirmInput.value && confirmInput.value !== '';
    if (same) confirmInput.classList.remove('invalid');
    else if (registerForm.__state?.tried || confirmInput.dataset.touched === '1') {
      confirmInput.classList.add('invalid');
    }
  }
  confirmInput?.addEventListener('input', updateConfirmMatchVisual);
  confirmInput?.addEventListener('blur', () => {
    confirmInput.dataset.touched = '1';
    updateConfirmMatchVisual();
  });
  passwordInput?.addEventListener('input', updateConfirmMatchVisual);

  // Submit
  registerForm.addEventListener('submit', async e => {
    e.preventDefault();
    const baseValid = registerForm.checkValidity();
    const extraOk   = passwordRulesOk();
    if (!baseValid || !extraOk) return;

    registerSubmitBtn.disabled = true;
    registerSubmitBtn.textContent = 'Registering…';

    try {
      const username    = registerForm.username.value.trim();
      const email       = registerForm.email.value.trim();
      const password    = registerForm.password.value;
      const invite_code = registerForm.invite_code.value.trim();

      await window.api.register({ username, email, password, invite_code });

      setUsernameParam(username);
      showOverlay('verify'); // open inline verify modal
      showToast('Account created! Enter your 6-digit code to verify.', 'info');
      registerForm.reset();
      try { updatePwdRulesVisuals(''); } catch {}
      updateConfirmMatchVisual();
    } catch (err) {
      showToast('Registration failed: ' + (err.message || 'Unknown error'), 'error');
      registerSubmitBtn.textContent = 'Register';
    } finally {
      if (typeof refreshAllGates === 'function') refreshAllGates();
    }
  });
}

  /* =========================
   *  AUTH: Verify (6-digit)
   * ========================= */
  const verifyForm = document.getElementById('verify-form');
  if (verifyForm) {
    const verifySubmitBtn = document.getElementById('verify-submit');

    const verifyCodeOk = () => /^\d{6}$/.test((verifyForm.token.value || '').trim());

    bindFormGate(verifyForm, verifySubmitBtn, verifyCodeOk, /* disableOnInvalid= */ false);

    verifyForm.addEventListener('submit', async e => {
      e.preventDefault();
      if (verifySubmitBtn.disabled) return;

      verifySubmitBtn.disabled = true;
      verifySubmitBtn.textContent = 'Verifying…';

      const username    = getUsernameFromParams();
      const email_token = (verifyForm.token.value || '').trim();

      if (!username) {
        showToast('Missing username for verification. Please register again.', 'error');
        verifySubmitBtn.textContent = 'Verify';
        refreshAllGates();
        return;
      }

      try {
        await window.api.verifyEmail({ username, email_token });
        showToast('Email verified! You can log in now.', 'info');
        verifyForm.reset();
        setUsernameParam('');
        showOverlay('login');
      } catch (err) {
        showToast('Verification failed: ' + (err.message || 'Server error'), 'error');
        verifySubmitBtn.textContent = 'Verify';
      } finally {
        refreshAllGates();
      }
    });
  }

  /* =========================
   *  Reset password request
   * ========================= */
  const resetForm = document.getElementById('reset-password-form');
  if (resetForm) {
    const resetBtn = document.getElementById('reset-password-submit');

    // gate: username required (HTML has required)
    bindFormGate(resetForm, resetBtn, null, /* disableOnInvalid= */ false);

    resetForm.addEventListener('submit', async e => {
      e.preventDefault();
      if (resetBtn.disabled) return;

      resetBtn.disabled = true;
      resetBtn.textContent = 'Sending…';

      try {
        const username = resetForm.username.value.trim();
        await window.api.request('/user/reset-password-request', {
          body: JSON.stringify({ username })
        });
        showToast('If the username exists, a reset link has been sent. Check your email.', 'info');
        setTimeout(() => showOverlay('login'), 800);
        resetForm.reset();
      } catch (err) {
        showToast('Reset failed: ' + (err.message || 'Unknown error'), 'error');
        resetBtn.textContent = 'Send reset email';
      } finally {
        refreshAllGates();
      }
    });
  }
});

/* =========================
 *  Eye toggle for passwords
 * ========================= */
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-toggle-password]');
  if (!btn) return;
  const input = btn.parentElement.querySelector('input[type="password"], input[type="text"]');
  if (!input) return;
  const nextType = input.type === 'password' ? 'text' : 'password';
  input.type = nextType;
  btn.setAttribute('aria-label', nextType === 'password' ? 'Show password' : 'Hide password');
});
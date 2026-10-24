(() => {
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  }
  let installEvent;
  const button = document.querySelector('#install-app');
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installEvent = event;
    if (button) button.hidden = false;
  });
  if (button) button.addEventListener('click', async () => {
    if (installEvent) {
      await installEvent.prompt();
      installEvent = null;
      button.hidden = true;
    }
  });
  const offline = document.querySelector('#offline-banner');
  let serverAvailable = navigator.onLine;
  let checking;
  const connectivity = () => {
    const available = navigator.onLine && serverAvailable;
    if (offline) offline.hidden = available;
    document.querySelectorAll('form[method="post"] button[type="submit"], form[method="post"] button:not([type])').forEach(control => {
      if (!available && !control.disabled) {
        control.dataset.offlineDisabled = '1';
        control.disabled = true;
      } else if (available && control.dataset.offlineDisabled) {
        control.disabled = false;
        delete control.dataset.offlineDisabled;
      }
    });
  };
  const probe = () => {
    if (checking) return checking;
    checking = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 4000);
      try {
        if (!navigator.onLine) throw new Error('offline');
        const response = await fetch('/ligacao/', {
          cache: 'no-store', credentials: 'same-origin', redirect: 'error', signal: controller.signal
        });
        serverAvailable = response.status === 204;
      } catch (_) { serverAvailable = false; }
      finally { clearTimeout(timeout); connectivity(); }
      return serverAvailable;
    })().finally(() => { checking = null; });
    return checking;
  };
  window.addEventListener('online', probe);
  window.addEventListener('offline', () => { serverAvailable = false; connectivity(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) probe(); });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.method.toLowerCase() !== 'post') return;
    // Keep native form submission, named actions, validation and navigation semantics.
    // A probe cannot prove a subsequent transaction will succeed; check known state.
    if (!navigator.onLine || !serverAvailable) {
      event.preventDefault();
      connectivity();
      probe();
    }
  });
  connectivity();
  probe();
  setInterval(() => { if (!document.hidden) probe(); }, 10000);
})();

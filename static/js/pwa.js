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
  const connectivity = () => {
    if (offline) offline.hidden = navigator.onLine;
    document.querySelectorAll('form[method="post"] button[type="submit"], form[method="post"] button:not([type])').forEach(control => {
      if (!navigator.onLine && !control.disabled) {
        control.dataset.offlineDisabled = '1';
        control.disabled = true;
      } else if (navigator.onLine && control.dataset.offlineDisabled) {
        control.disabled = false;
        delete control.dataset.offlineDisabled;
      }
    });
  };
  window.addEventListener('online', connectivity);
  window.addEventListener('offline', connectivity);
  document.addEventListener('submit', event => {
    if (!navigator.onLine && event.target.method.toLowerCase() === 'post') {
      event.preventDefault();
      connectivity();
    }
  });
  connectivity();
})();

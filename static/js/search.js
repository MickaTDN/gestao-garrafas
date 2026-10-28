/* Read-only searches preserve every unsaved operation field. No offline writes. */
(() => {
  const form = document.querySelector('form[data-live-search]');
  if (!form) return;
  const input = form.querySelector('[name=q]');
  const target = document.getElementById(form.dataset.liveSearch);
  const operation = document.getElementById('operation-form');
  let timer, controller, generation = 0;
  const search = async (url) => {
    const current = ++generation;
    if (controller) controller.abort();
    controller = new AbortController();
    url.searchParams.set('partial', form.dataset.partial);
    if (form.dataset.partial === 'references') target.hidden = !form.dataset.inventory && !input.value.trim();
    target.setAttribute('aria-busy', 'true');
    target.querySelectorAll('button').forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(url, {signal: controller.signal, cache: 'no-store', credentials: 'same-origin'});
      if (response.redirected) { location.assign(response.url); return; }
      if (!response.ok) throw new Error('search');
      const html = await response.text();
      if (current !== generation) return;
      target.innerHTML = html; // Escaped, authenticated same-origin server template.
      url.searchParams.delete('partial');
      history.replaceState(null, '', url);
      target.removeAttribute('aria-busy');
    } catch (error) {
      if (error.name === 'AbortError' || current !== generation) return;
      target.textContent = 'Não foi possível pesquisar. Verifique a ligação e tente novamente.';
      target.removeAttribute('aria-busy');
    }
  };
  const submit = () => {
    const url = new URL(form.action || location.href);
    url.search = new URLSearchParams(new FormData(form)).toString();
    search(url);
  };
  const changed = () => {
    generation++;
    if (controller) controller.abort();
    target.setAttribute('aria-busy', 'true');
    target.querySelectorAll('button').forEach(button => { button.disabled = true; });
    clearTimeout(timer); timer = setTimeout(submit, 180);
  };
  input.addEventListener('input', changed);
  form.querySelectorAll('select').forEach(select => select.addEventListener('change', changed));
  form.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); submit(); });
  target.addEventListener('click', event => {
    const chosen = event.target.closest('[data-open-line]');
    if (chosen) {
      const line = document.getElementById('inventory-line-' + chosen.dataset.openLine);
      if (line) { event.preventDefault(); line.open = true; line.scrollIntoView({block: 'start'}); }
      return;
    }
    const link = event.target.closest('a');
    if (link && link.getAttribute('href').startsWith('?')) { event.preventDefault(); search(new URL(link.href)); }
  });
  if (operation) operation.addEventListener('submit', () => {
    document.getElementById('search-query').value = input.value;
  });
  // The form can be used while a deferred script is still downloading. Events
  // from that interval cannot be replayed: reconcile the current controls with
  // their server-rendered defaults after all deferred initializers (including
  // location/sector filtering) have run, so no stale sector is sent with a new location.
  document.addEventListener('DOMContentLoaded', () => {
    const editedSelect = Array.from(form.querySelectorAll('select')).some(select => {
      const initial = Array.from(select.options).find(option => option.defaultSelected) || select.options[0];
      return select.value !== (initial?.value || '');
    });
    if (input.value !== input.defaultValue || editedSelect) {
      clearTimeout(timer);
      submit();
    }
  }, {once: true});
})();

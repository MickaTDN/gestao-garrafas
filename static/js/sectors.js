/* Configured database options only; remove incompatible options from native menus. */
(() => {
  const collator = new Intl.Collator('pt', {numeric: true, sensitivity: 'base'});
  document.querySelectorAll('select').forEach(sector => {
    if (!sector.querySelector('option[data-location]')) return;
    const locationName = sector.name.replace(/sector$/, 'location');
    const location = Array.from(sector.form.elements).find(element => element.name === locationName);
    if (!location) return;
    const options = Array.from(sector.options).map(option => option.cloneNode(true));
    const filter = (changed = false) => {
      const selected = changed ? '' : sector.value;
      const visible = options.filter(option => !option.value || !location.value || option.dataset.location === location.value);
      visible.sort((a, b) => !a.value ? -1 : !b.value ? 1 : collator.compare(a.textContent, b.textContent));
      sector.replaceChildren(...visible.map(option => option.cloneNode(true)));
      sector.value = visible.some(option => option.value === selected) ? selected : '';
    };
    location.addEventListener('change', () => filter(true));
    filter();
  });
})();

/* Options come from the database; the server independently validates ownership. */
(() => {
  document.querySelectorAll('select').forEach(sector => {
    if (!sector.querySelector('option[data-location]')) return;
    const locationName = sector.name.replace(/sector$/, 'location');
    const location = Array.from(sector.form.elements).find(element => element.name === locationName);
    if (!location) return;
    const filter = () => {
      Array.from(sector.options).forEach(option => {
        option.hidden = Boolean(option.value && option.dataset.location !== location.value);
        option.disabled = option.hidden;
      });
      if (sector.selectedOptions.length && sector.selectedOptions[0].disabled) sector.value = '';
    };
    location.addEventListener('change', filter);
    filter();
  });
})();

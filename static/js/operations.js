/* Progressive preview only; the server recalculates and validates every quantity. */
(() => {
  const form = document.querySelector('#operation-form');
  if (!form) return;
  document.querySelectorAll('.operation-line').forEach(line => {
    const boxes = line.querySelector('input[name$="-boxes"]');
    const units = line.querySelector('input[name$="-units"]');
    const update = () => {
      const capacity = line.dataset.capacity === '' ? null : Number(line.dataset.capacity);
      const stock = Number(line.dataset.stock);
      let total = null;
      if (boxes.value !== '' || units.value !== '') {
        const b = boxes.value === '' ? 0 : Number(boxes.value);
        const u = units.value === '' ? 0 : Number(units.value);
        if (Number.isInteger(b) && Number.isInteger(u) && b >= 0 && u >= 0 && (!b || capacity)) total = b * (capacity || 0) + u;
      }
      const difference = total === null ? null : form.dataset.kind === 'inventory' ? total - stock : total * (form.dataset.kind === 'exit' ? -1 : 1);
      const after = difference === null ? null : stock + difference;
      const equivalent = after !== null && capacity ? ` (${Math.floor(after / capacity)} cx + ${after % capacity} un.)` : '';
      line.querySelector('.line-total').textContent = total === null ? '—' : total;
      line.querySelector('.line-after').textContent = after === null ? '—' : `${after} garrafas${equivalent}`;
      line.querySelector('.line-difference').textContent = difference === null ? '—' : (difference > 0 ? '+' : '') + difference;
    };
    const location = line.querySelector('select[name$="-target_location"]');
    const sector = line.querySelector('select[name$="-target_sector"]');
    if (location && sector) {
      const filterSectors = () => {
        Array.from(sector.options).forEach(option => {
          option.hidden = Boolean(option.value && option.dataset.location !== location.value);
          option.disabled = option.hidden;
        });
        if (sector.selectedOptions.length && sector.selectedOptions[0].disabled) sector.value = '';
      };
      location.addEventListener('change', filterSectors);
      filterSectors();
    }
    boxes.addEventListener('input', update);
    units.addEventListener('input', update);
    update();
  });
})();

(() => {
  const canvas = document.querySelector('#signature-canvas');
  if (!canvas) return;
  const input = document.querySelector('input[name="signature_data"]');
  const choice = document.querySelector('select[name="validation"]');
  const panel = document.querySelector('#signature-panel');
  const ctx = canvas.getContext('2d');
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.strokeStyle = '#172c29';
  let drawing = false;
  const point = event => {
    const rect = canvas.getBoundingClientRect();
    return [(event.clientX - rect.left) * canvas.width / rect.width, (event.clientY - rect.top) * canvas.height / rect.height];
  };
  canvas.addEventListener('pointerdown', event => {
    if (!event.isPrimary || event.button > 0) return;
    event.preventDefault();
    drawing = true;
    canvas.setPointerCapture(event.pointerId);
    ctx.beginPath();
    ctx.moveTo(...point(event));
  });
  canvas.addEventListener('pointermove', event => {
    if (!drawing) return;
    event.preventDefault();
    ctx.lineTo(...point(event));
    ctx.stroke();
  });
  const finish = () => {
    if (drawing) input.value = canvas.toDataURL('image/png');
    drawing = false;
  };
  canvas.addEventListener('pointerup', finish);
  canvas.addEventListener('pointercancel', finish);
  document.querySelector('#signature-clear').addEventListener('click', () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    input.value = '';
  });
  const select = () => {
    panel.hidden = choice.value !== 'signed';
    if (panel.hidden) input.value = '';
  };
  choice.addEventListener('change', select);
  select();
})();

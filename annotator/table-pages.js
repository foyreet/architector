'use strict';

// Keep the DOM small while making every result row reachable.
window.tablePages = (container, rows, renderRows) => {
  const body = document.createElement('div');
  container.replaceChildren(body);
  const pageSize = 50;
  if (rows.length <= pageSize) {
    renderRows(body, rows);
    return;
  }
  const controls = document.createElement('div');
  const previous = document.createElement('button'), next = document.createElement('button');
  const status = document.createElement('span');
  previous.type = next.type = 'button';
  previous.textContent = '← Предыдущие';
  next.textContent = 'Следующие →';
  status.setAttribute('aria-live', 'polite');
  controls.className = 'insight-actions';
  controls.append(previous, status, next);
  container.prepend(controls);
  let start = 0;
  function show(offset) {
    start = offset;
    const end = Math.min(start + pageSize, rows.length);
    status.textContent = `Строки ${start + 1}–${end} из ${rows.length}`;
    previous.disabled = start === 0;
    next.disabled = end === rows.length;
    body.replaceChildren();
    renderRows(body, rows.slice(start, end));
  }
  previous.onclick = () => show(start - pageSize);
  next.onclick = () => show(start + pageSize);
  show(0);
};

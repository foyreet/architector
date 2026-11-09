'use strict';
window.Experiments = function ({api, context, history}) {
  const $ = id => document.getElementById(id);
  const dialog = $('experiments-dialog'), notesDialog = $('experiment-notes-dialog');
  let notesAnchor = null;
  const labels = {ready: 'Готово', paused: 'Ожидает продолжения', pending: 'Ожидает шага', error: 'Ошибка', cancelled: 'Остановлен', running: 'Работает', waiting: 'Ожидает', skipped: 'Пропущен'};
  let runs = [], scope = {}, generation = 0;
  let editing = null, dirty = false, saving = false;
  function el(tag, text, className) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; }
  const title = run => run.experiment.title || run.name || run.id.slice(0, 8);
  const stamp = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ru-RU') : '—';
  const seconds = value => typeof value === 'number' ? value.toLocaleString('ru-RU', {maximumFractionDigits: 2}) + ' с' : '—';
  const request = (action, body = {}) => api('/api/pipelines/' + action, {...body, project_id: scope.project_id});
  function discard() { return !dirty || confirm('Закрыть несохранённое описание эксперимента?'); }
  function closeNotes() {
    const identity = editing?.id, wasOpen = notesDialog.open;
    editing = null; dirty = false;
    if (wasOpen) notesDialog.close();
    $('experiment-notes').hidden = true;
    if (wasOpen && identity) {
      const row = [...$('experiments-runs').children].find(row => row.dataset.runId === identity);
      row?.querySelector('.experiment-notes-action')?.focus({preventScroll: true});
    }
  }
  function positionNotes() {
    if (!notesDialog.open || !notesAnchor) return;
    const margin = 12, rect = notesDialog.getBoundingClientRect();
    notesDialog.style.left = Math.max(margin, Math.min(notesAnchor.right - rect.width, innerWidth - rect.width - margin)) + 'px';
    notesDialog.style.top = Math.max(margin, Math.min(notesAnchor.top, innerHeight - rect.height - margin)) + 'px';
  }
  window.addEventListener('resize', positionNotes);
  new ResizeObserver(positionNotes).observe(notesDialog);
  notesDialog.addEventListener('cancel', event => {
    event.preventDefault();
    if (!saving && discard()) closeNotes();
  });
  function setMessage(text) { $('experiments-message').textContent = text; }

  function renderList() {
    $('experiments-empty').hidden = runs.length !== 0;
    dialog.querySelectorAll('.experiments-history-only').forEach(el => { el.hidden = runs.length === 0; });
    const search = $('experiments-search').value.toLocaleLowerCase();
    const status = $('experiments-filter').value;
    let visible = runs.filter(r => (!status || r.status === status || status === 'running' && r.status === 'waiting') &&
      [title(r), r.id, r.experiment.hypothesis, ...r.experiment.tags].join(' ').toLocaleLowerCase().includes(search));
    if ($('experiments-sort').value === 'duration') visible.sort((a, b) => (a.duration ?? Infinity) - (b.duration ?? Infinity));
    const body = $('experiments-runs'); body.replaceChildren();
    for (const run of visible) {
      const row = el('tr'); row.dataset.runId = run.id;
      const cell = el('td'); const name = el('button', title(run), 'experiment-name');
      name.onclick = () => openRun(run); cell.append(name, el('small', run.id.slice(0, 8), 'muted')); row.append(cell);
      row.append(el('td', labels[run.status] || run.status, 'experiment-state ' + run.status), el('td', stamp(run.created_at)), el('td', seconds(run.duration)), el('td', run.experiment.tags.join(', ') || '—'));
      const actions = el('td'); const open = el('button', 'Открыть запуск');
      open.onclick = () => openRun(run);
      const notes = el('button', 'Заметки', 'experiment-notes-action');
      notes.onclick = () => { if (!saving && discard()) editNotes(run, notes); };
      actions.append(open, notes); row.append(actions); body.append(row);
    }
    if (!visible.length) { const row = el('tr'), cell = el('td', runs.length ? 'Нет запусков по выбранным условиям.' : 'Запусков пока нет. Закройте экран и нажмите «Запустить пайплайн».', 'muted'); cell.colSpan = 6; row.append(cell); body.append(row); }
  }

  async function load() {
    const current = ++generation;
    $('experiments-empty').hidden = true;
    $('experiments-refresh').disabled = true; setMessage('Загружаю историю…');
    try {
      const result = await request('experiments');
      if (current !== generation || !dialog.open) return;
      runs = result.runs;
      renderList(); setMessage(runs.length ? `Показаны последние ${runs.length} запусков (не более 100). Для активных запусков нажмите «Обновить».` : '');
    } catch (error) { if (current === generation) setMessage(error.message); }
    finally { if (current === generation) $('experiments-refresh').disabled = false; }
  }

  async function openRun(run) {
    if (saving || !discard()) return;
    closeNotes(); dialog.close();
    try { await history(run.id); }
    catch (error) { alert(error.message); }
  }

  function editNotes(run, trigger) {
    notesAnchor = trigger.getBoundingClientRect();
    editing = run; dirty = false; $('experiment-notes').hidden = false;
    $('experiment-notes-title').textContent = 'Заметки · ' + title(run);
    $('experiment-name').value = run.experiment.title;
    $('experiment-tags').value = run.experiment.tags.join(', ');
    $('experiment-hypothesis').value = run.experiment.hypothesis;
    $('experiment-conclusion').value = run.experiment.conclusion;
    $('experiment-note-status').textContent = '';
    notesDialog.showModal(); positionNotes();
    $('experiment-name').focus({preventScroll: true});
  }
  $('experiment-notes').oninput = () => { dirty = true; };
  $('experiment-notes').onsubmit = async event => {
    event.preventDefault(); if (!editing || saving) return;
    saving = true; $('experiment-note-save').disabled = true;
    const fields = [...$('experiment-notes').querySelectorAll('input, textarea')]; fields.forEach(f => { f.disabled = true; });
    const current = generation;
    const experiment = {revision: editing.experiment.revision, title: $('experiment-name').value,
      tags: $('experiment-tags').value.split(',').map(t => t.trim()).filter(Boolean), hypothesis: $('experiment-hypothesis').value, conclusion: $('experiment-conclusion').value};
    try {
      const result = await request('experiment', {run_id: editing.id, experiment});
      if (current !== generation) return;
      runs = runs.map(r => r.id === result.id ? result : r); editing = result; dirty = false;
      renderList(); $('experiment-note-status').textContent = 'Описание сохранено';
    } catch (error) { if (current === generation) $('experiment-note-status').textContent = error.message; }
    finally { saving = false; $('experiment-note-save').disabled = false; fields.forEach(f => { f.disabled = false; }); }
  };
  $('experiment-notes-close').onclick = () => { if (!saving && discard()) closeNotes(); };
  $('experiments').onclick = () => {
    if (dialog.open || !window.WorkspaceNavigation.show(dialog, 'experiments')) return;
    scope = context(); closeNotes(); runs = [];
    $('experiments-scope').textContent = scope.name;
    $('experiments-search').value = ''; $('experiments-filter').value = '';
    renderList(); load();
  };
  window.addEventListener('architect-project-change', () => {
    if (!dialog.open) return;
    const next = context(), changed = next.project_id !== scope.project_id;
    scope = next; $('experiments-scope').textContent = scope.name;
    if (changed) { closeNotes(); runs = []; renderList(); load(); }
  });
  $('experiments-to-schema').onclick = () => $('schema-tab').click();
  $('close-experiments').onclick = () => { if (!saving && discard()) { closeNotes(); dialog.close(); } };
  dialog.addEventListener('cancel', event => { if (saving || !discard()) event.preventDefault(); else closeNotes(); });
  dialog.addEventListener('close', () => { if (!dialog.open) { ++generation; closeNotes(); } });
  $('experiments-refresh').onclick = () => { if (!saving && discard()) { closeNotes(); load(); } };
  for (const id of ['experiments-search', 'experiments-filter', 'experiments-sort']) $(id).addEventListener('input', renderList);
};


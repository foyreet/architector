'use strict';

// Project screens use non-modal dialogs, preserving their close/cancel lifecycle.
window.WorkspaceNavigation = (() => {
  const $ = id => document.getElementById(id);
  const tabs = {overview: 'overview-tab', schema: 'schema-tab', experiments: 'experiments', results: 'results-tab', proposals: 'project-proposals'};
  let active = null;
  const observed = new WeakSet();
  function select(view) {
    for (const [key, id] of Object.entries(tabs)) {
      if (key === view) $(id).setAttribute('aria-current', 'page');
      else $(id).removeAttribute('aria-current');
    }
    $('schema-view').hidden = view !== 'schema';
    $('project-panel').hidden = view === 'schema';
    $('schema-actions').hidden = view !== 'schema';
  }
  function restore(dialog) {
    if (dialog.open) return;
    if (active === dialog) { active = null; select('schema'); }
    dialog.classList.remove('project-screen');
    document.body.append(dialog);
  }
  function leave() {
    if (!active) return true;
    if (!active.dispatchEvent(new Event('cancel', {cancelable: true}))) return false;
    const previous = active;
    previous.close(); restore(previous);
    return true;
  }
  function show(dialog, view = null) {
    if (active && active !== dialog && !leave()) return false;
    if (dialog.open && (!view || !dialog.classList.contains('project-screen'))) {
      dialog.close(); restore(dialog);
    }
    if (!observed.has(dialog)) {
      observed.add(dialog);
      dialog.addEventListener('close', () => restore(dialog));
    }
    if (view) {
      active = dialog;
      $('project-panel').append(dialog); dialog.classList.add('project-screen');
      select(view);
      if (!dialog.open) dialog.show();
    } else if (!dialog.open) dialog.showModal();
    return true;
  }
  $('schema-tab').onclick = () => { if (leave()) $('viewport').focus({preventScroll: true}); };
  // Give an experiment with unsaved notes the same protection on all navigation paths.
  const destinations = new Set(['design-document-create', 'board-open', 'connections', 'learning', 'community', 'publish-project', 'propose-project', 'run-pipeline', 'debug-pipeline', 'new-diagram', 'import', 'experiment-wizard-open', 'project-catalog', 'welcome-experiment']);
  document.addEventListener('click', event => {
    if (destinations.has(event.target.closest('button')?.id) && !leave()) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && active && !event.target.closest('#codex-chat') && !document.querySelector('dialog:modal')) {
      event.preventDefault(); event.stopImmediatePropagation();
      if (leave()) $('schema-tab').focus();
    }
  }, true);
  const key = 'opensource.architect.sidebar-collapsed';
  function collapse(value) {
    document.body.classList.toggle('sidebar-collapsed', value);
    if (window.DeviceUI?.mobile) {
      $('sidebar-toggle').textContent = '×';
      $('sidebar-toggle').setAttribute('aria-label', 'Закрыть меню');
      $('sidebar-toggle').title = 'Закрыть меню';
      return;
    }
    $('sidebar-toggle').setAttribute('aria-expanded', String(!value));
    $('sidebar-toggle').textContent = value ? '»' : '«';
    $('sidebar-toggle').title = value ? 'Развернуть меню' : 'Свернуть меню';
    $('sidebar-toggle').setAttribute('aria-label', $('sidebar-toggle').title);
  }
  try { const saved = localStorage.getItem(key); collapse(saved === null ? matchMedia('(max-width:760px)').matches : saved === 'true'); } catch (_) {}
  $('sidebar-toggle').onclick = () => {
    const value = !document.body.classList.contains('sidebar-collapsed'); collapse(value);
    try { localStorage.setItem(key, String(value)); } catch (_) {}
  };
  matchMedia('(max-width:760px)').addEventListener('change', event => {
    if (event.matches) collapse(true);
    else { try { collapse(localStorage.getItem(key) === 'true'); } catch (_) {} }
  });
  const menus = [$('project-menu')];
  const title = $('diagram-name');
  const measure = document.createElement('canvas').getContext('2d');
  function resizeTitle() {
    const style = getComputedStyle(title);
    measure.font = style.font;
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    title.style.width = Math.ceil(measure.measureText(title.value || ' ').width + padding + 4) + 'px';
  }
  title.addEventListener('input', resizeTitle);
  new ResizeObserver(resizeTitle).observe(title.parentElement);
  document.fonts.ready.then(resizeTitle);
  resizeTitle();
  document.addEventListener('click', event => {
    for (const menu of menus) if (!menu.contains(event.target) || event.target.closest('button')) menu.open = false;
  });
  for (const menu of menus) menu.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.stopPropagation(); menu.open = false; menu.querySelector('summary').focus(); }
  });
  $('new-diagram').addEventListener('click', () => { if (matchMedia('(max-width:760px)').matches) collapse(true); });
  for (const id of ['connections', 'learning', 'community', 'codex-chat-open', 'board-open', 'design-document-create']) {
    $(id).addEventListener('click', () => { $(id).classList.add('nav-active'); if (matchMedia('(max-width:760px)').matches) collapse(true); });
  }
  for (const dialog of document.querySelectorAll('dialog')) dialog.addEventListener('close', () => {
    if (!dialog.open) document.querySelectorAll('.nav-active').forEach(button => button.classList.remove('nav-active'));
  });
  return {show, leave, resizeTitle};
})();


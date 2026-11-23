'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const last = 'architect.problem-space.last';
  const url = new URL(location.href);
  const project = url.searchParams.get('project');
  if (project) $('back-schema').href += '?project=' + encodeURIComponent(project);
  let id, revision, dirty = false, saving = false, conflict = false;
  const key = () => 'architect.problem-space.draft.' + id;
  const status = message => { $('status').textContent = message; };
  async function api(action, body) {
    const response = await fetch('/api/problem-spaces/' + action, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Architect-Request': '1'},
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw Object.assign(Error(data.error || 'Ошибка запроса.'), {status: response.status});
    return data;
  }
  const tree = window.problemSpace(changed, (request, path) =>
    api('suggest-questions', {...value(), request, path}));
  function value() {
    return {title: $('title').value, problem: $('formulation').value, problem_tree: tree.value()};
  }
  function changed() {
    dirty = true;
    try { localStorage.setItem(key(), JSON.stringify({...value(), revision})); }
    catch { status('Черновик не помещается в браузере. Нажмите «Сохранить».'); return; }
    status(conflict ? 'Есть другая версия дерева' : 'Есть изменения');
  }
  function openTree(record, draft) {
    id = record.id;
    revision = record.revision;
    conflict = !!draft && draft.revision !== revision;
    const data = draft || record;
    $('title').value = data.title;
    $('formulation').value = data.problem;
    tree.load(data.problem_tree);
    dirty = !!draft;
    $('save').textContent = conflict ? 'Сохранить копию' : 'Сохранить';
    status(conflict ? 'Дерево изменилось в другой вкладке' : dirty ? 'Восстановлен черновик' : revision ? 'Сохранено' : '');
    url.searchParams.delete('new');
    url.searchParams.set('id', id);
    history.replaceState(null, '', url);
    localStorage.setItem(last, id);
  }
  const fresh = () => ({id: crypto.randomUUID(), title: 'Новое дерево', problem: '', problem_tree: [], revision: 0});
  async function restore(treeId) {
    if (!treeId) { openTree(fresh()); return; }
    let draft = JSON.parse(localStorage.getItem('architect.problem-space.draft.' + treeId) || 'null');
    let record;
    try { record = await api('get', {id: treeId}); }
    catch (error) {
      if (error.status !== 404) throw error;
      record = {...fresh(), id: treeId};
    }
    if (url.searchParams.has('legacy') && !draft) {
      const old = JSON.parse(localStorage.getItem('architect.design-document.local.' + treeId) || 'null');
      if (old?.problem_tree) draft = {title: old.title, problem: old.sections?.problem || '', problem_tree: old.problem_tree, revision: record.revision};
    }
    url.searchParams.delete('legacy');
    openTree(record, draft);
    if (draft) changed();
  }
  async function save() {
    if (saving || !id) return;
    saving = true;
    $('solutions').disabled = $('save').disabled = $('library').disabled = true;
    const previousKey = key();
    const dest = conflict ? crypto.randomUUID() : id;
    const sent = JSON.stringify(value());
    try {
      const result = await api('save', {...JSON.parse(sent), id: dest, revision: conflict ? 0 : revision});
      openTreeAfterSave(dest, result.revision);
      localStorage.removeItem(previousKey);
      if (sent !== JSON.stringify(value())) changed();
      return !dirty;
    } catch (error) {
      if (error.status === 409) { conflict = true; $('save').textContent = 'Сохранить копию'; }
      status(error.message);
    } finally { saving = false; $('solutions').disabled = $('save').disabled = $('library').disabled = false; }
  }
  function openTreeAfterSave(dest, version) {
    id = dest; revision = version; dirty = conflict = false;
    url.searchParams.set('id', id); history.replaceState(null, '', url);
    localStorage.setItem(last, id);
    $('save').textContent = 'Сохранить';
    status('Сохранено');
  }
  $('save').onclick = save;
  $('solutions').onclick = async () => {
    if (!id || saving) return;
    if (conflict) { status('Сначала сохраните свою версию дерева как копию.'); return; }
    if ((dirty || !revision) && !await save()) return;
    const next = new URL('/solution-space.html', location.origin);
    next.searchParams.set('id', id);
    if (project) next.searchParams.set('project', project);
    location.href = next;
  };
  $('title').oninput = $('formulation').oninput = () => { tree.updateOrigin(); changed(); };
  $('library').onclick = async () => {
    try {
      const result = await api('list', {});
      $('entries').replaceChildren();
      const ids = new Set(result.trees.map(row => row.id));
      for (const storageKey of Object.keys(localStorage)) {
        const prefix = 'architect.problem-space.draft.';
        if (!storageKey.startsWith(prefix)) continue;
        const draftId = storageKey.slice(prefix.length);
        if (!ids.has(draftId)) {
          const draft = JSON.parse(localStorage.getItem(storageKey));
          result.trees.push({id: draftId, title: (draft.title || 'Новое дерево') + ' · черновик'});
        }
      }
      for (const row of result.trees) {
        const button = document.createElement('button');
        button.textContent = row.title;
        button.onclick = async () => {
          try { await restore(row.id); $('trees').close(); }
          catch (error) { $('trees').close(); status(error.message); }
        };
        $('entries').append(button);
      }
      if (!result.trees.length) $('entries').textContent = 'Сохранённых деревьев пока нет.';
      $('trees').showModal();
    } catch (error) { status(error.message); }
  };
  $('new').onclick = () => { openTree(fresh()); $('trees').close(); };
  $('export').onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify({format:'architect.problem-space',version:1,...value()},null,2)],{type:'application/json'}));
    a.download = ($('title').value || 'Дерево') + '.json';
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $('import').onclick = () => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.json';
    input.onchange = async () => {
      $('trees').close();
      try {
        const data = JSON.parse(await input.files[0].text());
        if (data.version !== 1 || !['architect.problem-space','architect.design-document'].includes(data.format)) throw Error('Выберите JSON дерева.');
        const record = {...fresh(), title: data.title, problem: data.problem ?? data.sections?.problem ?? '', problem_tree: data.problem_tree};
        const result = await api('save', record);
        openTree({...record, revision: result.revision});
      } catch (error) { status(error.message); }
    };
    input.click();
  };
  document.querySelectorAll('[data-close]').forEach(button => { button.onclick = () => button.closest('dialog').close(); });
  window.addEventListener('beforeunload', event => { if (dirty || saving) event.preventDefault(); });
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); }
  });
  document.body.inert = true;
  const oldNew = url.searchParams.get('new');
  const initial = url.searchParams.get('id') || (oldNew ? oldNew === '1' ? null : oldNew : localStorage.getItem(last));
  restore(initial).catch(error => { status(error.message); }).finally(() => { document.body.inert = false; });
})();

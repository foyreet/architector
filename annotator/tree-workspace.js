'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const metrics = document.body.classList.contains('metrics-page');
  const space = metrics ? 'architect.metric-tree' : 'architect.problem-space';
  const endpoint = metrics ? '/api/metric-trees/' : '/api/problem-spaces/';
  const goalKey = metrics ? 'goal' : 'problem', nodesKey = metrics ? 'metrics' : 'problem_tree';
  const last = space + '.last';
  const url = new URL(location.href);
  const project = url.searchParams.get('project');
  if (project) $('back-schema').href += '?project=' + encodeURIComponent(project);
  let id, revision, dirty = false, saving = false, conflict = false;
  const key = () => space + '.draft.' + id;
  const status = message => { $('status').textContent = message; };
  async function api(action, body) {
    const response = await fetch(endpoint + action, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Architect-Request': '1'},
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw Object.assign(Error(data.error || 'Ошибка запроса.'), {status: response.status});
    return data;
  }
  window.setupMethodEditor({
    first:'tree',
    load:async () => ({tree:await api('method', {})}),
    save:changes => api('save-method', changes.tree)
  });
  const tree = window.problemSpace(changed, (request, path) =>
    api(metrics ? 'suggest' : 'suggest-questions', {...value(), request, path}), metrics);
  function value() {
    return {title: $('title').value, [goalKey]: $('formulation').value, [nodesKey]: tree.value()};
  }
  function changed() {
    dirty = true;
    try { localStorage.setItem(key(), JSON.stringify({...value(), revision})); }
    catch { status('Черновик не помещается в браузере. Нажмите «Сохранить».'); return; }
    status(conflict ? 'Есть другая версия дерева' : 'Есть изменения');
  }
  function syncNavigation() {
    window.designFlow.treeOpened(metrics ? 'metric' : 'tree', id, url.searchParams.has('attach'));
    const context = window.designFlow.url(metrics ? 'metrics' : 'problems');
    for (const key of ['tree', 'metric', 'doc', 'draft']) {
      if (context.searchParams.has(key)) url.searchParams.set(key, context.searchParams.get(key));
      else url.searchParams.delete(key);
    }
    history.replaceState(null, '', url);
    localStorage.setItem(last, id);
  }
  function openTree(record, draft) {
    id = record.id;
    revision = record.revision;
    conflict = !!draft && draft.revision !== revision;
    const data = draft || record;
    $('title').value = data.title;
    $('formulation').value = data[goalKey];
    tree.load(data[nodesKey]);
    dirty = !!draft;
    $('save').textContent = conflict ? 'Сохранить копию' : 'Сохранить';
    status(conflict ? 'Дерево изменилось в другой вкладке' : dirty ? 'Восстановлен черновик' : revision ? 'Сохранено' : '');
    if (!dirty && url.searchParams.has('attach')) status('При сохранении дерево будет связано с этим документом.');
    url.searchParams.delete('new');
    url.searchParams.set('id', id);
    syncNavigation();
  }
  const fresh = () => ({id: crypto.randomUUID(), title: 'Новое дерево', [goalKey]: '', [nodesKey]: [], revision: 0});
  async function restore(treeId) {
    if (!treeId) { openTree(fresh()); return; }
    let draft = JSON.parse(localStorage.getItem(space + '.draft.' + treeId) || 'null');
    let record;
    try { record = await api('get', {id: treeId}); }
    catch (error) {
      if (error.status !== 404) throw error;
      record = {...fresh(), id: treeId};
    }
    if (!metrics && url.searchParams.has('legacy') && !draft) {
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
    if ($('solutions')) $('solutions').disabled = true;
    $('save').disabled = $('library').disabled = true;
    const previousKey = key();
    const dest = conflict ? crypto.randomUUID() : id;
    const sent = JSON.stringify(value());
    const attach = url.searchParams.has('attach') ? {doc:url.searchParams.get('doc')} : {};
    try {
      const result = attach.doc && !dirty && revision
        ? await api('attach', {id:dest, ...attach})
        : await api('save', {...JSON.parse(sent), id:dest, revision:conflict ? 0 : revision, ...attach});
      url.searchParams.delete('attach');
      openTreeAfterSave(dest, result.revision);
      localStorage.removeItem(previousKey);
      if (sent !== JSON.stringify(value())) changed();
      return !dirty;
    } catch (error) {
      if (error.status === 409) { conflict = true; $('save').textContent = 'Сохранить копию'; }
      status(error.message);
    } finally { saving = false; if ($('solutions')) $('solutions').disabled = false; $('save').disabled = $('library').disabled = false; }
  }
  function openTreeAfterSave(dest, version) {
    id = dest; revision = version; dirty = conflict = false;
    url.searchParams.set('id', id);
    syncNavigation();
    $('save').textContent = 'Сохранить';
    status('Сохранено');
  }
  $('save').onclick = save;
  if ($('solutions')) $('solutions').onclick = async () => {
    if (!id || saving) return;
    if (conflict) { status('Сначала сохраните свою версию дерева как копию.'); return; }
    if ((dirty || !revision || url.searchParams.has('attach')) && !await save()) return;
    location.href = window.designFlow.url('solutions');
  };
  $('design-flow').addEventListener('click', async event => {
    const link = event.target.closest('a[data-step]');
    if (!link || !(url.searchParams.has('draft') || url.searchParams.has('attach')) || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (saving) return;
    if (conflict) { status('Сначала сохраните свою версию дерева как копию.'); return; }
    if ((dirty || (revision && url.searchParams.has('attach'))) && !await save()) return;
    const target = new URL(link.href);
    // A skipped, untouched stage has no saved tree to attach.
    if (!revision) target.searchParams.delete(metrics ? 'metric' : 'tree');
    location.assign(target);
  });
  $('title').oninput = $('formulation').oninput = () => { tree.updateOrigin(); changed(); };
  $('library').onclick = async () => {
    try {
      const result = await api('list', {});
      $('entries').replaceChildren();
      const ids = new Set(result.trees.map(row => row.id));
      for (const storageKey of Object.keys(localStorage)) {
        const prefix = space + '.draft.';
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
    a.href = URL.createObjectURL(new Blob([JSON.stringify({format:space,version:1,...value()},null,2)],{type:'application/json'}));
    a.download = ($('title').value || 'Дерево') + '.json';
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $('import').onclick = () => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.json';
    input.onchange = async () => {
      $('trees').close();
      try {
        const data = JSON.parse(await input.files[0].text());
        if (data.version !== 1 || !(metrics ? [space] : [space,'architect.design-document']).includes(data.format)) throw Error('Выберите JSON дерева.');
        const record = {...fresh(), title: data.title, [goalKey]: data[goalKey] ?? data.sections?.problem ?? '', [nodesKey]: data[nodesKey]};
        const result = await api('save', record);
        openTree({...record, revision: result.revision});
      } catch (error) { status(error.message); }
    };
    input.click();
  };
  document.querySelectorAll('[data-close]').forEach(button => { button.onclick = () => button.closest('dialog').close(); });
  window.addEventListener('beforeunload', event => { if (dirty || saving) event.preventDefault(); });
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      save();
    }
  });
  document.body.inert = true;
  const oldNew = url.searchParams.get('new');
  const initial = url.searchParams.get('id') || (oldNew ? oldNew === '1' ? null : oldNew : localStorage.getItem(last));
  restore(initial).catch(error => { status(error.message); }).finally(() => { document.body.inert = false; });
})();

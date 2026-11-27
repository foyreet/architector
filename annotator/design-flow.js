'use strict';
// Keep the current task in each navigation URL so tabs can follow different tasks.
window.designFlow = (() => {
  const nav = document.getElementById('design-flow');
  const params = new URLSearchParams(location.search);
  const project = params.get('project');
  const state = {tree: params.get('tree'), metric: params.get('metric'),
    doc: params.get('doc'), draft: params.has('draft')};
  const paths = {problems:'/problem-space.html', solutions:'/solution-space.html',
    metrics:'/metric-tree.html', document:'/design-docs.html'};
  if (location.pathname === paths.solutions && params.has('id')) {
    if (state.tree && state.tree !== params.get('id')) {
      state.doc = state.metric = null;
      state.draft = false;
    }
    state.tree = params.get('id');
  }
  function url(step, task = state) {
    const next = new URL(paths[step], location.origin);
    for (const [key, value] of Object.entries({project, tree:task.tree, metric:task.metric, doc:task.doc})) {
      if (value) next.searchParams.set(key, value);
    }
    if (task.doc && task.draft) next.searchParams.set('draft', '1');
    const id = step === 'document' ? task.doc : step === 'metrics' ? task.metric : task.tree;
    if (id) next.searchParams.set(step === 'document' && task.draft ? 'new' : 'id', id);
    else if (step === 'document' && (task.tree || task.metric)) next.searchParams.set('new', '1');
    else if ((step === 'metrics' || step === 'problems') && (task.tree || task.metric || task.doc)) next.searchParams.set('new', '1');
    if (task.doc && !task.draft && !id && step !== 'document') next.searchParams.set('attach', '1');
    return next;
  }
  async function taskTitle(task = state) {
    if (!task.doc) return '';
    const response = await fetch('/api/design-documents/task-title', {method:'POST',
      headers:{'Content-Type':'application/json', 'X-Architect-Request':'1'},
      body:JSON.stringify({id:task.doc, tree_id:task.tree, metric_tree_id:task.metric})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Не удалось загрузить название задачи.');
    return result.title || '';
  }
  function refresh() {
    for (const a of nav.querySelectorAll('a[data-step]')) a.href = url(a.dataset.step);
  }
  const historyPrefix = 'architect.task-visit.';
  let activeStep;
  function visitKey(task, step) {
    return task.doc || (step === 'metrics' ? task.metric && 'metric.' + task.metric : task.tree && 'tree.' + task.tree);
  }
  function remember(step) {
    activeStep = step;
    const key = visitKey(state, step);
    if (key && step) {
      try { localStorage.setItem(historyPrefix + key, JSON.stringify({step, time:Date.now()})); } catch {}
    }
  }
  function lastVisit(task) {
    const keys = [task.doc];
    if (task.draft) {
      if (task.tree) keys.push('tree.' + task.tree);
      if (task.metric) keys.push('metric.' + task.metric);
    }
    let latest = null;
    for (const key of keys) {
      try {
        const entry = JSON.parse(localStorage.getItem(historyPrefix + key));
        if (entry && Object.hasOwn(paths, entry.step) && Number.isFinite(entry.time) && (!latest || entry.time > latest.time)) latest = entry;
      } catch {}
    }
    return latest;
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && activeStep) remember(activeStep);
  });
  window.addEventListener('pageshow', event => { if (event.persisted && activeStep) remember(activeStep); });
  function treeOpened(key, id, choosingForDocument = false) {
    // Opening another tree from the library starts a different context.
    if (!choosingForDocument && state[key] && state[key] !== id) {
      state.doc = null;
      state.draft = false;
      state[key === 'tree' ? 'metric' : 'tree'] = null;
    }
    state[key] = id;
    remember(key === 'metric' ? 'metrics' : 'problems');
    refresh();
  }
  function documentOpened(id, draft, links) {
    Object.assign(state, {doc:id, draft, tree:links.tree_id, metric:links.metric_tree_id});
    remember(id ? 'document' : null);
    refresh();
  }
  const settings = document.getElementById('tree-ai-settings');
  if (settings && project) {
    const target = new URL(settings.href);
    target.searchParams.set('project', project);
    settings.href = target;
  }
  refresh();
  return {url, taskTitle, treeOpened, documentOpened, lastVisit, remember, historyPrefix};
})();

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
  function url(step) {
    const next = new URL(paths[step], location.origin);
    for (const [key, value] of Object.entries({project, tree:state.tree, metric:state.metric, doc:state.doc})) {
      if (value) next.searchParams.set(key, value);
    }
    if (state.doc && state.draft) next.searchParams.set('draft', '1');
    const id = step === 'document' ? state.doc : step === 'metrics' ? state.metric : state.tree;
    if (id) next.searchParams.set(step === 'document' && state.draft ? 'new' : 'id', id);
    else if (step === 'document' && (state.tree || state.metric)) next.searchParams.set('new', '1');
    else if ((step === 'metrics' || step === 'problems') && (state.tree || state.metric || state.doc)) next.searchParams.set('new', '1');
    return next;
  }
  function refresh() {
    for (const a of nav.querySelectorAll('a[data-step]')) a.href = url(a.dataset.step);
  }
  function treeOpened(key, id) {
    // Opening another tree from the library starts a different context.
    if (state[key] && state[key] !== id) {
      state.doc = null;
      state.draft = false;
      state[key === 'tree' ? 'metric' : 'tree'] = null;
    }
    state[key] = id;
    refresh();
  }
  function documentOpened(id, draft, links) {
    Object.assign(state, {doc:id, draft, tree:links.tree_id, metric:links.metric_tree_id});
    refresh();
  }
  const settings = document.getElementById('tree-ai-settings');
  if (settings && project) {
    const target = new URL(settings.href);
    target.searchParams.set('project', project);
    settings.href = target;
  }
  refresh();
  return {url, treeOpened, documentOpened};
})();

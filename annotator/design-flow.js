'use strict';
// Step links between the problem tree, solution cases, metric tree and design document.
(() => {
  const nav = document.getElementById('design-flow');
  if (!nav) return;
  const params = new URLSearchParams(location.search);
  const project = params.get('project');
  // Solution pages are opened for one problem tree; otherwise follow the last opened tree.
  let tree = location.pathname === '/solution-space.html' ? params.get('id') : null;
  if (!tree) { try { tree = localStorage.getItem('architect.problem-space.last'); } catch {} }
  for (const link of nav.querySelectorAll('a[href]')) {
    const url = new URL(link.getAttribute('href'), location.origin);
    if (project) url.searchParams.set('project', project);
    if (tree && ['problems', 'solutions'].includes(link.dataset.step)) url.searchParams.set('id', tree);
    link.href = url;
  }
})();

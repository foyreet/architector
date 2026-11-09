'use strict';
window.MobileWorkspace = function (editor) {
  if (!window.DeviceUI?.mobile) return null;
  const $ = id => document.getElementById(id);
  const viewport = $('viewport'), inspector = document.querySelector('.inspector');
  const properties = $('mobile-properties'), navigation = $('mobile-nav-dialog');
  const form = $('inspector-form');
  $('run-pipeline').textContent = '▶ Запустить';
  $('run-pipeline').setAttribute('aria-label', 'Запустить пайплайн');
  let moving = false, panelNode = null, restoring = false, fieldsDirty = false;
  let fieldKey = null, fieldSnapshot = '';
  const activeTouches = new Map();
  let gesture = null;

  function sizeViewport() {
    const view = window.visualViewport;
    if (!view || view.scale === 1) document.documentElement.style.setProperty('--app-height', `${view?.height || innerHeight}px`);
  }
  sizeViewport(); window.visualViewport?.addEventListener('resize', sizeViewport);
  window.addEventListener('resize', sizeViewport);
  navigation.append($('app-sidebar'));
  $('mobile-inspector-host').append(inspector);
  $('mobile-menu').onclick = () => navigation.showModal();
  $('sidebar-toggle').onclick = () => navigation.close();
  $('sidebar-toggle').textContent = '×';
  $('sidebar-toggle').setAttribute('aria-label', 'Закрыть меню');
  navigation.addEventListener('click', event => {
    if (event.target.closest('button') && event.target.closest('button').id !== 'sidebar-toggle') navigation.close();
  }, true);
  // Native dialogs close on Escape/Android back where supported, without navigating away.
  $('mobile-properties-close').onclick = () => properties.close();
  properties.addEventListener('close', () => { cacheFields(); panelNode = null; $('mobile-edit').focus({preventScroll: true}); });
  $('mobile-apply').onclick = () => {
    if (!editor.save()) return;
    clearDraft(); properties.close();
  };

  function inputs() {
    return [...form.querySelectorAll('input, select, textarea')].filter(input =>
      !['password', 'file', 'hidden'].includes(input.type) && !/token|secret|key/i.test(input.id));
  }
  function values() {
    return inputs().map(input => ({id: input.id, name: input.name, parameter: input.dataset.parameter || '',
      value: input.value, checked: input.type === 'checkbox' ? input.checked : undefined}));
  }
  function cacheFields() {
    if (!panelNode || restoring || !fieldKey) return;
    const fields = values();
    if (JSON.stringify(fields) === fieldSnapshot && !fieldsDirty) return;
    try {
      localStorage.setItem(fieldKey, JSON.stringify({node: panelNode, fields}));
      fieldsDirty = true;
      $('mobile-draft-status').textContent = 'Черновик настроек сохранён на этом устройстве.';
    } catch { $('mobile-draft-status').textContent = 'Не удалось сохранить черновик. Нажмите «Применить и закрыть».'; }
  }
  function clearDraft() {
    if (fieldKey) { try { localStorage.removeItem(fieldKey); } catch {} }
    fieldsDirty = false; fieldSnapshot = JSON.stringify(values());
    $('mobile-draft-status').textContent = '';
  }
  form.addEventListener('input', cacheFields);
  form.addEventListener('change', cacheFields);
  function openProperties() {
    const node = editor.selected(); if (!node) return;
    panelNode = node.id;
    fieldKey = editor.storageKey() + '.fields.' + node.id;
    fieldSnapshot = JSON.stringify(values()); fieldsDirty = false;
    $('mobile-draft-status').textContent = '';
    try {
      const draft = JSON.parse(localStorage.getItem(fieldKey) || 'null');
      if (draft?.node === node.id && Array.isArray(draft.fields)) {
        restoring = true;
        const behavior = draft.fields.find(field => field.id === 'node-behavior');
        if (behavior) { $('node-behavior').value = behavior.value; editor.behavior(); }
        const current = inputs();
        draft.fields.forEach((field, index) => {
          const target = field.id ? current.find(input => input.id === field.id) : current[index];
          if (!target || target.name !== field.name || (target.dataset.parameter || '') !== field.parameter) return;
          target.value = field.value; if (target.type === 'checkbox') target.checked = !!field.checked;
        });
        fieldsDirty = true;
        $('mobile-draft-status').textContent = 'Восстановлен черновик настроек. Примените изменения.';
      }
    } catch {} finally { restoring = false; }
    properties.showModal(); $('mobile-properties-close').focus({preventScroll: true});
  }
  $('mobile-edit').onclick = openProperties;
  $('mobile-deselect').onclick = () => { moving = false; editor.select(null); };
  $('mobile-move').onclick = () => { moving = !moving; selection(); };
  function selection() {
    const node = editor.selected();
    $('mobile-selection').hidden = !node;
    $('mobile-selected-name').textContent = node?.name || '';
    if (!node) moving = false;
    $('mobile-move').setAttribute('aria-pressed', String(moving));
    $('mobile-move').textContent = moving ? 'Двигаем ✓' : 'Двигать';
    viewport.classList.toggle('mobile-moving', moving);
    $('mobile-connect').disabled = !node || !editor.outputs(node).length;
  }

  let candidates = [];
  function chooseInputs() {
    candidates = editor.connections($('mobile-output').value);
    $('mobile-input').replaceChildren(...candidates.map((item, i) => new Option(item.label, String(i))));
    $('mobile-connection-submit').disabled = !candidates.length;
    $('mobile-connection-status').textContent = candidates.length ? 'Показаны только совместимые свободные входы.' : 'Совместимых входов нет. Добавьте подходящий блок или выберите другой выход.';
  }
  $('mobile-connect').onclick = () => {
    const node = editor.selected(); if (!node) return;
    $('mobile-output').replaceChildren(...editor.outputs(node).map(port => new Option(port.label, port.id)));
    chooseInputs(); $('mobile-connection').showModal();
  };
  $('mobile-output').onchange = chooseInputs;
  $('mobile-connection-close').onclick = () => $('mobile-connection').close();
  $('mobile-connection-form').onsubmit = event => {
    event.preventDefault(); const candidate = candidates[Number($('mobile-input').value)];
    if (!candidate) return;
    try { editor.connect(candidate.edge); $('mobile-connection').close(); }
    catch (error) { $('mobile-connection-status').textContent = error.message; }
  };

  const midpoint = points => ({x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2});
  const distance = points => Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  function cancelMove() { if (gesture?.kind === 'move') editor.cancelMove(gesture.before); }
  function capture(event) { try { viewport.setPointerCapture(event.pointerId); } catch {} }
  viewport.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch') return;
    if (!activeTouches.size && event.target.closest('button:not(.port), summary, input, select, textarea, a')) return;
    event.preventDefault(); event.stopImmediatePropagation();
    activeTouches.set(event.pointerId, {x: event.clientX, y: event.clientY}); capture(event);
    if (activeTouches.size >= 2) {
      cancelMove(); const points = [...activeTouches.values()].slice(0, 2);
      gesture = {kind: 'pinch', camera: {...editor.camera()}, center: midpoint(points), distance: Math.max(distance(points), 1)};
    } else {
      const node = event.target.closest('.node')?.dataset.id;
      gesture = {kind: moving && node && node === editor.selected()?.id ? 'move' : 'pan',
        start: {x: event.clientX, y: event.clientY}, camera: {...editor.camera()}, node, moved: false};
      if (gesture.kind === 'move') gesture.before = editor.snapshot();
    }
  }, true);
  window.addEventListener('pointermove', event => {
    if (!activeTouches.has(event.pointerId)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    activeTouches.set(event.pointerId, {x: event.clientX, y: event.clientY});
    if (!gesture) return;
    if (gesture.kind === 'pinch') {
      if (activeTouches.size < 2 || !gesture.camera) return;
      const points = [...activeTouches.values()].slice(0, 2), center = midpoint(points), rect = viewport.getBoundingClientRect();
      const scale = Math.max(.001, Math.min(2, gesture.camera.scale * distance(points) / gesture.distance));
      editor.setCamera({scale, x: center.x - rect.left - (gesture.center.x - rect.left - gesture.camera.x) * scale / gesture.camera.scale,
        y: center.y - rect.top - (gesture.center.y - rect.top - gesture.camera.y) * scale / gesture.camera.scale});
    } else {
      const dx = event.clientX - gesture.start.x, dy = event.clientY - gesture.start.y;
      gesture.moved ||= Math.hypot(dx, dy) > 6;
      if (!gesture.moved) return;
      if (gesture.kind === 'move') editor.move(gesture.before, gesture.node, dx / gesture.camera.scale, dy / gesture.camera.scale);
      else editor.setCamera({...gesture.camera, x: gesture.camera.x + dx, y: gesture.camera.y + dy});
    }
  }, {capture: true, passive: false});
  function finish(event) {
    if (!activeTouches.has(event.pointerId)) return;
    event.stopImmediatePropagation();
    const cancelled = event.type !== 'pointerup';
    if (gesture?.kind === 'move') {
      if (cancelled) cancelMove(); else if (gesture.moved) editor.finishMove(gesture.before);
    }
    if (!cancelled && gesture && gesture.kind !== 'pinch' && !gesture.moved) editor.select(gesture.node || null);
    activeTouches.delete(event.pointerId);
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    // After a pinch, remaining fingers are ignored until all are lifted.
    gesture = activeTouches.size ? {kind: 'pinch'} : null;
  }
  window.addEventListener('pointerup', finish, true);
  window.addEventListener('pointercancel', finish, true);
  viewport.addEventListener('click', event => {
    if (event.pointerType === 'touch' && event.target.closest('.node')) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  function background() {
    cacheFields(); cancelMove(); activeTouches.clear(); gesture = null;
    editor.cache();
  }
  window.addEventListener('pagehide', background);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') background(); });
  selection();
  return {selection, applied: clearDraft, isEditing: () => properties.open, openProperties};
};


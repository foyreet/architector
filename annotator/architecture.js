'use strict';

(async () => {
  const saveStatus = document.getElementById('save-status');
  const updateSaveStatus = () => {
    saveStatus.classList.add('sr-only');
    document.getElementById('save').title = 'Сохранить проект';
  };
  new MutationObserver(updateSaveStatus).observe(saveStatus, {childList: true, characterData: true, subtree: true});
  updateSaveStatus();
  let Contracts;
  try {
    if (typeof window.BlockContracts !== 'function') {
      throw new Error('Не загрузился модуль контрактов. Перезапустите сервер: остановите прежний процесс и запустите python3 serve.py из папки opensource. Затем обновите страницу.');
    }
    Contracts = await window.BlockContracts();
  } catch (error) {
    document.getElementById('save-status').textContent = 'Редактор не запущен';
    document.getElementById('toast').hidden = false;
    document.getElementById('toast').textContent = error.message;
    return;
  }
  let account;
  try { account = await api('/api/community/session', {}); }
  catch (error) { document.getElementById('save-status').textContent = error.message; return; }
  const STORAGE_KEY = 'opensource.architect.clean.v1' + (account.user && !account.user.primary ? '.user.' + account.user.id : account.enabled && !account.user ? '.guest' : '');
  const $ = id => document.getElementById(id);
  const blank = (types = [], definitions = []) => ({format: 'architect', version: definitions.length ? 4 : 3, name: 'Новая схема', types, definitions, nodes: [], edges: []});
  const clone = value => JSON.parse(JSON.stringify(value));
  const uid = () => crypto.randomUUID();
  let state = blank();
  let personalBlocks = [], personalLoaded = false, personalGeneration = 0;
  let selected = null;
  let multiSelected = new Set();
  let activeProject = null, projectSaveTimer, projectSavePromise = null, savingCurrentProject = false, creatingDiagram = false;
  let runView = null, runViewRequest = 0;
  const runViewControls = new Map();
  let community;
  let kaggleConnectionToken = '';
  const ACTIVE_PROJECT_KEY = STORAGE_KEY + '.active-project';
  let connection = null;
  const mobileUI = !!window.DeviceUI?.mobile;
  let mobile = null, previousMobileNodeCount = 0;
  const initialScale = () => mobileUI ? .85 : 1;
  let camera = {x: 0, y: 0, scale: initialScale()};
  let canvasSize, pendingCanvasFit = false, pendingSelectionReveal = false;
  let past = [], future = [];
  let pointer = null;
  let unsaved = false;
  let toastTimer;
  // Credentials and responses are deliberately outside serializable graph state/history.
  let openrouterKey = '';
  let serverKey = false;
  const runs = new Map();
  const datasets = new Map();
  const hubModels = new Map();
  let hubToken = '';
  let pipelineRun = null, activePipeline = null, pipelineTimer, pipelineStarting = false;
  let pendingPipeline = null, pipelineStep = null, stepRequest = 0, historyRequest = 0, launchReturnFocus = null;
  let pipelineList = [];
  let pipelineHistoryLoading = false;
  const pipelineLabels = {waiting: 'Ожидает', pending: 'Ожидает шага', paused: 'Ожидает продолжения', running: 'Работает', ready: 'Готово', error: 'Ошибка', skipped: 'Пропущен', cancelled: 'Остановлен'};
  const executionDefaults = () => Contracts.defaults();

  function parseExecution(value) {
    if (value === undefined) return executionDefaults();
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Некорректные настройки блока.');
    const result = executionDefaults();
    for (const field of Object.keys(result)) if (value[field] !== undefined) result[field] = clone(value[field]);
    // Validate the active contract and discard undeclared input literals.
    const block = Contracts.fromExecution(result);
    result.input_values = Contracts.toExecution(block).input_values;
    return result;
  }

  function serializable() {
    return {...state, version: state.definitions?.length ? 4 : 3,
      types: state.types.map(({behavior, ...type}) => ({...type, block: {kind: behavior, version: Contracts.get(behavior).version}})),
      nodes: state.nodes.map(({execution, ...node}) => ({...node, block: Contracts.fromExecution(execution)}))};
  }

  function toast(message) {
    clearTimeout(toastTimer);
    $('toast').textContent = message;
    $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4200);
  }

  function validate(raw) {
    const fail = () => { throw new Error('Некорректный файл схемы. Ожидается JSON, экспортированный из этого редактора.'); };
    const text = (value, limit, required = false) => {
      if (typeof value !== 'string' || value.length > limit || (required && !value.trim())) fail();
      return value;
    };
    const object = value => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) fail();
      return value;
    };
    object(raw);
    if (raw.format !== 'architect' || ![1, 2, 3, 4].includes(raw.version)) fail();
    for (const [key, max] of [['types', 200], ['nodes', 500], ['edges', 1000]]) {
      if (!Array.isArray(raw[key]) || raw[key].length > max) fail();
    }
    const ids = new Set();
    const identifier = value => {
      if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(value) || ids.has(value)) fail();
      ids.add(value);
      return value;
    };
    const types = raw.types.map(item => {
      object(item);
      if (typeof item.color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(item.color)) fail();
      const behavior = raw.version >= 3 ? Contracts.normalize(item.block).kind :
        ['note', 'openrouter', 'kaggle', 'huggingface'].includes(item.behavior) ? item.behavior : 'note';
      return {id: identifier(item.id), name: text(item.name, 100, true), description: text(item.description, 2000), color: item.color, behavior};
    });
    const typeIds = new Set(types.map(type => type.id));
    const nodes = raw.nodes.map(item => {
      object(item);
      if (!typeIds.has(item.typeId) || !Number.isFinite(item.x) || !Number.isFinite(item.y) || Math.abs(item.x) > 100000 || Math.abs(item.y) > 100000) fail();
      const size = {};
      for (const [key, min, max] of [['width', 180, 1600], ['height', 110, 4096]]) if (key in item) {
        if (!Number.isFinite(item[key]) || item[key] < min || item[key] > max) fail();
        size[key] = item[key];
      }
      return {id: identifier(item.id), typeId: item.typeId, name: text(item.name, 100, true), description: text(item.description, 2000), x: item.x, y: item.y, ...size, execution: raw.version >= 3 ? Contracts.toExecution(item.block) : parseExecution(item.execution)};
    });
    const edges = [];
    for (const item of raw.edges) {
      object(item);
      const edge = {id: identifier(item.id), from: item.from, to: item.to,
        fromPort: raw.version >= 3 ? item.fromPort : 'annotation',
        toPort: raw.version >= 3 ? item.toPort : 'annotation',
        kind: raw.version >= 3 ? item.kind : 'annotation'};
      const error = Contracts.connectionError(nodes, edges, edge);
      if (error) throw new Error('Некорректный файл схемы: ' + error);
      edges.push(edge);
    }
    return {format: 'architect', version: raw.definitions?.length ? 4 : 3, name: text(raw.name, 160, true), types, nodes, edges, definitions: clone(raw.definitions || [])};
  }

  function persist(announce = false) {
    if (runView) return;
    if (activeProject) {
      activeProject.meta.name = state.name;
      activeProject.dirty = true; unsaved = true;
      cacheProjectDraft();
      $('save-status').textContent = activeProject.conflict ? 'Конфликт сохранения' : 'Сохраняется…';
      clearTimeout(projectSaveTimer);
      if (!activeProject.conflict) projectSaveTimer = setTimeout(() => flushProject().then(() => { if (announce) toast('Проект сохранён'); }).catch(error => toast(error.message)), announce ? 0 : 450);
      return;
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable()));
      unsaved = false;
      $('save-status').textContent = 'Схема восстановлена локально';
      if (announce) toast('Схема и каталог блоков сохранены в этом браузере');
    } catch {
      unsaved = true;
      $('save-status').textContent = 'Не сохранено — скачайте JSON';
      toast('Браузер не разрешил сохранение. Скачайте схему через «Экспорт JSON».');
    }
  }

  function commit(change) {
    if (runView) return;
    const before = clone(state);
    change();
    if (JSON.stringify(before) === JSON.stringify(state)) return;
    past.push(before);
    if (past.length > 50) past.shift();
    future = [];
    persist();
    render();
    window.dispatchEvent(new Event('architect-diagram-change'));
  }

  function history(redo) {
    if (runView) return;
    const source = redo ? future : past;
    if (!source.length) return;
    const nodeCount = state.nodes.length;
    (redo ? past : future).push(clone(state));
    state = source.pop();
    multiSelected.clear();
    selected = null;
    connection = null;
    persist();
    render();
    if (state.nodes.length !== nodeCount) fit(true);
    window.dispatchEvent(new Event('architect-diagram-change'));
  }

  function el(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function viewCenter() {
    return {x: ($('viewport').clientWidth / 2 - camera.x) / camera.scale - 90, y: ($('viewport').clientHeight / 2 - camera.y) / camera.scale - 55};
  }
  function frameScreenScale() {
    const view = $('viewport');
    return view.clientWidth ? view.getBoundingClientRect().width / view.clientWidth : 1;
  }

  function makeNode(type) {
    // Adding from the fixed toolbar must work even if the sheet was panned away.
    if (!mobileUI) {
      $('canvas-editor').dispatchEvent(new Event('frame-reset'));
      canvasSize = {width: $('viewport').clientWidth, height: $('viewport').clientHeight};
      requestAnimationFrame(revealSelectedNode);
    }
    const center = viewCenter();
    const node = {id: uid(), typeId: type.id, name: type.name, description: type.description, execution: Contracts.toExecution({kind: type.behavior || 'note', version: 1})};
    const startX = center.x;
    const right = ($('viewport').clientWidth - camera.x) / camera.scale;
    // Typed cards are taller; place the whole rectangle so another card cannot cover its ports.
    while (state.nodes.some(item => center.x < item.x + nodeWidth(item) + 24 && center.x + nodeWidth(node) + 24 > item.x &&
        center.y < item.y + nodeHeight(item) + 24 && center.y + nodeHeight(node) + 24 > item.y)) {
      center.x += 300;
      if (center.x + nodeWidth(node) > right) { center.x = startX; center.y += 250; }
    }
    return {...node, ...center};
  }

  function addNode(type) {
    if (state.nodes.length >= 500) return toast('На одной схеме можно разместить до 500 блоков.');
    commit(() => {
      const node = makeNode(type);
      state.nodes.push(node);
      selected = node.id;
    });
    setLibrary(false);
  }

  function renderLibrary() {
    const query = normalizeSearch($('block-search').value);
    const matches = personalBlocks.filter(item => normalizeSearch(item.type.name + ' ' + item.type.description + ' ' + item.origin_name).includes(query));
    $('library-empty').hidden = !personalLoaded || matches.length > 0;
    if (personalLoaded) $('library-empty').textContent = personalBlocks.length ? 'Ничего не найдено.' : 'У вас пока нет своих блоков.';
    $('library-list').replaceChildren();
    for (const item of matches) {
      const row = el('div', 'type-item');
      const add = el('button', 'picker-block', item.type.name);
      add.setAttribute('aria-label', `Добавить «${item.type.name}» на схему`);
      add.title = [item.type.description, 'Создан в схеме: ' + item.origin_name].filter(Boolean).join('\n');
      add.onclick = async () => {
        add.disabled = true;
        try { await addPersonalBlock(item); }
        catch (error) { toast(error.message); }
        finally { add.disabled = false; }
      };
      row.append(add);
      if (item.type.block.kind.startsWith('subgraph_')) {
        const exportButton = el('button', '', '↓');
        exportButton.setAttribute('aria-label', `Экспорт подсхемы «${item.type.name}»`);
        exportButton.onclick = () => downloadJSON({format: 'architect.block-package', version: 1,
          kind: item.type.block.kind, definitions: item.definitions}, 'my-block');
        row.append(exportButton);
      }
      $('library-list').append(row);
    }
  }
  async function loadPersonalBlocks() {
    const generation = ++personalGeneration;
    personalLoaded = false; $('library-list').replaceChildren();
    $('library-empty').hidden = false; $('library-empty').textContent = 'Загружаем ваши блоки…';
    $('personal-block-retry').hidden = true;
    try {
      const result = await api('/api/blocks/personal-list', {});
      if (generation !== personalGeneration) return;
      personalBlocks = result.blocks; personalLoaded = true; renderLibrary();
    } catch (error) {
      if (generation !== personalGeneration) return;
      $('library-empty').hidden = false; $('library-empty').textContent = 'Не удалось загрузить ваши блоки. ' + error.message;
      $('personal-block-retry').hidden = false;
    }
  }
  async function registerPersonalBlock(diagram, typeId) {
    const result = await api('/api/blocks/personal-create', {diagram, type_id: typeId});
    ++personalGeneration;
    personalBlocks = [result.block, ...personalBlocks.filter(item => item.id !== result.block.id)];
    personalLoaded = true;
    return result.block;
  }
  async function addPersonalBlock(item) {
    const existing = state.types.find(type => type.behavior === item.type.block.kind && type.name === item.type.name && type.description === item.type.description && type.color === item.type.color);
    if ((!existing && state.types.length >= 200) || state.nodes.length >= 500) throw new Error('Достигнут лимит блоков или типов схемы.');
    const original = JSON.stringify(state), diagram = serializable();
    const definitions = new Map((diagram.definitions || []).map(d => [d.kind, d]));
    for (const d of item.definitions) definitions.set(d.kind, d);
    diagram.definitions = [...definitions.values()]; diagram.version = diagram.definitions.length ? 4 : 3;
    const typeId = existing?.id || uid();
    if (!existing) diagram.types.push({...clone(item.type), id: typeId});
    const next = await prepareDiagram(diagram);
    if (JSON.stringify(state) !== original || runView) throw new Error('Схема изменилась. Добавьте блок ещё раз.');
    commit(() => { state = next; const node = makeNode(state.types.find(t => t.id === typeId)); state.nodes.push(node); selected = node.id; });
    setLibrary(false); $('viewport').focus({preventScroll: true});
  }

  function portOffset(node, side, id) {
    const index = Contracts.ports(node, side, state.edges).findIndex(port => port.id === id);
    return 88 + Math.max(0, index) * 22;
  }

  function nodeWidth(node) { return node.width ?? 180; }
  function nodeMinimumHeight(node) {
    return 88 + 22 * Math.max(1, Contracts.ports(node, 'input', state.edges).length, Contracts.ports(node, 'output', state.edges).length);
  }
  function nodeHeight(node) { return Math.max(nodeMinimumHeight(node), node.height ?? 0); }
  function resizeNode(node, width, height) {
    const nextWidth = Math.round(Math.max(180, Math.min(1600, width)));
    const nextHeight = Math.round(Math.max(nodeMinimumHeight(node), Math.min(4096, height)));
    if (nextWidth !== nodeWidth(node) || nextHeight !== nodeHeight(node)) { node.width = nextWidth; node.height = nextHeight; }
  }

  function renderContract() {
    const contract = Contracts.get($('node-behavior').value);
    $('contract-ports').replaceChildren();
    for (const [side, label] of [['inputs', 'Вход'], ['outputs', 'Выход']]) for (const port of contract[side]) {
      $('contract-ports').append(el('li', '', `${label}: ${port.label} · ${Contracts.catalog.types[port.type].label}${port.required ? ' · обязательный' : ''}`));
    }
    if (!contract.inputs.length && !contract.outputs.length) $('contract-ports').append(el('li', '', 'Связи описания без передачи данных.'));
  }

  function renderEdges() {
    const svg = $('edges');
    svg.replaceChildren();
    const ns = 'http://www.w3.org/2000/svg';
    const defs = document.createElementNS(ns, 'defs');
    const marker = document.createElementNS(ns, 'marker');
    for (const [key, value] of Object.entries({id: 'arrow', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '5', markerHeight: '5', orient: 'auto-start-reverse'})) marker.setAttribute(key, value);
    const arrow = document.createElementNS(ns, 'path');
    arrow.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    arrow.setAttribute('fill', '#a5aec5');
    marker.append(arrow); defs.append(marker); svg.append(defs);
    const nodes = new Map(state.nodes.map(node => [node.id, node]));
    for (const edge of state.edges) {
      const from = nodes.get(edge.from), to = nodes.get(edge.to);
      const x = from.x + nodeWidth(from), y = from.y + portOffset(from, 'output', edge.fromPort), endX = to.x, endY = to.y + portOffset(to, 'input', edge.toPort);
      const bend = Math.max(70, Math.abs(endX - x) / 2);
      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', `M ${x} ${y} C ${x + bend} ${y}, ${endX - bend} ${endY}, ${endX} ${endY}`);
      path.setAttribute('class', 'edge' + (edge.kind === 'annotation' ? ' annotation-edge' : ''));
      const title = document.createElementNS(ns, 'title'); title.textContent = edge.kind === 'annotation' ? 'Связь описания (без передачи данных)' : `${edge.fromPort} → ${edge.toPort}`; path.append(title);
      path.setAttribute('marker-end', 'url(#arrow)');
      svg.append(path);
    }
  }

  function renderNodes() {
    $('nodes').replaceChildren();
    for (const node of state.nodes) {
      const type = state.types.find(item => item.id === node.typeId);
      const card = el('article', 'node' + (selected === node.id || multiSelected.has(node.id) ? ' selected' : ''));
      card.dataset.id = node.id;
      card.style.left = `${node.x}px`;
      card.style.top = `${node.y}px`;
      card.style.setProperty('--node-color', type.color);
      card.tabIndex = 0;
      card.setAttribute('aria-label', `Блок: ${node.name}`);
      const contract = Contracts.get(node.execution.mode);
      const heading = el('h3', '', node.name); heading.title = node.name;
      card.append(el('span', 'execution-badge', contract.label), heading, el('p', '', node.description || 'Добавьте описание в свойствах'));
      card.style.width = `${nodeWidth(node)}px`;
      card.style.height = `${nodeHeight(node)}px`;
      card.style.minHeight = `${nodeMinimumHeight(node)}px`;
      for (const side of ['input', 'output']) for (const spec of Contracts.ports(node, side, state.edges)) {
        const active = side === 'output' && connection?.node === node.id && connection?.port === spec.id;
        const port = el('button', `port ${side}${active ? ' active' : ''}`);
        port.disabled = !!runView;
        port.dataset.port = spec.id;
        port.style.top = `${portOffset(node, side, spec.id) - 7}px`;
        port.setAttribute('aria-label', `${side === 'input' ? 'Вход' : 'Выход'}: ${node.name} · ${spec.label}`);
        port.title = `${spec.label} · ${Contracts.catalog.types[spec.type].label}${spec.required ? ' · обязательный вход' : ''}`;
        port.addEventListener('pointerdown', event => event.stopPropagation());
        port.onclick = event => {
          event.stopPropagation();
          if (side === 'output') {
            connection = active ? null : {node: node.id, port: spec.id};
            renderNodes();
            $('connection-hint').hidden = !connection;
          } else if (connection) {
            const edge = {id: uid(), from: connection.node, fromPort: connection.port, to: node.id, toPort: spec.id,
              kind: spec.type === 'annotation' ? 'annotation' : 'data'};
            const error = Contracts.connectionError(state.nodes, state.edges, edge);
            if (error) return toast(error);
            if (state.edges.length >= 1000) return toast('На одной схеме можно создать до 1000 связей.');
            commit(() => { state.edges.push(edge); connection = null; });
          } else toast('Сначала нажмите выход другого блока.');
        };
        const label = el('span', `port-label ${side}-label`, spec.label);
        label.style.top = `${portOffset(node, side, spec.id) - 7}px`;
        label.title = port.title;
        card.append(port, label);
      }
      const resize = el('button', 'node-resize');
      resize.type = 'button'; resize.setAttribute('aria-label', `Изменить размер: ${node.name}`);
      resize.title = 'Потяните за угол · стрелки: 10 px, Shift: 50 px · двойной щелчок: стандартный размер';
      resize.addEventListener('pointerdown', event => {
        if (runView) return;
        if (event.button !== 0 || pointer) return;
        event.stopPropagation(); event.preventDefault();
        selected = node.id; multiSelected.clear();
        for (const other of $('nodes').children) other.classList.toggle('selected', other === card);
        renderInspector();
        pointer = {kind: 'resize', pointerId: event.pointerId, node, card, handle: resize, startX: event.clientX, startY: event.clientY,
          width: nodeWidth(node), height: nodeHeight(node), before: clone(state)};
        resize.setPointerCapture(event.pointerId);
      });
      resize.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault(); event.stopPropagation();
        const step = event.shiftKey ? 50 : 10;
        commit(() => { selected = node.id; resizeNode(node, nodeWidth(node) + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0),
          nodeHeight(node) + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0)); });
        $('nodes').querySelector(`[data-id="${node.id}"] .node-resize`)?.focus({preventScroll: true});
      });
      resize.ondblclick = event => { event.stopPropagation(); commit(() => { delete node.width; delete node.height; }); };
      card.append(resize);
      card.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        event.stopPropagation();
        if (event.shiftKey) {
          if (selected && !multiSelected.size) multiSelected.add(selected);
          if (multiSelected.has(node.id)) multiSelected.delete(node.id); else multiSelected.add(node.id);
          selected = null; renderNodes(); renderInspector(); return;
        }
        multiSelected.clear();
        selected = node.id;
        document.querySelectorAll('.node').forEach(item => item.classList.toggle('selected', item.dataset.id === selected));
        renderInspector();
        if (runView) return;
        pointer = {kind: 'node', node, startX: event.clientX, startY: event.clientY, x: node.x, y: node.y, before: clone(state), card};
        card.setPointerCapture(event.pointerId);
      });
      card.addEventListener('keydown', event => {
        if (event.target !== card) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); selected = node.id; render(); if (mobile) mobile.openProperties(); else $('node-name').focus();
        }
      });
      $('nodes').append(card);
    }
    renderPipeline();
  }

  $('inspector-back').onclick = () => { $('viewport').scrollIntoView({block: 'start'}); $('viewport').focus({preventScroll: true}); };

  function renderInspector() {
    syncCustomOptions();
    for (const [control, properties] of runViewControls) Object.assign(control, properties);
    runViewControls.clear();
    document.querySelector('.inspector-heading h2').textContent = runView ? 'Параметры запуска · только просмотр' : 'Настройка блока';
    const node = state.nodes.find(item => item.id === selected);
    document.querySelector('.inspector').hidden = !node;
    document.querySelector('.layout').classList.toggle('has-selection', !!node);
    $('pack-subgraph').hidden = !node && !multiSelected.size;
    $('inspector-empty').hidden = !!node;
    $('inspector-form').hidden = !node;
    mobile?.selection();
    if (!node) return;
    $('node-name').value = node.name;
    $('node-description').value = node.description;
    const execution = node.execution || executionDefaults();
    $('node-behavior').value = execution.mode;
    $('kg-dataset').value = execution.dataset || '';
    $('kg-token').value = '';
    $('hf-repo').value = execution.hf_repo || '';
    $('hf-revision').value = execution.hf_revision || 'main';
    $('hf-token').value = '';
    $('or-model').value = execution.model;
    $('or-system').value = execution.system;
    $('or-prompt').value = execution.prompt;
    $('or-max-tokens').value = execution.max_tokens;
    $('or-temperature').value = execution.temperature;
    $('csv-file').value = execution.csv_file;
    $('csv-encoding').value = execution.csv_encoding;
    $('csv-delimiter').value = execution.csv_delimiter;
    $('csv-row-index').value = execution.csv_row_index;
    $('prompt-template').value = execution.prompt_template;
    $('local-prompt').value = execution.local_prompt;
    $('local-max-tokens').value = execution.local_max_tokens;
    updateBehavior();
    renderRun();
    renderDataset();
    renderHubModel();
    $('node-connections').replaceChildren();
    const edges = state.edges.filter(edge => edge.from === node.id || edge.to === node.id);
    if (!edges.length) $('node-connections').append(el('p', 'muted', 'Пока нет связей.'));
    for (const edge of edges) {
      const outgoing = edge.from === node.id;
      const other = state.nodes.find(item => item.id === (outgoing ? edge.to : edge.from));
      const row = el('div', 'connection-row');
      const remove = el('button', '', '×');
      remove.type = 'button';
      remove.setAttribute('aria-label', `Удалить связь с «${other.name}»`);
      remove.onclick = () => commit(() => { state.edges = state.edges.filter(item => item.id !== edge.id); });
      row.append(el('span', '', `${outgoing ? '→' : '←'} ${other.name} · ${edge.kind === 'annotation' ? 'описание' : edge.fromPort + ' → ' + edge.toPort}`), remove);
      $('node-connections').append(row);
    }
    $('run-view-code').hidden = !runView || node.execution.mode !== 'python_code';
    if (!$('run-view-code').hidden) {
      const settings = Contracts.fromExecution(node.execution).settings;
      $('run-view-code-text').value = settings.code || '';
      $('run-view-code-params').value = settings.params || '{}';
    }
    if (runView) for (const control of $('inspector-form').querySelectorAll('input, textarea, select')) {
      runViewControls.set(control, {readOnly: control.readOnly, disabled: control.disabled});
      if (control.tagName === 'SELECT' || ['checkbox', 'radio', 'color', 'file'].includes(control.type)) control.disabled = true;
      else control.readOnly = true;
    }
  }

  function renderCamera() {
    $('world').style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
    $('viewport').style.backgroundPosition = `${camera.x}px ${camera.y}px`;
    $('viewport').style.backgroundSize = `${Math.max(10, 20 * camera.scale)}px ${Math.max(10, 20 * camera.scale)}px`;
    const outerScale = frameScreenScale(), visibleScale = camera.scale * outerScale;
    const sceneMode = document.body.classList.contains('scene-mode');
    for (const prefix of ['', 'fullscreen-']) {
      $(prefix + 'zoom-value').textContent = `${visibleScale < .01 ? (visibleScale * 100).toFixed(1) : Math.round(visibleScale * 100)}%`;
      $(prefix + 'zoom-out').disabled = sceneMode ? outerScale <= .15 : camera.scale <= .001;
      $(prefix + 'zoom-in').disabled = sceneMode ? outerScale >= 2 : camera.scale >= 2;
    }
  }

  function render() {
    syncCustomOptions();
    renderProjectStatus();
    $('diagram-name').value = state.name;
    $('diagram-name').readOnly = !!runView;
    window.WorkspaceNavigation.resizeTitle();
    document.title = `${state.name} — Архитектор`;
    $('welcome').hidden = true;
    $('first-block').textContent = 'Собрать схему вручную';
    $('connection-hint').hidden = !connection;
    $('undo').disabled = !past.length;
    $('redo').disabled = !future.length;
    renderLibrary(); renderNodes(); renderEdges(); renderInspector(); renderCamera();
    if (mobileUI && state.nodes.length > previousMobileNodeCount) requestAnimationFrame(() => fit(true));
    previousMobileNodeCount = state.nodes.length;
  }

  function fit(readable = false) {
    readable = readable === true;
    if (!$('viewport').clientWidth || !$('viewport').clientHeight) { pendingCanvasFit = {readable}; return; }
    if (!document.body.classList.contains('canvas-fullscreen-open')) $('canvas-editor').dispatchEvent(new Event('frame-reset'));
    pendingCanvasFit = false;
    canvasSize = {width: $('viewport').clientWidth, height: $('viewport').clientHeight};
    if (!state.nodes.length) { camera = {x: 0, y: 0, scale: initialScale()}; renderCamera(); return; }
    const left = Math.min(...state.nodes.map(node => node.x));
    const top = Math.min(...state.nodes.map(node => node.y));
    const right = Math.max(...state.nodes.map(node => node.x + nodeWidth(node)));
    const bottom = Math.max(...state.nodes.map(node => node.y + nodeHeight(node)));
    const first = state.nodes.find(node => node.id === selected) || [...state.nodes].sort((a, b) => a.x - b.x || a.y - b.y)[0];
    if (readable) {
      // The desktop scene moves the whole sheet. Keep every card inside that
      // sheet, rather than panning cards beyond its overflow boundary.
      const detail = {width: right - left + 80, height: bottom - top + 160,
        focusX: first.x - left, focusY: first.y - top, applied: false};
      $('canvas-editor').dispatchEvent(new CustomEvent('frame-fit-content', {detail}));
      if (detail.applied) {
        camera = {scale: 1, x: 40 - left, y: 80 - top};
        canvasSize = {width: $('viewport').clientWidth, height: $('viewport').clientHeight};
        renderCamera();
        return;
      }
    }
    const rect = $('viewport').getBoundingClientRect();
    const outerScale = frameScreenScale();
    const landscape = mobileUI && rect.width > rect.height && innerHeight <= 600;
    const inset = mobileUI ? landscape ? {left: 24, right: selected ? 360 : 24, top: 64, bottom: 72} :
      {left: 24, right: 24, top: 72, bottom: selected ? 170 : 72} : {left: 40, right: 40, top: 50, bottom: 50};
    if (!mobileUI) {
      const tools = document.querySelector('.canvas-add-tools');
      const controls = document.querySelector('.canvas-bottom .zoom-tools');
      if (outerScale === 1 && tools.offsetParent) inset.top = Math.max(inset.top, tools.getBoundingClientRect().bottom - rect.top + 16);
      if (outerScale === 1 && controls.offsetParent) inset.bottom = Math.max(inset.bottom, rect.bottom - controls.getBoundingClientRect().top + 16);
    }
    const width = Math.max(40, $('viewport').clientWidth - inset.left - inset.right), height = Math.max(40, $('viewport').clientHeight - inset.top - inset.bottom);
    const fittedScale = Math.min(mobileUI ? .85 : 1.2, width / (right - left), height / (bottom - top));
    const readableScale = initialScale();
    const scale = Math.max(readable ? readableScale : .001, fittedScale);
    camera = {scale, x: inset.left + width / 2 - (left + right) / 2 * scale, y: inset.top + height / 2 - (top + bottom) / 2 * scale};
    if (readable && fittedScale < readableScale) {
      camera.x = inset.left - first.x * scale;
      camera.y = inset.top - first.y * scale;
    }
    renderCamera();
  }

  function zoom(factor, point) {
    const rect = $('viewport').getBoundingClientRect();
    const scale = Math.max(.001, Math.min(2, camera.scale * factor));
    const outerScale = frameScreenScale();
    const x = point ? (point.x - rect.left) / outerScale : $('viewport').clientWidth / 2;
    const y = point ? (point.y - rect.top) / outerScale : $('viewport').clientHeight / 2;
    camera.x = x - (x - camera.x) * scale / camera.scale;
    camera.y = y - (y - camera.y) * scale / camera.scale;
    camera.scale = scale; renderCamera();
  }

  function openBlockDialog() {
    if (state.types.length >= 200 || state.nodes.length >= 500) return toast('Достигнут лимит: 200 типов или 500 блоков.');
    setLibrary(false);
    $('block-form').reset(); $('block-create-error').hidden = true; $('block-dialog').showModal();
  }

  let pickerMode = 'blocks', pickerTab = 'community', globalGeneration = 0, globalSearchTimer;
  const pickerQueries = {};
  const pickerSearchKey = () => pickerMode === 'blocks' ? pickerTab : pickerMode;
  const normalizeSearch = text => text.toLocaleLowerCase('ru').replaceAll('ё', 'е').trim();
  function filterBlocks() {
    const query = normalizeSearch($('block-search').value);
    let found = false;
    for (const group of $('blocks-community').querySelectorAll('.block-category')) {
      const categoryMatches = normalizeSearch(group.querySelector('summary').textContent).includes(query);
      const items = [...group.querySelectorAll('[data-block-search]')];
      let matches = false;
      for (const item of items) {
        item.hidden = !!query && !categoryMatches && !normalizeSearch(item.dataset.blockSearch).includes(query);
        matches ||= !item.hidden;
      }
      group.hidden = !!query && !matches && !categoryMatches;
      if (!query && group.dataset.wasOpen !== undefined) { group.open = group.dataset.wasOpen === 'true'; delete group.dataset.wasOpen; }
      if (query) { if (group.dataset.wasOpen === undefined) group.dataset.wasOpen = String(group.open); group.open = !group.hidden; }
      found ||= !group.hidden;
    }
    $('block-search-empty').hidden = found;
  }
  function appendLibraryReleases(list, matches, status) {
    const group = el('details', 'block-category'); group.open = true; group.append(el('summary', '', 'Подсхемы'));
    for (const release of matches) {
      const card = el('article', 'picker-release');
      card.append(el('strong', '', release.name), el('p', 'muted', `@${release.username} · версия ${release.number}`));
      const view = el('button', '', 'Открыть версию');
      view.onclick = () => community.openBlockRelease(release.id);
      const add = el('button', '', 'Добавить');
      add.onclick = async () => {
        add.disabled = true; status.textContent = '';
        try { if (await community.addBlockRelease(release)) setLibrary(false); }
        catch (error) { status.textContent = error.message; }
        finally { add.disabled = false; }
      };
      card.append(view, add); group.append(card);
    }
    list.append(group);
  }
  async function searchAllCommunityBlocks() {
    clearTimeout(globalSearchTimer);
    const generation = ++globalGeneration, query = $('block-search').value.trim();
    const status = $('global-block-status'), list = $('global-block-list');
    list.replaceChildren(); $('global-block-retry').hidden = true;
    if (!query) { status.textContent = 'Введите название блока или автора.'; return; }
    status.textContent = 'Ищем во всех блоках сообщества…';
    try {
      const result = await api('/api/community/catalog', {kind: 'block', search: query});
      if (generation !== globalGeneration || pickerTab !== 'global' || $('block-library').hidden) return;
      status.textContent = !result.releases.length ? 'Ничего не найдено.' : result.releases.length === 200 ? 'Показаны первые 200 результатов. Уточните запрос.' : '';
      if (result.releases.length) appendLibraryReleases(list, result.releases, status);
    } catch (error) {
      if (generation !== globalGeneration || pickerTab !== 'global' || $('block-library').hidden) return;
      status.textContent = 'Не удалось выполнить поиск. ' + error.message; $('global-block-retry').hidden = false;
    }
  }
  function selectPickerTab(tab) {
    pickerQueries[pickerSearchKey()] = $('block-search').value;
    pickerTab = tab; $('block-search').value = pickerQueries[tab] || ''; ++globalGeneration; clearTimeout(globalSearchTimer);
    $('block-search').placeholder = tab === 'global' ? 'Название блока или автор' : tab === 'community' ? 'Найти в библиотеке' : 'Найти блок или категорию';
    $('block-search').setAttribute('aria-label', tab === 'global' ? 'Поиск по всем блокам сообщества' : 'Поиск блоков и категорий');
    for (const name of ['local', 'community', 'global']) {
      const active = name === tab;
      $('blocks-' + name).hidden = !active;
      $('blocks-' + name + '-tab').setAttribute('aria-selected', String(active));
      $('blocks-' + name + '-tab').tabIndex = active ? 0 : -1;
    }
    if (tab === 'community') filterBlocks(); else if (tab === 'global') searchAllCommunityBlocks(); else loadPersonalBlocks();
  }
  function setLibrary(open) {
    if (open && mobileUI && $('codex-chat').open) $('codex-chat-close').click();
    $('block-library').hidden = !open;
    $('library-toggle').setAttribute('aria-expanded', String(open));
    if (!open) { hideProjectPreview(); ++personalGeneration; ++globalGeneration; ++catalogRequest; ++datasetGeneration; clearTimeout(globalSearchTimer); return; }
    selectPickerMode(pickerMode);
    if (!mobileUI) $('block-search').focus(); else $('library-close').focus({preventScroll: true});
  }
  $('block-search').oninput = () => {
    pickerQueries[pickerSearchKey()] = $('block-search').value;
    if (pickerMode === 'projects') { renderProjectList(); return; }
    if (pickerMode === 'data') { renderDatasetList(); return; }
    if (pickerTab === 'global') {
      ++globalGeneration; clearTimeout(globalSearchTimer);
      $('global-block-list').replaceChildren(); $('global-block-retry').hidden = true;
      $('global-block-status').textContent = $('block-search').value.trim() ? 'Ищем во всех блоках сообщества…' : 'Введите название блока или автора.';
      globalSearchTimer = setTimeout(searchAllCommunityBlocks, 250);
    } else { filterBlocks(); renderLibrary(); }
  };
  $('block-search').addEventListener('keydown', event => {
    if (event.key === 'Enter' && pickerMode === 'blocks' && pickerTab === 'global') { event.preventDefault(); searchAllCommunityBlocks(); }
  });
  $('global-block-retry').onclick = searchAllCommunityBlocks;
  $('personal-block-retry').onclick = loadPersonalBlocks;
  for (const name of ['local', 'community', 'global']) $('blocks-' + name + '-tab').onclick = () => selectPickerTab(name);
  document.querySelector('.block-picker-tabs').onkeydown = event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = ['local', 'community'];
    const tab = event.key === 'Home' ? 'local' : event.key === 'End' ? 'global' : tabs[(tabs.indexOf(pickerTab) + (event.key === 'ArrowRight' ? 1 : 2)) % 3];
    selectPickerTab(tab); $('blocks-' + tab + '-tab').focus();
  };
  $('block-library').addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setLibrary(false); $('library-toggle').focus(); }
  });
  $('library-toggle').onclick = () => setLibrary($('block-library').hidden);
  $('library-close').onclick = () => { setLibrary(false); $('library-toggle').focus(); };
  $('library-create').onclick = openBlockDialog;
  $('create-type').onclick = openBlockDialog;
  $('first-block').onclick = () => setLibrary(true);
  $('close-dialog').onclick = $('cancel-dialog').onclick = () => $('block-dialog').close();
  $('block-form').onsubmit = async event => {
    event.preventDefault();
    const name = $('type-name').value.trim();
    if (!name) { $('type-name').focus(); return; }
    const button = $('block-form').querySelector('button[type=submit]'); button.disabled = true;
    $('block-create-error').hidden = true;
    const original = JSON.stringify(state);
    const type = {id: uid(), name, description: $('type-description').value.trim(), color: $('type-color').value, behavior: $('type-behavior').value};
    try {
      const diagram = {format: 'architect', version: 3, name: state.name, nodes: [], edges: [], definitions: [],
        types: [{id: type.id, name, description: type.description, color: type.color, block: {kind: type.behavior, version: Contracts.get(type.behavior).version}}]};
      await registerPersonalBlock(diagram, type.id);
      if (JSON.stringify(state) !== original || !$('block-dialog').open || runView) { toast('Блок сохранён в «Личном». Откройте каталог, чтобы добавить его на схему.'); return; }
      commit(() => { state.types.push(type); const node = makeNode(type); state.nodes.push(node); selected = node.id; });
      $('block-dialog').close(); toast('Блок добавлен в «Личное» и на схему');
    } catch (error) { $('block-create-error').hidden = false; $('block-create-error').textContent = 'Не удалось создать блок: ' + error.message; }
    finally { button.disabled = false; }
  };

  function saveNode() {
    if (runView) return true;
    if (!$('inspector-form').reportValidity()) return false;
    const node = state.nodes.find(item => item.id === selected);
    const name = $('node-name').value.trim();
    if (!name || !node) return false;
    let execution;
    const hfRepo = $('hf-repo').value.trim(), hfRevision = $('hf-revision').value.trim() || 'main';
    const sameModel = node.execution?.hf_repo === hfRepo && node.execution?.hf_revision === hfRevision;
    const hub = currentHubModel();
    try {
      execution = parseExecution({mode: $('node-behavior').value, model: $('or-model').value.trim(), system: $('or-system').value,
        custom_settings: node.execution.custom_settings,
        hf_repo: hfRepo, hf_revision: hfRevision, hf_commit: hub?.info?.commit || (sameModel ? node.execution.hf_commit : ''),
        hf_files: hub?.info ? [...hub.chosen] : sameModel ? node.execution.hf_files : [],
        input_values: node.execution.input_values, csv_file: $('csv-file').value.trim(), csv_delimiter: $('csv-delimiter').value,
        csv_encoding: $('csv-encoding').value,
        csv_row_index: Number($('csv-row-index').value),
        prompt_template: $('prompt-template').value, local_prompt: $('local-prompt').value, local_max_tokens: Number($('local-max-tokens').value),
        dataset: $('kg-dataset').value.trim(), prompt: $('or-prompt').value, max_tokens: Number($('or-max-tokens').value), temperature: Number($('or-temperature').value)});
      if (execution.mode.startsWith('subgraph_')) execution = readSubgraphFields(execution.mode);
      if (mlKinds.includes(execution.mode)) execution = readMLFields(execution);
    } catch (error) { toast(error.message); return false; }
    const proposed = state.nodes.map(item => item.id === node.id ? {...item, execution} : item);
    for (const edge of state.edges) {
      const error = Contracts.connectionError(proposed, state.edges, edge);
      if (error) { toast('Нельзя изменить поведение: ' + error + ' Удалите несовместимые связи.'); return false; }
    }
    commit(() => { node.name = name; node.description = $('node-description').value.trim(); node.execution = execution; });
    mobile?.applied();
    return true;
  }
  $('inspector-form').onsubmit = event => { event.preventDefault(); saveNode(); };
  function deleteNode() {
    if (!selected) return;
    commit(() => {
      state.nodes = state.nodes.filter(node => node.id !== selected);
      state.edges = state.edges.filter(edge => edge.from !== selected && edge.to !== selected);
      if (connection?.node === selected) connection = null;
      selected = null;
    });
  }
  $('delete-node').onclick = deleteNode;
  $('diagram-name').onchange = () => commit(() => { state.name = $('diagram-name').value.trim() || 'Новая схема'; });
  $('save').onclick = saveCurrentProject;
  async function openDesignDocuments(create, releaseId) {
    if (selected && !saveNode()) return;
    try {
      if (!activeProject && !runView) {
        await saveCurrentProject();
        if (!activeProject) return;
      }
      await flushProject();
      const url = new URL('/design-docs.html', location.origin);
      if (activeProject) url.searchParams.set('project', activeProject.meta.id);
      if (create) url.searchParams.set('new', '1');
      if (releaseId) url.searchParams.set('release', releaseId);
      location.href = url;
    } catch (error) { toast(error.message); }
  }
  $('design-document-create').onclick = () => openDesignDocuments(true);

  $('board-open').onclick = async () => {
    if (selected && !saveNode()) return;
    try {
      if (!activeProject && !runView) {
        await saveCurrentProject();
        if (!activeProject) return;
      }
      await flushProject();
      location.href = '/board.html' + (activeProject ? '?project=' + encodeURIComponent(activeProject.meta.id) : '');
    } catch (error) { toast(error.message); }
  };

  async function saveCurrentProject() {
    if (runView || savingCurrentProject) return;
    if (selected && !saveNode()) return;
    savingCurrentProject = true;
    let backupSaved = true;
    $('save').disabled = true;
    try {
      if (activeProject) {
        await flushProject();
        backupSaved = cacheProjectDraft();
      } else {
        // Keep the editor state while the request is pending: edits must not be lost.
        const sourceState = state, diagram = serializable();
        persist();
        const result = await api('/api/projects/create', {name: state.name, description: '', diagram});
        if (activeProject || state !== sourceState || runView) {
          toast('Проект сохранён. Откройте его через «+ → Каталог проектов».');
          return;
        }
        activeProject = {meta: {...result.project, name: state.name}, description: result.description, dirty: false, conflict: false};
        try {
          localStorage.setItem(ACTIVE_PROJECT_KEY, result.project.id);
          const local = localStorage.getItem(STORAGE_KEY);
          if (local === JSON.stringify(serializable())) localStorage.removeItem(STORAGE_KEY);
        } catch {}
        const url = new URL(location.href); url.searchParams.set('project', result.project.id);
        window.history.replaceState(null, '', url);
        if (JSON.stringify(diagram) !== JSON.stringify(serializable())) {
          persist();
          await flushProject();
        }
        backupSaved = cacheProjectDraft();
        renderProjectStatus();
        await loadPipelineHistory().catch(error => toast(error.message));
      }
      $('save-status').textContent = 'Сохранено';
      toast(backupSaved ? 'Проект сохранён' : 'Проект сохранён, но браузер не разрешил создать резервную копию. Вы можете экспортировать проект.');
      return true;
    } catch (error) {
      $('save-status').textContent = 'Не удалось сохранить проект';
      toast('Не удалось сохранить проект: ' + error.message);
    } finally {
      savingCurrentProject = false;
      if (runViewControls.has($('save'))) runViewControls.get($('save')).disabled = false;
      $('save').disabled = !!runView;
    }
  }
  $('undo').onclick = () => history(false);
  $('redo').onclick = () => history(true);
  $('fit').onclick = fit;
  $('zoom-in').onclick = () => zoom(1.2);
  $('zoom-out').onclick = () => zoom(1 / 1.2);
  $('zoom-value').onclick = () => {
    fit(true);
    zoom(1 / camera.scale);
    revealSelectedNode();
  };
  $('canvas-editor').addEventListener('frame-scale-change', renderCamera);
  $('canvas-editor').addEventListener('frame-fit-request', () => fit(true));
  const canvasEditor = $('canvas-editor');
  let canvasExpanded = false, fullscreenBusy = false;
  function syncCanvasFullscreen() {
    const expanded = document.fullscreenElement === canvasEditor || canvasEditor.classList.contains('canvas-expanded');
    const changed = expanded !== canvasExpanded;
    canvasExpanded = expanded;
    $('canvas-fullscreen-toolbar').hidden = !expanded;
    $('canvas-fullscreen').setAttribute('aria-expanded', String(expanded));
    document.body.classList.toggle('canvas-fullscreen-open', expanded);
    if (changed) requestAnimationFrame(() => {
      fit(!canvasExpanded);
      (canvasExpanded ? $('canvas-fullscreen-exit') : $('canvas-fullscreen')).focus({preventScroll: true});
    });
  }
  async function toggleCanvasFullscreen() {
    if (fullscreenBusy) return;
    fullscreenBusy = true;
    try {
      if (document.fullscreenElement === canvasEditor) await document.exitFullscreen();
      else if (canvasEditor.classList.contains('canvas-expanded')) canvasEditor.classList.remove('canvas-expanded');
      else {
        if ($('codex-chat').open) $('codex-chat-close').click();
        setLibrary(false);
        try {
          if (!canvasEditor.requestFullscreen) throw new Error('Fullscreen unavailable');
          await canvasEditor.requestFullscreen();
        } catch (_) { canvasEditor.classList.add('canvas-expanded'); }
      }
    } catch (_) { toast('Не удалось переключить полный экран. Нажмите Esc.'); }
    finally { fullscreenBusy = false; syncCanvasFullscreen(); }
  }
  $('canvas-fullscreen').onclick = toggleCanvasFullscreen;
  $('canvas-fullscreen-exit').onclick = toggleCanvasFullscreen;
  $('fullscreen-fit').onclick = fit;
  $('fullscreen-zoom-in').onclick = () => zoom(1.2);
  $('fullscreen-zoom-out').onclick = () => zoom(1 / 1.2);
  document.addEventListener('fullscreenchange', syncCanvasFullscreen);
  function revealSelectedNode() {
    pendingSelectionReveal = false;
    if (mobileUI || !selected) return;
    const node = state.nodes.find(item => item.id === selected);
    if (!node) return;
    // Keep the selected card available when a side panel reduces the sheet.
    // Pan only: changing panels must never change graph geometry or zoom.
    const keepVisible = (offset, start, extent, available, margin) => {
      const low = margin, high = Math.max(low, available - margin - extent * camera.scale);
      const position = offset + start * camera.scale;
      return offset + Math.max(low, Math.min(high, position)) - position;
    };
    camera.x = keepVisible(camera.x, node.x, nodeWidth(node), $('viewport').clientWidth, 24);
    camera.y = keepVisible(camera.y, node.y, nodeHeight(node), $('viewport').clientHeight, 80);
    renderCamera();
  }
  // Keep the graph centred on window rotation/resizing without discarding a chosen zoom.
  new ResizeObserver(() => {
    const size = {width: $('viewport').clientWidth, height: $('viewport').clientHeight};
    if (!size.width || !size.height) return;
    if (pendingCanvasFit) { fit(pendingCanvasFit.readable); return; }
    if (canvasSize && (size.width !== canvasSize.width || size.height !== canvasSize.height)) {
      if (!pointer) {
        camera.x += (size.width - canvasSize.width) / 2;
        camera.y += (size.height - canvasSize.height) / 2;
        revealSelectedNode();
        renderCamera();
      } else pendingSelectionReveal = true;
    }
    canvasSize = size;
  }).observe($('viewport'));
  $('viewport').addEventListener('wheel', event => {
    if (pointer || event.target.closest('button, summary, input, select, textarea, a') || document.querySelector('dialog[open]:not(#codex-chat)')) return;
    event.preventDefault();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? $('viewport').clientHeight : 1);
    zoom(Math.exp(-Math.max(-300, Math.min(300, delta)) * .002), {x: event.clientX, y: event.clientY});
  }, {passive: false});

  $('new-diagram').onclick = async () => {
    if (creatingDiagram) return;
    if (savingCurrentProject) { toast('Дождитесь сохранения текущей схемы.'); return; }
    if (selected && !saveNode()) return;
    creatingDiagram = true; $('new-diagram').disabled = true;
    const sourceState = state, sourceProject = activeProject;
    try {
      // A new schema gets its own project identity; never clear the current one.
      if (activeProject) { await flushProject(); cacheProjectDraft(); }
      else if (state.nodes.length || state.types.length || state.name !== 'Новая схема') {
        if (!await saveCurrentProject()) return;
      }
      if (state !== sourceState || (sourceProject && activeProject !== sourceProject) || runView) return;
      const previous = activeProject, snapshot = JSON.stringify(state);
      const result = await api('/api/projects/create', {name: 'Новая схема', description: '', diagram: blank()});
      if (activeProject !== previous || JSON.stringify(state) !== snapshot || runView) {
        toast('Пустая схема создана в каталоге проектов. Текущая работа осталась открытой.'); return;
      }
      if ($('codex-chat').open) $('codex-chat-close').click();
      setLibrary(false);
      await adoptProject(result);
      if (mobileUI) $('viewport').focus({preventScroll: true});
      else { $('diagram-name').focus({preventScroll: true}); $('diagram-name').select(); }
      toast('Создана пустая схема');
    } catch (error) { toast('Не удалось создать схему: ' + error.message); }
    finally { creatingDiagram = false; $('new-diagram').disabled = false; }
  };
  $('export').onclick = () => {
    const blob = new Blob([JSON.stringify(serializable(), null, 2) + '\n'], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = el('a');
    link.href = url;
    link.download = (state.name.replace(/[^\p{L}\p{N}_-]+/gu, '-').slice(0, 80) || 'architecture') + '.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  $('import').onclick = () => $('import-file').click();
  $('import-file').onchange = async () => {
    const file = $('import-file').files[0];
    $('import-file').value = '';
    if (!file) return;
    try {
      if (file.size > 128 * 1024 * 1024) throw new Error('Файл слишком большой. Максимум — 128 МБ.');
      const next = await prepareDiagram(JSON.parse(await file.text()));
      if ((state.nodes.length || state.types.length) && !confirm('Заменить текущую схему и каталог данными из файла? Действие можно отменить.')) return;
      commit(() => { state = next; selected = null; connection = null; });
      fit(true); toast('Схема импортирована');
    } catch (error) { toast(error instanceof SyntaxError ? 'Не удалось прочитать JSON. Проверьте файл.' : error.message); }
  };

  $('canvas-editor').addEventListener('frame-background-click', () => {
    selected = null; multiSelected.clear(); renderNodes(); renderInspector();
  });
  $('viewport').addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button, summary, input, select, textarea, a')) return;
    selected = null; multiSelected.clear(); renderNodes(); renderInspector();
    pointer = {kind: 'pan', startX: event.clientX, startY: event.clientY, x: camera.x, y: camera.y};
    $('viewport').setPointerCapture(event.pointerId);
    $('viewport').classList.add('panning');
  });
  window.addEventListener('pointermove', event => {
    if (!pointer) return;
    if (pointer.kind === 'resize' && event.pointerId !== pointer.pointerId) return;
    const outerScale = frameScreenScale();
    const dx = (event.clientX - pointer.startX) / outerScale, dy = (event.clientY - pointer.startY) / outerScale;
    if (pointer.kind === 'pan') {
      camera.x = pointer.x + dx; camera.y = pointer.y + dy; renderCamera();
    } else if (pointer.kind === 'resize') {
      resizeNode(pointer.node, pointer.width + dx / camera.scale, pointer.height + dy / camera.scale);
      pointer.card.style.width = `${nodeWidth(pointer.node)}px`; pointer.card.style.height = `${nodeHeight(pointer.node)}px`;
      renderEdges();
    } else {
      pointer.node.x = Math.max(-100000, Math.min(100000, pointer.x + dx / camera.scale));
      pointer.node.y = Math.max(-100000, Math.min(100000, pointer.y + dy / camera.scale));
      pointer.card.style.left = `${pointer.node.x}px`; pointer.card.style.top = `${pointer.node.y}px`;
      renderEdges();
    }
  });
  function endPointer(event) {
    if (!pointer) return;
    if (pointer.kind === 'resize' && event.pointerId !== pointer.pointerId) return;
    const cancelled = pointer.kind === 'resize' && event.type === 'pointercancel';
    const resized = pointer.kind === 'resize' && (nodeWidth(pointer.node) !== pointer.width || nodeHeight(pointer.node) !== pointer.height);
    if (!cancelled && (resized || pointer.kind === 'node' && (pointer.node.x !== pointer.x || pointer.node.y !== pointer.y))) {
      past.push(pointer.before); if (past.length > 50) past.shift(); future = []; persist();
    }
    const restore = cancelled;
    if (restore) state = pointer.before;
    else if (pointer.kind === 'resize' && !resized) {
      const original = pointer.before.nodes.find(item => item.id === pointer.node.id);
      for (const key of ['width', 'height']) {
        if (key in original) pointer.node[key] = original[key]; else delete pointer.node[key];
      }
    }
    const showSettings = event.type === 'pointerup' && pointer.kind === 'node' &&
      !mobileUI && Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) < 5 && matchMedia('(max-width:760px)').matches;
    const target = pointer.kind === 'pan' ? $('viewport') : pointer.handle || pointer.card;
    if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId);
    pointer = null; $('viewport').classList.remove('panning');
    if (restore) render();
    if (pendingSelectionReveal) revealSelectedNode();
    if (showSettings) { document.querySelector('.inspector').scrollIntoView({block: 'start'}); $('node-name').focus({preventScroll: true}); }
    $('undo').disabled = !past.length; $('redo').disabled = !future.length;
  }
  window.addEventListener('pointerup', endPointer);
  window.addEventListener('pointercancel', endPointer);
  document.addEventListener('keydown', event => {
    if (document.querySelector('dialog[open]:not(#codex-chat)') || event.target.closest('input, textarea, select, [contenteditable]')) return;
    if (event.key === 'Escape' && canvasExpanded) { event.preventDefault(); toggleCanvasFullscreen(); return; }
    if (event.key === 'Escape' && !$('block-library').hidden) { setLibrary(false); $('library-toggle').focus(); return; }
    if (event.key === 'Escape') { connection = null; selected = null; multiSelected.clear(); render(); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); history(event.shiftKey); }
    if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); deleteNode(); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') { event.preventDefault(); persist(true); }
  });

  // Built-in ML operations are usable immediately, without creating a custom type.
  const mlKinds = ['ml_prepare', 'ml_split', 'ml_train', 'gpu_train', 'ml_evaluate', 'ml_save'];
  for (const id of ['node-behavior', 'type-behavior']) for (const kind of mlKinds.filter(kind => Contracts.get(kind).available_for_new !== false)) {
    const option = el('option', '', Contracts.get(kind).label); option.value = kind; $(id).append(option);
  }
  function mlType(kind) {
    let type = state.types.find(t => t.behavior === kind);
    if (!type) {
      type = {id: uid(), name: Contracts.get(kind).label, description: '', color: '#275fe8', behavior: kind};
      state.types.push(type);
    }
    return type;
  }
  const blockGroups = [['Данные', ['csv', 'kaggle']], ['Обработка', ['python_code']], ['Модели', ['openrouter', 'huggingface', 'local_model', 'gpu_train']]];
  for (const [label, kinds] of blockGroups) {
    const group = el('details', 'block-category'); group.append(el('summary', '', label));
    for (const kind of kinds.filter(kind => Contracts.get(kind).available_for_new !== false)) {
      const button = el('button', 'picker-block', Contracts.get(kind).label);
      button.type = 'button'; button.dataset.mlKind = kind; button.dataset.blockSearch = Contracts.get(kind).label + ' ' + kind;
      if (kind === 'python_code') button.id = 'add-python-block';
      button.onclick = () => {
        if (state.nodes.length >= 500 || state.types.length >= 200) return toast('Достигнут лимит блоков или типов схемы.');
        commit(() => { const node = makeNode(mlType(kind)); state.nodes.push(node); selected = node.id; });
        setLibrary(false);
        $('viewport').focus({preventScroll: true});
      };
      group.append(button);
    }
    $('builtin-blocks').append(group);
  }


  function renderMLFields() {
    const kind = $('node-behavior').value;
    $('ml-fields').hidden = !mlKinds.includes(kind); $('ml-parameters').replaceChildren();
    if (!mlKinds.includes(kind)) return;
    const node = state.nodes.find(n => n.id === selected);
    const block = node?.execution.mode === kind ? Contracts.fromExecution(node.execution) : Contracts.normalize({kind, version: 1});
    for (const spec of Contracts.get(kind).settings) {
      const label = el('label', '', spec.label);
      const field = el(spec.enum ? 'select' : 'input');
      if (spec.enum) for (const value of spec.enum) { const option = el('option', '', spec.choices?.[value] || value); option.value = value; field.append(option); }
      else if (['number', 'integer'].includes(spec.type)) {
        field.type = 'number'; field.min = spec.minimum; field.max = spec.maximum; field.step = spec.type === 'integer' ? '1' : '0.05';
      } else { field.type = 'text'; field.maxLength = spec.maxLength || 4000; }
      field.dataset.setting = spec.id; field.value = block.settings[spec.id];
      label.append(field); $('ml-parameters').append(label);
    }
  }
  function readMLFields(execution) {
    const block = Contracts.fromExecution(execution);
    for (const field of $('ml-parameters').querySelectorAll('[data-setting]')) {
      const spec = Contracts.get(block.kind).settings.find(s => s.id === field.dataset.setting);
      block.settings[spec.id] = ['number', 'integer'].includes(spec.type) ? Number(field.value) : field.value;
    }
    return Contracts.toExecution(block);
  }

  function updateBehavior() {
    $('python-fields').hidden = $('node-behavior').value !== 'python_code';
    $('preview-data').hidden = !['csv', 'ml_prepare', 'python_code'].includes($('node-behavior').value);
    const enabled = $('node-behavior').value === 'openrouter';
    $('openrouter-fields').hidden = !enabled;
    const kaggle = $('node-behavior').value === 'kaggle';
    $('kaggle-fields').hidden = !kaggle;
    $('kg-dataset').disabled = $('kg-token').disabled = !kaggle;
    const hf = $('node-behavior').value === 'huggingface';
    $('hf-fields').hidden = !hf;
    for (const id of ['hf-repo', 'hf-revision', 'hf-token']) $(id).disabled = !hf;
    for (const id of ['or-model', 'or-system', 'or-prompt', 'or-max-tokens', 'or-temperature']) $(id).disabled = !enabled;
    for (const [mode, panel] of [['csv', 'csv-fields'], ['template', 'template-fields'], ['local_model', 'local-model-fields']]) {
      $(panel).hidden = $('node-behavior').value !== mode;
      $(panel).querySelectorAll('input, textarea, select').forEach(field => { field.disabled = $(panel).hidden; });
    }
    renderContract();
    renderSubgraphFields();
    renderMLFields();
  }
  $('node-behavior').onchange = updateBehavior;

  async function api(path, body) {
    if (path.startsWith('/api/pipelines/') && activeProject) body = {project_id: activeProject.meta.id, ...body};
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Architect-Request': '1', 'X-Architect-Account': account?.user?.id || '-'},
      body: JSON.stringify(path.startsWith('/api/openrouter/') ? {...body, api_key: openrouterKey} : body)});
    let data;
    try { data = await response.json(); } catch { throw new Error('Сервер вернул некорректный ответ. Перезапустите редактор.'); }
    if (!response.ok) { const error = new Error(data.error || 'Не удалось выполнить запрос.'); error.status = response.status; throw error; }
    return data;
  }

  function renderKeyStatus() {
    $('openrouter-key-status').textContent = openrouterKey ? 'Ключ задан для этой вкладки. Проверка произойдёт при запросе.' :
      serverKey ? 'Сервер настроен через OPENROUTER_API_KEY. Можно использовать его или задать свой ключ для вкладки.' : 'Ключ пока не задан.';
    $('openrouter-settings').textContent = openrouterKey || serverKey ? 'OpenRouter · ключ задан' : 'OpenRouter · ключ';
  }
  $('openrouter-settings').onclick = async () => {
    $('openrouter-key').value = '';
    renderKeyStatus();
    $('openrouter-dialog').showModal();
    try {
      const response = await fetch('/api/openrouter/status');
      if (!response.ok) throw new Error();
      serverKey = (await response.json()).server_key === true;
      renderKeyStatus();
    } catch { $('openrouter-key-status').textContent = 'Сервер подключения недоступен. Перезапустите редактор.'; }
  };
  $('close-openrouter').onclick = () => $('openrouter-dialog').close();
  $('openrouter-dialog').addEventListener('close', () => { $('openrouter-key').value = ''; });
  $('openrouter-form').onsubmit = event => {
    event.preventDefault();
    const key = $('openrouter-key').value.trim();
    if (key && !/^[!-~]{1,512}$/.test(key)) return toast('В ключе недопустимые символы.');
    if (key) openrouterKey = key;
    if (!openrouterKey && !serverKey) return toast('Вставьте API-ключ OpenRouter.');
    $('openrouter-key').value = '';
    $('openrouter-dialog').close(); renderKeyStatus(); toast('Ключ задан. Теперь можно запустить блок.');
  };
  $('forget-key').onclick = () => { openrouterKey = ''; $('openrouter-key').value = ''; renderKeyStatus(); toast(serverKey ? 'Ключ вкладки убран. Серверный ключ остаётся доступен.' : 'Ключ вкладки убран.'); };

  $('load-models').onclick = async () => {
    $('load-models').disabled = true;
    $('models-status').textContent = 'Загружаем каталог OpenRouter…';
    try {
      const data = await api('/api/openrouter/models', {});
      $('model-options').replaceChildren();
      for (const model of data.models) {
        const option = el('option'); option.value = model.id; option.label = model.name;
        $('model-options').append(option);
      }
      $('models-status').textContent = `Загружено моделей: ${data.models.length}. Начните вводить ID в поле выше.`;
    } catch (error) { $('models-status').textContent = error.message; }
    finally { $('load-models').disabled = false; }
  };

  function renderRun() {
    const run = runs.get(selected);
    $('run-result').hidden = !run;
    $('run-block').disabled = run?.pending === true;
    $('run-block').textContent = run?.pending ? 'Ожидаем ответ…' : 'Запустить блок';
    $('copy-result').hidden = !run?.data?.text;
    if (!run) return;
    $('run-status').className = run.error ? 'run-error' : run.data ? 'run-success' : '';
    const node = state.nodes.find(item => item.id === selected);
    const changed = node && JSON.stringify(node.execution) !== run.config;
    $('run-status').textContent = run.pending ? 'Запрос отправлен. Ответ может занять до 90 секунд.' : run.error ||
      (run.data.finish_reason === 'length' ? 'Ответ достиг лимита токенов и может быть неполным.' : 'Ответ получен.');
    if (changed) $('run-status').textContent += ' Настройки блока изменились после отправки.';
    $('run-output').textContent = run.data?.text || '';
    const usage = run.data?.usage || {};
    const details = [];
    if (run.data?.model) details.push(run.data.model);
    if (usage.total_tokens !== undefined) details.push(`Токенов: ${usage.total_tokens}`);
    if (usage.cost !== undefined) details.push(`Стоимость: $${usage.cost}`);
    $('run-usage').textContent = details.join(' · ');
  }
  $('run-block').onclick = async () => {
    if (runs.get(selected)?.pending || !saveNode()) return;
    const node = state.nodes.find(item => item.id === selected);
    if (!node || node.execution.mode !== 'openrouter') return;
    if (!node.execution.model.trim() || !node.execution.prompt.trim()) return toast('Укажите модель и промпт.');
    const id = node.id;
    const block = Contracts.fromExecution(node.execution);
    const run = {pending: true, config: JSON.stringify(node.execution)};
    runs.set(id, run); renderRun();
    try { run.data = (await api('/api/blocks/execute', {block, secrets: {api_key: openrouterKey}})).details; }
    catch (error) { run.error = error instanceof TypeError ? 'Соединение с сервером прервалось. Запрос мог быть обработан; автоматического повтора нет.' : error.message; }
    finally { run.pending = false; if (selected === id) renderRun(); }
  };
  $('copy-result').onclick = async () => {
    try { await navigator.clipboard.writeText(runs.get(selected)?.data?.text || ''); toast('Ответ скопирован'); }
    catch { toast('Не удалось скопировать автоматически. Выделите текст ответа вручную.'); }
  };

  function fileSize(bytes) {
    return bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(2)} ГиБ` : bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} МиБ` : bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} КиБ` : `${bytes} Б`;
  }

  function currentDataset() {
    const run = datasets.get(selected);
    return run?.source === $('kg-dataset').value.trim() ? run : null;
  }

  function renderDataset() {
    const run = currentDataset();
    const data = run?.data;
    const downloading = data?.status === 'downloading';
    $('kg-download').disabled = $('kg-files').disabled = datasets.get(selected)?.pending === true;
    $('kg-status').className = run?.error || data?.status === 'error' ? 'run-error' : 'muted';
    $('kg-status').textContent = run?.error || data?.error || (downloading ?
      `Скачано ${fileSize(data.bytes)}${data.total ? ` из ${fileSize(data.total)}` : ''}… Можно продолжать работу со схемой.` :
      run?.pending ? 'Проверяем датасет…' : data?.status === 'ready' ? `Датасет на диске · файлов: ${data.files.length} · ${fileSize(data.size)}` :
      data?.status === 'missing' ? 'Локальной копии пока нет. Нажмите «Скачать датасет».' : 'Вставьте ссылку Kaggle или owner/dataset.');
    $('kg-progress').hidden = !downloading;
    if (downloading && data.total) {
      $('kg-progress').max = data.total;
      $('kg-progress').value = data.bytes;
    } else $('kg-progress').removeAttribute('value');
    $('kg-path').textContent = data?.path || '';
    const files = data?.files || [];
    $('kg-file-label').hidden = $('kg-preview-button').hidden = !files.length;
    $('kg-file').replaceChildren();
    for (const file of files) {
      const option = el('option', '', `${file.name} · ${fileSize(file.size)}`);
      option.value = file.name;
      $('kg-file').append(option);
    }
    if (files.length) {
      if (!files.some(file => file.name === run.file)) run.file = files[0].name;
      $('kg-file').value = run.file;
    }
    $('kg-preview-button').disabled = run?.previewPending === true;
    $('kg-preview').hidden = !run?.preview && !run?.previewPending && !run?.previewError;
    $('kg-preview-title').textContent = run?.previewFile || '';
    $('kg-table').replaceChildren();
    $('kg-text').textContent = '';
    const preview = run?.preview;
    $('kg-preview-note').textContent = run?.previewError || (run?.previewPending ? 'Читаем файл…' :
      preview?.message || (preview?.kind === 'table' ? 'Первые 21 строка, до 30 столбцов.' : 'Текст в UTF-8, до 64 КиБ.'));
    if (preview?.truncated) $('kg-preview-note').textContent += ' Показана часть содержимого.';
    if (preview?.kind === 'table') {
      const table = el('table');
      for (const row of preview.rows) {
        const tr = el('tr');
        for (const cell of row) tr.append(el('td', '', cell));
        table.append(tr);
      }
      $('kg-table').append(table);
    } else if (preview?.kind === 'text') $('kg-text').textContent = preview.text;
  }

  async function loadDataset(action) {
    if (datasets.get(selected)?.pending) return;
    const token = $('kg-token').value.trim() || kaggleConnectionToken;
    if (!saveNode()) return;
    $('kg-token').value = '';
    const node = state.nodes.find(item => item.id === selected);
    if (!node || node.execution.mode !== 'kaggle') return;
    const id = node.id;
    const block = Contracts.fromExecution(node.execution);
    const run = {source: node.execution.dataset, pending: true};
    datasets.set(id, run);
    renderDataset();
    const refresh = () => { if (selected === id) renderDataset(); };
    try {
      run.data = (await api(action === 'download' ? '/api/blocks/execute' : '/api/blocks/result', {block, ...(action === 'download' ? {secrets: {token}} : {})})).details;
      refresh();
      while (run.data.status === 'downloading') {
        await new Promise(resolve => setTimeout(resolve, 1000));
        if (!state.nodes.some(item => item.id === id)) break;
        run.data = (await api('/api/blocks/result', {block})).details;
        refresh();
      }
    } catch (error) {
      run.error = error instanceof TypeError ? 'Соединение прервалось. Нажмите «Показать скачанные файлы», чтобы проверить загрузку.' : error.message;
    } finally { run.pending = false; refresh(); }
  }
  $('kg-download').onclick = () => loadDataset('download');
  $('kg-files').onclick = () => loadDataset('files');
  $('kg-dataset').oninput = renderDataset;
  $('kg-file').onchange = () => {
    const run = currentDataset();
    if (run) { run.file = $('kg-file').value; run.preview = null; run.previewError = ''; renderDataset(); }
  };
  $('kg-preview-button').onclick = async () => {
    const run = currentDataset();
    if (!run || run.previewPending || !run.file) return;
    const id = selected;
    const file = run.file;
    run.previewFile = file; run.previewPending = true; run.preview = null; run.previewError = '';
    renderDataset();
    try {
      const preview = await api('/api/kaggle/preview', {dataset: run.source, file});
      if (run.file === file) run.preview = preview;
    } catch (error) {
      if (run.file === file) run.previewError = error instanceof TypeError ? 'Не удалось связаться с локальным сервером.' : error.message;
    } finally { run.previewPending = false; if (selected === id) renderDataset(); }
  };

  function hubSource() {
    return JSON.stringify([$('hf-repo').value.trim(), $('hf-revision').value.trim() || 'main']);
  }

  function currentHubModel() {
    const run = hubModels.get(selected);
    return run?.source === hubSource() ? run : null;
  }

  function renderHubModel() {
    const run = currentHubModel();
    const data = run?.data;
    const busy = hubModels.get(selected)?.pending === true;
    const config = state.nodes.find(node => node.id === selected)?.execution;
    const sameSource = config && JSON.stringify([config.hf_repo, config.hf_revision]) === hubSource();
    const commitId = run?.info?.commit || (sameSource ? config.hf_commit : '');
    $('hf-info').disabled = busy;
    $('hf-local').disabled = busy || !commitId;
    $('hf-token-status').textContent = hubToken ? 'Токен задан' : '';
    $('hf-token-status').hidden = !hubToken;
    $('hf-model-info').textContent = run?.info ? [run.info.repo, run.info.pipeline, run.info.library,
      run.info.license && `Лицензия: ${run.info.license}`, `Версия: ${run.info.commit.slice(0, 12)}`].filter(Boolean).join(' · ') :
      commitId ? `Сохранённая версия: ${commitId.slice(0, 12)}` : '';
    $('hf-selection').hidden = !run?.info;
    $('hf-file-list').replaceChildren();
    for (const file of run?.info?.files || []) {
      const row = el('label', 'model-file');
      const checkbox = el('input');
      checkbox.type = 'checkbox'; checkbox.checked = run.chosen.has(file.name); checkbox.disabled = busy;
      checkbox.setAttribute('aria-label', file.name);
      checkbox.onchange = () => {
        if (checkbox.checked) run.chosen.add(file.name); else run.chosen.delete(file.name);
        renderHubSelection();
      };
      row.append(checkbox, el('span', '', file.name), el('small', '', fileSize(file.size)));
      $('hf-file-list').append(row);
    }
    renderHubSelection();
    const downloading = data?.status === 'downloading';
    $('hf-status').className = run?.error || data?.error ? 'run-error' : 'muted';
    $('hf-status').textContent = run?.error || data?.error || (downloading ?
      `Скачано ${fileSize(data.bytes)}${data.total ? ` из ${fileSize(data.total)}` : ''} · ${data.current_file || 'Проверяем файлы…'}` :
      run?.pending ? 'Обращаемся к Hugging Face…' : data?.status === 'ready' ? `На диске файлов: ${data.files.length}. Сохранены только выбранные файлы.` :
      data?.status === 'missing' ? 'Файлы этой версии ещё не скачаны.' : run?.info ? 'Выберите нужные файлы весов, конфигурации и токенизатора.' : 'Укажите модель и загрузите список файлов.');
    $('hf-progress').hidden = !downloading;
    if (downloading && data.total) { $('hf-progress').max = data.total; $('hf-progress').value = data.bytes; }
    else $('hf-progress').removeAttribute('value');
    $('hf-path').textContent = data?.path || '';
    $('hf-local-files').replaceChildren();
    for (const file of data?.files || []) $('hf-local-files').append(el('li', '', `${file.name} · ${fileSize(file.size)}`));
  }

  function renderHubSelection() {
    const run = currentHubModel();
    const chosen = (run?.info?.files || []).filter(file => run.chosen.has(file.name));
    const size = chosen.reduce((total, file) => total + file.size, 0);
    const busy = hubModels.get(selected)?.pending === true;
    $('hf-selected-size').textContent = `Выбрано: ${chosen.length} · ${fileSize(size)}${size > 32 * 1024 ** 3 ? ' — превышен лимит 32 ГиБ' : ''}`;
    $('hf-download').disabled = busy || !chosen.length || size > 32 * 1024 ** 3;
    $('hf-select-all').disabled = $('hf-select-none').disabled = busy;
  }

  async function hubAction(action) {
    if (hubModels.get(selected)?.pending) return;
    const supplied = $('hf-token').value.trim();
    if (supplied) hubToken = supplied;
    if (!saveNode()) return;
    $('hf-token').value = '';
    const node = state.nodes.find(item => item.id === selected);
    if (!node || node.execution.mode !== 'huggingface') return;
    const id = node.id, config = clone(node.execution);
    let run = currentHubModel();
    if (!run || action === 'info') {
      run = {source: hubSource(), chosen: new Set(config.hf_files)};
      hubModels.set(id, run);
    }
    run.pending = true; run.error = '';
    renderHubModel();
    const refresh = () => { if (selected === id) renderHubModel(); };
    try {
      if (action === 'info') {
        const info = await api('/api/huggingface/info', {repo: config.hf_repo, revision: config.hf_revision, token: hubToken});
        run.info = info;
        run.chosen = new Set(info.commit === config.hf_commit ? config.hf_files.filter(name => info.files.some(file => file.name === name)) : []);
        const current = state.nodes.find(item => item.id === id);
        if (current && current.execution.hf_repo === config.hf_repo && current.execution.hf_revision === config.hf_revision) {
          commit(() => { current.execution.hf_commit = info.commit; current.execution.hf_files = [...run.chosen]; });
        }
      } else {
        const commitId = run.info?.commit || config.hf_commit;
        const block = Contracts.fromExecution({...config, hf_commit: commitId, hf_files: [...run.chosen]});
        run.data = (await api(action === 'download' ? '/api/blocks/execute' : '/api/blocks/result', {block,
          ...(action === 'download' ? {secrets: {token: hubToken}} : {})})).details;
        refresh();
        while (run.data.status === 'downloading') {
          await new Promise(resolve => setTimeout(resolve, 1000));
          if (!state.nodes.some(item => item.id === id)) break;
          run.data = (await api('/api/blocks/result', {block})).details;
          refresh();
        }
      }
    } catch (error) {
      run.error = error instanceof TypeError ? 'Соединение с сервером прервалось. Проверьте локальные файлы, чтобы узнать результат загрузки.' : error.message;
    } finally { run.pending = false; refresh(); }
  }

  $('hf-info').onclick = () => hubAction('info');
  $('hf-download').onclick = () => hubAction('download');
  $('hf-local').onclick = () => hubAction('status');
  $('hf-forget-token').onclick = () => { hubToken = ''; $('hf-token').value = ''; renderHubModel(); };
  $('hf-repo').oninput = $('hf-revision').oninput = renderHubModel;
  $('hf-select-all').onclick = () => {
    const run = currentHubModel();
    if (run?.info) { run.chosen = new Set(run.info.files.map(file => file.name)); renderHubModel(); }
  };
  $('hf-select-none').onclick = () => {
    const run = currentHubModel();
    if (run) { run.chosen.clear(); renderHubModel(); }
  };

  async function prepareDiagram(raw) {
    if (raw?.version === 4 || raw?.definitions?.length) {
      const prepared = await api('/api/subgraphs/normalize', {diagram: raw});
      Contracts.install(prepared.contracts);
      return validate(prepared.diagram);
    }
    return validate(raw);
  }

  function downloadJSON(value, name) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], {type: 'application/json'}));
    const link = el('a'); link.href = url; link.download = name + '.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function draftKey(project) { return STORAGE_KEY + '.project.' + project.meta.id; }
  function cacheProjectDraft() {
    if (runView) return;
    if (!activeProject) return;
    try {
      localStorage.setItem(draftKey(activeProject), JSON.stringify({diagram: serializable(), revision: activeProject.meta.revision,
        description: activeProject.description, name: activeProject.meta.name, project: activeProject.meta, saved: !activeProject.dirty, research: activeProject.meta.research, researchDirty: activeProject.researchDirty}));
      return true;
    } catch { $('save-status').textContent = 'Не удалось создать локальную резервную копию'; return false; }
  }

  async function flushProject() {
    if (runView) return;
    clearTimeout(projectSaveTimer);
    if (!activeProject) return;
    if (projectSavePromise) { await projectSavePromise; if (activeProject?.dirty) return flushProject(); return; }
    const session = activeProject;
    if (session.conflict) throw new Error('Проект изменён в другой вкладке. Сохраните свой вариант как новый проект или откройте сохранённую версию.');
    if (!session.dirty) return;
    projectSavePromise = (async () => {
      while (session === activeProject && session.dirty) {
        const diagram = serializable(), description = session.description, name = session.meta.name;
        const research = session.researchDirty ? structuredClone(session.meta.research) : null;
        $('save-status').textContent = 'Сохраняется…';
        try {
          const result = await api('/api/projects/save', {project_id: session.meta.id, revision: session.meta.revision, name, description, diagram, ...(research ? {research} : {})});
          if (session !== activeProject) return;
          const pendingResearch = session.meta.research;
          session.researchDirty = !!session.researchDirty && JSON.stringify(research) !== JSON.stringify(pendingResearch);
          session.meta = {...result.project, name: session.meta.name, ...(session.researchDirty ? {research: pendingResearch} : {})};
          session.dirty = session.researchDirty || JSON.stringify(diagram) !== JSON.stringify(serializable()) || description !== session.description || name !== session.meta.name;
          unsaved = session.dirty;
          cacheProjectDraft();
          $('save-status').textContent = session.dirty ? 'Сохраняется…' : 'Сохранено';
          renderProjectStatus();
        } catch (error) {
          if (session === activeProject) {
            session.conflict = error.status === 409; unsaved = true; cacheProjectDraft();
            $('save-status').textContent = session.conflict ? 'Проект изменён в другой вкладке' : 'Не удалось сохранить проект';
          }
          throw error;
        }
      }
    })();
    try { await projectSavePromise; } finally { projectSavePromise = null; }
  }

  function diagramFromRun(record) {
    if (record.editor_diagram) return {diagram: record.editor_diagram, arranged: false};
    if (record.source_diagram?.types) return {diagram: record.source_diagram, arranged: false};
    const source = record.diagram;
    if (!source?.nodes?.length || !Array.isArray(source.edges)) throw new Error('Схема этого запуска не сохранилась.');
    // Legacy runs contain exact executable blocks/settings but no editor layout.
    const types = [], kinds = new Map();
    for (const node of source.nodes) if (!kinds.has(node.block.kind)) {
      const type = {id: uid(), name: Contracts.get(node.block.kind).label, description: '', color: '#5368e8',
        block: {kind: node.block.kind, version: node.block.version}};
      types.push(type); kinds.set(node.block.kind, type.id);
    }
    return {arranged: true, diagram: {format: 'architect', version: 3, name: record.name || source.name || 'Схема запуска',
      types, edges: clone(source.edges), nodes: source.nodes.map((node, index) => ({...clone(node),
        typeId: kinds.get(node.block.kind), description: '', x: (index % 4) * 300, y: Math.floor(index / 4) * 240}))}};
  }

  async function openRunDiagram(id) {
    const request = ++runViewRequest, project = activeProject;
    if (selected && !saveNode()) return;
    await flushProject();
    const record = await api('/api/pipelines/run', {run_id: id});
    const snapshot = diagramFromRun(record), next = await prepareDiagram(snapshot.diagram);
    if (request !== runViewRequest || project !== activeProject) return;
    await flushProject();
    if (request !== runViewRequest || project !== activeProject) return;
    if (!runView) runView = {current: {state, past, future, selected, multiSelected, connection, camera, pipelineRun}};
    runView.record = record;
    clearTimeout(pipelineTimer); ++historyRequest; ++stepRequest;
    state = next; past = []; future = []; selected = null; multiSelected = new Set(); connection = null;
    pipelineRun = record; pipelineStep = null; pipelineHistoryLoading = false;
    if ($('codex-chat').open) $('codex-chat-close').click();
    setLibrary(false);
    document.body.classList.add('run-view');
    $('run-view-actions').hidden = false;
    $('run-view-label').textContent = `Просмотр запуска · ${new Date(record.created_at).toLocaleString('ru-RU')}` +
      (snapshot.arranged ? ' · расположение восстановлено' : '');
    $('schema-tab').click();
    render(); fit(true);
    $('viewport').focus({preventScroll: true});
  }

  function leaveRunDiagram() {
    ++runViewRequest;
    if (!runView) return;
    const current = runView.current;
    ({state, past, future, selected, multiSelected, connection, camera, pipelineRun} = current);
    runView = null; pipelineStep = null; pipelineHistoryLoading = false;
    document.body.classList.remove('run-view');
    $('run-view-actions').hidden = true;
    render(); fit(true); schedulePipelinePoll();
  }
  $('run-view-return').onclick = leaveRunDiagram;
  $('run-view-log').onclick = async () => {
    if (!runView) return;
    $('pipeline-dialog').showModal();
    try { await loadPipelineHistory(runView.record.id); }
    catch (error) { $('pipeline-summary').textContent = error.message; }
  };
  // Navigation returns to the real project before any action can save or launch it.
  document.addEventListener('click', event => {
    if (runView && event.target.closest('.app-sidebar button, .project-tabs button:not(#schema-tab), #mobile-menu')) leaveRunDiagram();
  }, true);

  function renderProjectStatus() {
    community?.refreshProject();
    window.dispatchEvent(new Event('architect-project-change'));
    $('project-status').textContent = activeProject ? `Проект: ${activeProject.meta.name}` : 'Новая схема';
  }

  async function adoptProject(result, recover = false) {
    clearTimeout(projectSaveTimer); clearTimeout(pipelineTimer);
    ++historyRequest; ++stepRequest;
    Contracts.install(result.contracts);
    const next = validate(result.diagram);
    activeProject = {meta: result.project, description: result.description, dirty: false, conflict: false};
    state = next; selected = null; multiSelected.clear(); connection = null; past = []; future = [];
    pipelineRun = null; activePipeline = null; pipelineList = []; pipelineHistoryLoading = false; pipelineStep = null;
    runs.clear(); datasets.clear(); hubModels.clear(); unsaved = false;
    try { localStorage.setItem(ACTIVE_PROJECT_KEY, result.project.id); } catch {}
    const projectURL = new URL(location.href); projectURL.searchParams.set('project', result.project.id);
    window.history.replaceState(null, '', projectURL);
    $('save-status').textContent = 'Сохранено';
    if (recover) {
      try {
        const draft = JSON.parse(localStorage.getItem(draftKey(activeProject)) || 'null');
        if (draft && !draft.saved) {
          state = await prepareDiagram(draft.diagram);
          activeProject.description = draft.description; activeProject.meta.name = draft.name;
          if (draft.researchDirty) { activeProject.meta.research = draft.research; activeProject.researchDirty = true; }
          activeProject.dirty = true; activeProject.conflict = draft.revision !== result.project.revision; unsaved = true;
          $('save-status').textContent = activeProject.conflict ? 'Восстановленные изменения отличаются от сохранённого проекта' : 'Восстановлены несохранённые изменения';
          toast('Восстановлены несохранённые изменения. Сохраните их или откройте сохранённую версию через «+ → Каталог проектов».');
        }
      } catch (error) { toast('Не удалось восстановить изменения: ' + error.message); }
    }
    cacheProjectDraft();
    render(); renderProjectStatus(); fit(true);
    await loadPipelineHistory();
  }

  async function openProject(id, recover = false) {
    await adoptProject(await api('/api/projects/get', {project_id: id}), recover);
  }

  let catalogRequest = 0, catalogProjects = [], openingProject = false;
  let datasetGeneration = 0, savedDatasets = [], datasetsTruncated = false;
  function selectPickerMode(mode) {
    hideProjectPreview();
    pickerQueries[pickerSearchKey()] = $('block-search').value;
    pickerMode = mode; $('picker-mode').value = mode;
    ++catalogRequest; ++datasetGeneration; ++globalGeneration; clearTimeout(globalSearchTimer);
    document.querySelector('.block-picker-tabs').hidden = mode !== 'blocks';
    for (const name of ['local', 'community', 'global']) $('blocks-' + name).hidden = mode !== 'blocks' || pickerTab !== name;
    $('picker-data').hidden = mode !== 'data'; $('projects-dialog').hidden = mode !== 'projects';
    $('block-search').value = pickerQueries[pickerSearchKey()] || '';
    if (mode === 'blocks') selectPickerTab(pickerTab);
    else {
      $('block-search').placeholder = mode === 'projects' ? 'Найти проект' : 'Найти файл или датасет';
      $('block-search').setAttribute('aria-label', $('block-search').placeholder);
      if (mode === 'projects') refreshProjectList(); else loadDatasets();
    }
  }
  $('picker-mode').onchange = () => selectPickerMode($('picker-mode').value);
  document.addEventListener('open-project-catalog', () => {
    if (!window.WorkspaceNavigation.leave() || (selected && !saveNode())) return;
    pickerQueries[pickerSearchKey()] = $('block-search').value;
    pickerMode = 'projects'; $('block-search').value = pickerQueries.projects || ''; setLibrary(true);
  });
  async function refreshProjectList() {
    hideProjectPreview(); projectRunCache.clear();
    const request = ++catalogRequest;
    catalogProjects = []; $('project-list').replaceChildren(); $('project-retry').hidden = true;
    $('project-message').textContent = 'Загружаем проекты…';
    try {
      const data = await api('/api/projects/list', {});
      if (request !== catalogRequest || $('block-library').hidden) return;
      catalogProjects = data.projects; renderProjectList();
    } catch (error) {
      if (request !== catalogRequest || $('block-library').hidden) return;
      $('project-message').textContent = error.message; $('project-retry').hidden = false;
    }
  }
  const projectPreview = el('div', 'project-preview');
  projectPreview.id = 'project-preview'; projectPreview.setAttribute('role', 'tooltip'); projectPreview.setAttribute('aria-live', 'polite'); projectPreview.hidden = true;
  document.body.append(projectPreview);
  const projectRunCache = new Map();
  let previewAnchor = null, previewRequest = 0, previewTimer, previewDismissTimer;
  function hideProjectPreview() {
    ++previewRequest; clearTimeout(previewTimer); clearTimeout(previewDismissTimer);
    previewAnchor?.removeAttribute('aria-describedby'); previewAnchor = null; projectPreview.hidden = true;
  }
  function positionProjectPreview() {
    if (!previewAnchor || projectPreview.hidden) return;
    const anchor = previewAnchor.getBoundingClientRect(), card = projectPreview.getBoundingClientRect();
    const panel = $('block-library').getBoundingClientRect(), gap = 8;
    let left = panel.right + gap, top = anchor.top;
    if (left + card.width > innerWidth - gap) {
      left = panel.left - card.width - gap;
      if (left < gap) { left = gap; top = anchor.bottom + gap; if (top + card.height > innerHeight - gap) top = anchor.top - card.height - gap; }
    }
    projectPreview.style.left = Math.max(gap, Math.min(left, innerWidth - card.width - gap)) + 'px';
    projectPreview.style.top = Math.max(gap, Math.min(top, innerHeight - card.height - gap)) + 'px';
  }
  function previewDate(value) {
    const date = value ? new Date(value) : null;
    return date && Number.isFinite(date.getTime()) ? date.toLocaleString('ru-RU') : '';
  }
  function previewDetails(project, run) {
    const title = el('strong', 'project-preview-title', project.name);
    projectPreview.replaceChildren(title);
    const status = el('p', 'project-preview-status');
    if (!run) status.textContent = 'Запусков пока нет';
    else {
      const labels = {ready: 'Успешно завершён', error: 'Ошибка', running: 'Выполняется', waiting: 'В очереди', pending: 'Ожидает шага', paused: 'Ожидает продолжения', cancelled: 'Остановлен', skipped: 'Пропущен'};
      status.textContent = 'Последний запуск: ' + (labels[run.status] || 'Статус неизвестен');
      status.dataset.status = run.status;
    }
    projectPreview.append(status);
    const facts = el('dl', 'project-preview-facts');
    const fact = (label, value) => { if (value) facts.append(el('dt', '', label), el('dd', '', value)); };
    if (run) {
      fact('Начало', previewDate(run.created_at)); fact('Окончание', previewDate(run.finished_at));
      if (previewDate(run.created_at) && previewDate(run.finished_at)) {
        const seconds = Math.max(0, Math.round((new Date(run.finished_at) - new Date(run.created_at)) / 1000));
        fact('Длительность', seconds >= 60 ? Math.floor(seconds / 60) + ' мин ' + seconds % 60 + ' с' : seconds + ' с');
      }
    }
    fact('Проект изменён', previewDate(project.updated_at));
    projectPreview.append(facts); positionProjectPreview();
  }
  async function showProjectPreview(project, button) {
    hideProjectPreview();
    if ($('block-library').hidden || pickerMode !== 'projects' || !button.isConnected) return;
    previewAnchor = button; const request = ++previewRequest;
    button.setAttribute('aria-describedby', projectPreview.id);
    projectPreview.replaceChildren(el('strong', 'project-preview-title', project.name), el('p', '', 'Загружаем сведения о запуске…'));
    projectPreview.hidden = false; positionProjectPreview();
    try {
      let cached = projectRunCache.get(project.id);
      if (!cached || cached.expires < Date.now()) {
        cached = {expires: Date.now() + 10000, promise: api('/api/pipelines/runs', {project_id: project.id})};
        projectRunCache.set(project.id, cached);
      }
      const data = await cached.promise;
      if (request !== previewRequest || previewAnchor !== button || !button.isConnected) return;
      previewDetails(project, data.runs[0] || null);
    } catch (_) {
      projectRunCache.delete(project.id);
      if (request !== previewRequest || previewAnchor !== button) return;
      projectPreview.replaceChildren(el('strong', 'project-preview-title', project.name), el('p', '', 'Не удалось загрузить сведения о запуске. Наведите на проект ещё раз, чтобы повторить.'));
      positionProjectPreview();
    }
  }
  function dismissProjectPreview() {
    clearTimeout(previewTimer); clearTimeout(previewDismissTimer);
    if (previewAnchor === document.activeElement && previewAnchor?.matches(':focus-visible')) return;
    previewDismissTimer = setTimeout(hideProjectPreview, 150);
  }
  projectPreview.addEventListener('pointerenter', () => clearTimeout(previewDismissTimer));
  projectPreview.addEventListener('pointerleave', dismissProjectPreview);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !projectPreview.hidden) { event.preventDefault(); event.stopImmediatePropagation(); hideProjectPreview(); }
  }, true);
  window.addEventListener('resize', hideProjectPreview);
  document.addEventListener('scroll', event => { if (!projectPreview.contains(event.target)) hideProjectPreview(); }, true);
  function renderProjectList() {
    hideProjectPreview();
    const list = $('project-list'); list.replaceChildren();
    const query = normalizeSearch($('block-search').value);
    const projects = catalogProjects.filter(item => normalizeSearch(item.name).includes(query));
    $('project-message').textContent = !catalogProjects.length ? 'Сохранённых проектов пока нет.' : !projects.length ? 'Ничего не найдено.' : '';
    for (const project of projects) {
      const row = el('div', 'picker-project'); row.dataset.projectId = project.id;
      const name = el('button', 'picker-project-name', project.name);
      name.disabled = openingProject; name.onclick = () => openCatalogProject(project.id);
      name.addEventListener('pointerenter', event => {
        if (event.pointerType === 'touch') return;
        clearTimeout(previewDismissTimer); clearTimeout(previewTimer);
        if (previewAnchor === name && !projectPreview.hidden) return;
        hideProjectPreview(); previewTimer = setTimeout(() => showProjectPreview(project, name), 180);
      });
      name.addEventListener('pointerleave', dismissProjectPreview);
      name.addEventListener('focus', () => { if (name.matches(':focus-visible')) showProjectPreview(project, name); });
      name.addEventListener('blur', dismissProjectPreview);
      row.append(name); list.append(row);
    }
  }
  async function openCatalogProject(id) {
    if (openingProject) return;
    if (selected && !saveNode()) return;
    if (activeProject?.dirty && !confirm('Открыть сохранённую версию? Несохранённые изменения останутся доступны для восстановления.')) return;
    openingProject = true; renderProjectList();
    try {
      if (projectSavePromise) await projectSavePromise.catch(() => {});
      await openProject(id); setLibrary(false);
    } catch (error) { $('project-message').textContent = error.message; }
    finally {
      openingProject = false;
      for (const button of $('project-list').querySelectorAll('button')) button.disabled = false;
    }
  }
  $('project-retry').onclick = refreshProjectList;
  async function loadDatasets() {
    const request = ++datasetGeneration;
    savedDatasets = []; $('dataset-list').replaceChildren(); $('dataset-retry').hidden = true;
    $('dataset-status').textContent = 'Загружаем данные…';
    try {
      const result = await api('/api/data/catalog', {});
      if (request !== datasetGeneration || $('block-library').hidden) return;
      savedDatasets = result.datasets; datasetsTruncated = result.truncated; renderDatasetList();
    } catch (error) {
      if (request !== datasetGeneration || $('block-library').hidden) return;
      $('dataset-status').textContent = error.message; $('dataset-retry').hidden = false;
    }
  }
  function renderDatasetList() {
    const query = normalizeSearch($('block-search').value), list = $('dataset-list'); list.replaceChildren();
    let count = 0;
    for (const category of ['Загруженные CSV', 'Датасеты Kaggle']) {
      const items = savedDatasets.filter(item => item.category === category && normalizeSearch(category + ' ' + item.name + ' ' + item.files.join(' ')).includes(query));
      if (!items.length) continue;
      const group = el('details', 'block-category'); group.open = !!query; group.append(el('summary', '', category));
      for (const item of items) {
        const folder = el('details', 'block-category dataset-folder'); folder.open = !!query;
        folder.append(el('summary', '', item.name));
        if (!item.files.length) folder.append(el('p', 'muted', 'В датасете нет CSV-файлов.'));
        for (const file of item.files) {
          const add = el('button', '', file); add.title = 'Добавить чтение ' + file;
          add.onclick = () => {
            if (selected && !saveNode()) return;
            if (state.nodes.length >= 500 || state.types.length >= 200) return toast('Достигнут лимит блоков или типов схемы.');
            commit(() => {
              const node = makeNode(mlType('csv')); node.name = file;
              node.execution = Contracts.toExecution({kind: 'csv', version: 1, inputs: {dataset: item.artifact, file}, settings: {delimiter: item.delimiter || ','}});
              state.nodes.push(node); selected = node.id;
            });
            setLibrary(false); $('viewport').focus({preventScroll: true});
          };
          folder.append(add);
        }
        group.append(folder); count++;
      }
      list.append(group);
    }
    $('dataset-status').textContent = !savedDatasets.length ? 'Сохранённых данных пока нет.' : !count ? 'Ничего не найдено.' : datasetsTruncated ? 'Показана часть сохранённых данных.' : '';
  }
  $('dataset-retry').onclick = loadDatasets;
  const wizard=window.ExperimentWizard({api,adopt:adoptProject,
    beforeCreate:async()=>{if(selected&&!saveNode())throw new Error('Проверьте настройки открытого блока.');await flushProject();},
    launch:()=> $('run-pipeline').click()});
  $('welcome-experiment').onclick=$('experiment-wizard-open').onclick=()=>{
    setLibrary(false);wizard.open().catch(e=>toast(e.message));
  };

  function syncCustomOptions() {
    for (const id of ['node-behavior', 'type-behavior']) {
      const value = $(id).value;
      $(id).querySelectorAll('option[data-custom], option[data-existing]').forEach(option => option.remove());
      const current = id === 'node-behavior' ? state.nodes.find(node => node.id === selected)?.execution.mode : null;
      if (current && Contracts.get(current).available_for_new === false) {
        const option = el('option', '', Contracts.get(current).label);
        option.value = current; option.dataset.existing = '1'; $(id).append(option);
      }
      for (const definition of state.definitions || []) {
        const option = el('option', '', definition.name + ' · подсхема');
        option.value = definition.kind; option.dataset.custom = '1'; $(id).append(option);
      }
      $(id).value = value;
    }
  }

  function renderSubgraphFields() {
    const kind = $('node-behavior').value;
    const custom = kind.startsWith('subgraph_');
    $('subgraph-fields').hidden = !custom;
    $('subgraph-parameters').replaceChildren();
    if (!custom) return;
    const node = state.nodes.find(n => n.id === selected);
    const block = node?.execution.mode === kind ? Contracts.fromExecution(node.execution) : Contracts.normalize({kind, version: 1});
    $('subgraph-version').textContent = 'Версия содержимого: ' + kind.slice(9, 21);
    for (const section of ['inputs', 'settings']) for (const spec of Contracts.get(kind)[section]) {
      const connected = section === 'inputs' && state.edges.some(e => e.kind === 'data' && e.to === selected && e.toPort === spec.id);
      const label = el('label', '', spec.label + (connected ? ' · из связи' : ''));
      const field = el('textarea'); field.rows = 2; field.dataset.section = section; field.dataset.port = spec.id;
      const value = block[section][spec.id];
      field.value = value === undefined ? '' : ['text', 'string'].includes(spec.type) ? value : JSON.stringify(value);
      field.disabled = connected; field.placeholder = ['text', 'string'].includes(spec.type) ? 'Текст' : 'Значение в JSON';
      label.append(field); $('subgraph-parameters').append(label);
    }
  }

  function readSubgraphFields(kind) {
    const block = Contracts.normalize({kind, version: 1});
    for (const field of $('subgraph-parameters').querySelectorAll('textarea')) {
      if (field.disabled) continue;
      const spec = Contracts.get(kind)[field.dataset.section].find(p => p.id === field.dataset.port);
      if (!field.value.trim() && !['text', 'string'].includes(spec.type)) { delete block[field.dataset.section][spec.id]; continue; }
      block[field.dataset.section][spec.id] = ['text', 'string'].includes(spec.type) ? field.value : JSON.parse(field.value);
    }
    return Contracts.toExecution(block);
  }

  let packingSelection = [];
  $('pack-subgraph').onclick = () => {
    if (selected && !saveNode()) return;
    packingSelection = [...new Set([...multiSelected, ...(selected ? [selected] : [])])].filter(id => state.nodes.some(n => n.id === id));
    if (!packingSelection.length) return toast('Выберите блоки: Shift + клик добавляет блок к выделению.');
    const chosen = new Set(packingSelection);
    $('subgraph-name').value = 'Моя подсхема'; $('subgraph-description').value = ''; $('subgraph-error').textContent = '';
    $('subgraph-port-names').replaceChildren();
    for (const node of state.nodes.filter(n => chosen.has(n.id))) {
      for (const section of ['inputs', 'outputs', 'settings']) for (const spec of Contracts.get(node.execution.mode)[section]) {
        if (section === 'settings' && node.execution.mode === 'python_code' && spec.id === 'code') continue;
        if (section === 'inputs' && state.edges.some(e => e.kind === 'data' && e.to === node.id && e.toPort === spec.id && chosen.has(e.from))) continue;
        if (section === 'outputs') {
          const edges = state.edges.filter(e => e.kind === 'data' && e.from === node.id && e.fromPort === spec.id);
          if (edges.length && edges.every(e => chosen.has(e.to))) continue;
        }
        const label = el('label', '', `${{inputs: 'Вход', outputs: 'Выход', settings: 'Настройка'}[section]} · ${spec.type}`);
        const input = el('input'); input.maxLength = 200; input.required = true;
        input.dataset.binding = `${section}:${node.id}:${spec.id}`; input.value = node.name + ' · ' + spec.label;
        label.append(input); $('subgraph-port-names').append(label);
      }
    }
    $('subgraph-dialog').showModal();
  };
  $('close-subgraph').onclick = () => $('subgraph-dialog').close();
  $('subgraph-form').onsubmit = async event => {
    event.preventDefault();
    const button = $('subgraph-form').querySelector('button[type=submit]'); button.disabled = true;
    const original = JSON.stringify(state);
    try {
      const labels = Object.fromEntries([...$('subgraph-port-names').querySelectorAll('input')].map(input => [input.dataset.binding, input.value]));
      const result = await api('/api/subgraphs/pack', {diagram: serializable(), selected: packingSelection,
        name: $('subgraph-name').value.trim(), description: $('subgraph-description').value, labels});
      Contracts.install(result.contracts); const next = validate(result.diagram);
      await registerPersonalBlock(result.diagram, next.nodes.find(node => node.id === result.node_id).typeId);
      if (JSON.stringify(state) !== original || runView) throw new Error('Схема изменилась. Созданный блок доступен в «Личном».');
      commit(() => { state = next; selected = result.node_id; multiSelected.clear(); connection = null; });
      $('subgraph-dialog').close(); fit(); toast('Подсхема добавлена в каталог. Её можно экспортировать в другой проект.');
    } catch (error) { $('subgraph-error').textContent = error.message; }
    finally { button.disabled = false; }
  };

  function exportSubgraph(kind) {
    const found = new Map((state.definitions || []).map(d => [d.kind, d])), needed = new Set();
    const visit = key => { if (needed.has(key) || !found.has(key)) return; needed.add(key); for (const node of found.get(key).graph.nodes) visit(node.block.kind); for (const type of found.get(key).graph.types) visit(type.block.kind); };
    visit(kind);
    downloadJSON({format: 'architect.block-package', version: 1, kind, definitions: [...needed].map(key => found.get(key))}, 'subgraph-' + kind.slice(9, 21));
  }
  async function importSubgraphPackage(value, addToCanvas = false) {
      if (state.types.length >= 200 || (addToCanvas && state.nodes.length >= 500)) throw new Error('Достигнут лимит блоков или типов схемы.');
      if (value.format !== 'architect.block-package' || value.version !== 1 || !Array.isArray(value.definitions)) throw new Error('Некорректный пакет блока.');
      const definitions = new Map((state.definitions || []).map(d => [d.kind, d]));
      for (const d of value.definitions) definitions.set(d.kind, d);
      const root = definitions.get(value.kind); if (!root) throw new Error('В пакете отсутствует основной блок.');
      const diagram = serializable(); diagram.definitions = [...definitions.values()]; diagram.version = 4;
      diagram.types.push({id: uid(), name: root.name, description: root.description, color: '#6366f1', block: {kind: root.kind, version: 1}});
      const next = await prepareDiagram(diagram);
      commit(() => {
        state = next;
        if (addToCanvas) { const node = makeNode(state.types[state.types.length - 1]); state.nodes.push(node); selected = node.id; }
      });
      if (addToCanvas) { setLibrary(false); $('viewport').focus({preventScroll: true}); }
      toast(addToCanvas ? 'Блок добавлен на схему' : 'Блок импортирован в каталог проекта');
  }
  $('import-subgraph').onclick = () => $('subgraph-file').click();
  $('subgraph-file').onchange = async () => {
    const file = $('subgraph-file').files[0]; $('subgraph-file').value = '';
    if (!file) return;
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error('Блок больше лимита 4 МиБ.');
      const value = JSON.parse(await file.text());
      await importSubgraphPackage(value, true);
    } catch (error) { toast(error.message); }
  };
  $('unpack-subgraph').onclick = async () => {
    if (!saveNode()) return;
    try {
      const result = await api('/api/subgraphs/unpack', {diagram: serializable(), node_id: selected});
      const next = await prepareDiagram(result.diagram);
      commit(() => { state = next; selected = null; multiSelected.clear(); connection = null; });
      fit(); toast('Подсхема развёрнута. После редактирования создайте новую версию через выделение.');
    } catch (error) { toast(error.message); }
  };

  function groupStatus(nodeId) {
    const ids = pipelineRun.groups?.[nodeId];
    if (!ids) return pipelineRun.nodes[nodeId];
    const steps = ids.filter(id => pipelineRun.diagram.nodes.find(node => node.id === id)?.block.kind !== 'note')
      .map(id => pipelineRun.nodes[id]).filter(Boolean);
    const status = ['error', 'running', 'waiting', 'pending', 'cancelled'].find(s => steps.some(step => step.status === s)) ||
      (steps.length && steps.every(step => step.status === 'ready') ? 'ready' : 'skipped');
    return {status, error: steps.find(step => step.error)?.error, reused_from: steps.length && steps.every(step => step.reused_from) ? steps[0].reused_from : null};
  }

  function pipelineSignature(diagram) {
    const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object' ?
      Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
    return JSON.stringify(stable({nodes: diagram.nodes.map(node => ({id: node.id, name: node.name, block: node.block})),
      edges: diagram.edges.map(edge => Object.fromEntries(['id', 'from', 'to', 'fromPort', 'toPort', 'kind'].map(key => [key, edge[key]])))}));
  }

  function renderPipeline() {
    const same = pipelineRun && pipelineSignature(serializable()) === pipelineSignature(pipelineRun.source_diagram || pipelineRun.diagram);
    const executable = serializable().nodes.some(node => node.block && node.block.kind !== 'note');
    $('run-pipeline').disabled = !!activePipeline || pipelineStarting || !executable;
    $('compute-target').disabled = pipelineStarting;
    $('run-pipeline').setAttribute('aria-busy', String(pipelineStarting));
    $('history-training').disabled = !pipelineRun;
    $('debug-pipeline').disabled = $('debug-node-open').disabled = !!activePipeline || pipelineStarting;
    const waiting = activePipeline?.status === 'waiting';
    const ahead = activePipeline?.queue_ahead;
    const liveStatus = activePipeline?.cancel_requested ? 'Остановка запрошена…' :
      waiting ? `В очереди${Number.isInteger(ahead) ? ` · перед вами ${ahead}` : ''}` : 'Выполняется';
    $('pipeline-live').hidden = !activePipeline;
    $('pipeline-live-status').textContent = activePipeline ? liveStatus : '';
    for (const id of ['cancel-pipeline', 'cancel-pipeline-live']) {
      $(id).textContent = waiting ? 'Отменить запуск' : 'Остановить';
      $(id).disabled = !!activePipeline?.cancel_requested;
    }
    $('cancel-pipeline').hidden = !activePipeline;
    $('pipeline-status').textContent = activePipeline ? liveStatus :
      pipelineRun ? `Запуск: ${pipelineLabels[pipelineRun.status]}` : 'Готов к запуску';
    if (pipelineRun && !same) $('pipeline-status').textContent += ' · показана другая версия схемы';
    window.dispatchEvent(new Event('architect-run-change'));
    for (const card of $('nodes').children) {
      card.querySelector('.pipeline-badge')?.remove();
      const step = same ? groupStatus(card.dataset.id) : null;
      card.dataset.runStatus = step?.status || '';
      if (step) {
        const badge = el('span', 'pipeline-badge', step.reused_from ? 'Готово · из истории' : pipelineLabels[step.status]);
        badge.title = step.error || (step.reused_from ? 'Результат из запуска ' + step.reused_from : `Запуск ${pipelineRun.created_at}`);
        card.append(badge);
      }
    }
    if (!$('pipeline-dialog').open) return;
    $('pipeline-summary').textContent = pipelineRun ? `${pipelineRun.name} · ${pipelineLabels[pipelineRun.status]} · ${new Date(pipelineRun.created_at).toLocaleString()}${pipelineRun.error ? '\n' + pipelineRun.error : ''}` : 'Запусков пока нет.';
    $('pipeline-steps').replaceChildren();
    for (const id of pipelineRun?.order || []) {
      const step = pipelineRun.nodes[id];
      const button = el('button', id === pipelineStep ? 'selected-step' : '', `${step.name} · ${pipelineLabels[step.status]}`);
      button.disabled = pipelineHistoryLoading;
      button.dataset.nodeId = id;
      button.onclick = () => showPipelineStep(id);
      $('pipeline-steps').append(button);
    }
    $('pipeline-events').textContent = (pipelineRun?.events || []).map(event => `${new Date(event.time).toLocaleTimeString()}  ${event.message}`).join('\n');
  }

  async function showPipelineStep(nodeId) {
    if (pipelineHistoryLoading || !pipelineRun) return;
    pipelineStep = nodeId;
    const request = ++stepRequest, runId = pipelineRun.id;
    renderPipeline();
    $('download-trained-model').hidden = true;
    $('download-python-data').hidden = true;
    $('ml-step-summary').hidden = true;
    $('pipeline-step-result').textContent = 'Загрузка результата…';
    try {
      const step = await api('/api/pipelines/step', {run_id: runId, node_id: nodeId});
      if (request === stepRequest && pipelineRun?.id === runId) {
        $('pipeline-step-result').textContent = JSON.stringify(step, null, 2);
        const details = step.details || {};
        const summary = $('ml-step-summary'); summary.replaceChildren();
        if (Number.isFinite(details.accuracy)) {
          summary.append(el('p', '', `Accuracy: ${(details.accuracy * 100).toFixed(1)}% · Macro F1: ${details.macro_f1.toFixed(3)}${details.test_rows ? ' · Test: ' + details.test_rows + ' строк' : ''}`));
          if (details.confusion_matrix) {
            summary.append(el('p', 'muted', 'Матрица ошибок: строки — истинный класс, столбцы — предсказанный.'));
            const table = el('table'), header = el('tr'); header.append(el('th', '', 'Класс'));
            for (const label of details.classes) header.append(el('th', '', label));
            table.append(header);
            details.confusion_matrix.forEach((values, i) => {
              const row = el('tr'); row.append(el('th', '', details.classes[i]));
              for (const count of values) row.append(el('td', '', String(count)));
              table.append(row);
            });
            summary.append(table);
          }
          summary.hidden = false;
        }
        const pythonData = step.outputs?.data;
        $('download-python-data').hidden = pythonData?.kind !== 'python_data';
        $('download-python-data').onclick = async () => {
          try { downloadJSON(await api('/api/code/export', {artifact: pythonData}), 'python-result'); }
          catch (error) { toast(error.message); }
        };
        const bundle = step.outputs?.bundle;
        $('download-trained-model').hidden = !bundle || bundle.kind !== 'model_bundle';
        $('download-trained-model').onclick = async () => {
          try { downloadJSON(await api('/api/ml/export', {artifact: bundle}), 'trained-model'); }
          catch (error) { toast(error.message); }
        };
      }
    } catch (error) {
      if (request === stepRequest) $('pipeline-step-result').textContent = error.message;
    }
  }

  function renderPipelineList() {
    $('pipeline-runs').replaceChildren();
    for (const run of pipelineList) {
      const option = el('option', '', `${new Date(run.created_at).toLocaleString()} · ${run.name} · ${pipelineLabels[run.status]}`);
      option.value = run.id;
      $('pipeline-runs').append(option);
    }
    if (pipelineRun) $('pipeline-runs').value = pipelineRun.id;
  }

  async function selectPipeline(id) {
    const request = ++historyRequest;
    ++stepRequest;
    pipelineStep = null;
    pipelineHistoryLoading = true;
    renderPipeline();
    $('download-trained-model').hidden = true;
    $('download-python-data').hidden = true;
    $('ml-step-summary').hidden = true;
    $('pipeline-step-result').textContent = 'Выберите шаг, чтобы увидеть входы, результат и версии.';
    try {
      const record = await api('/api/pipelines/run', {run_id: id});
      if (request !== historyRequest) return;
      pipelineRun = record;
      renderPipelineList();
    } finally {
      if (request === historyRequest) { pipelineHistoryLoading = false; renderPipeline(); }
    }
  }

  function schedulePipelinePoll() {
    clearTimeout(pipelineTimer);
    if (!activePipeline) return;
    pipelineTimer = setTimeout(async () => {
      const id = activePipeline?.id;
      const project = activeProject;
      if (!id) return;
      try {
        const record = await api('/api/pipelines/run', {run_id: id});
        if (project !== activeProject) return;
        activePipeline = ['waiting', 'running'].includes(record.status) ? record : null;
        const previousStep = pipelineRun?.id === id && pipelineStep ? pipelineRun.nodes[pipelineStep]?.status : null;
        if (pipelineRun?.id === id) pipelineRun = record;
        pipelineList = pipelineList.map(item => item.id === id ? {...item, status: record.status} : item);
        renderPipelineList(); renderPipeline();
        if (pipelineStep && pipelineRun?.id === id && previousStep !== record.nodes[pipelineStep]?.status && $('pipeline-dialog').open) showPipelineStep(pipelineStep);
        if (!activePipeline) toast(record.status === 'ready' ? 'Пайплайн завершён. Результаты сохранены в истории.' : record.status === 'paused' ? 'Шаг выполнен. Откройте «По шагам», чтобы проверить результат и продолжить.' : record.error || 'Пайплайн остановлен.');
      } catch (error) {
        $('pipeline-status').textContent = 'Не удалось обновить статус: ' + error.message;
        $('pipeline-live-status').textContent = `${activePipeline?.status === 'waiting' ? 'Запуск в очереди' : 'Запуск принят'} · связь потеряна, уточняем статус…`;
      }
      schedulePipelinePoll();
    }, 1000);
  }

  async function loadPipelineHistory(selectedId) {
    const request = ++historyRequest;
    pipelineHistoryLoading = true;
    renderPipeline();
    try {
      const list = (await api('/api/pipelines/runs', {})).runs;
      if (request !== historyRequest) return;
      pipelineList = list;
      const active = pipelineList.find(run => ['waiting', 'running'].includes(run.status));
      activePipeline = active || null;
      if (selectedId) await selectPipeline(selectedId);
      else if (pipelineRun && pipelineList.some(run => run.id === pipelineRun.id)) await selectPipeline(pipelineRun.id);
      else if (pipelineList.length) await selectPipeline(active?.id || pipelineList[0].id);
      renderPipelineList(); renderPipeline(); schedulePipelinePoll();
    } finally {
      if (request === historyRequest) { pipelineHistoryLoading = false; renderPipeline(); }
    }
  }

  const training = window.TrainingConsole({api, context: () => activeProject, diagram: serializable,
    secrets: () => ({openrouter: openrouterKey, kaggle: $('kg-token').value.trim() || kaggleConnectionToken, huggingface: $('hf-token').value.trim() || hubToken}),
    onResumed: async run => {pipelineRun=run;activePipeline=['waiting','running'].includes(run.status)?run:null;await loadPipelineHistory();renderPipeline();schedulePipelinePoll();}
  });
  $('history-training').onclick = () => training.open(pipelineRun?.id).catch(e => toast(e.message));
  let launchKaggleToken = '';
  function configureLaunchAccess(kinds) {
    const used = new Set(kinds);
    $('pipeline-openrouter-notice').hidden = !used.has('openrouter');
    $('pipeline-hf-field').hidden = !used.has('huggingface');
    launchKaggleToken = used.has('kaggle') ? $('kg-token').value.trim() || kaggleConnectionToken : '';
    $('pipeline-hf-token').value = used.has('huggingface') ? $('hf-token').value.trim() || hubToken : '';
  }
  window.PipelineDebug({api, selected: () => selected, currentRun: () => pipelineRun,
    prepare: async () => {
      if (activePipeline || pipelineStarting) throw new Error('Дождитесь завершения текущего запуска.');
      if (selected && !saveNode()) throw new Error('Проверьте настройки выбранного блока.');
      await flushProject();
      return {diagram: serializable(), ...(activeProject ? {project_id: activeProject.meta.id, revision: activeProject.meta.revision} : {})};
    },
    confirmRun: async (body, plan) => {
      launchReturnFocus = $('debug-pipeline');
      await training.refresh(body);
      pendingPipeline = {...body, run_id: uid()};
      $('pipeline-plan').textContent = 'Шагов к выполнению: ' + plan.execute.length + '. Готовых результатов: ' + plan.reused.length + '.';
      $('pipeline-plan').hidden = false;
      configureLaunchAccess(plan.execute.map(node => node.kind));
      $('pipeline-start-error').textContent = ''; $('pipeline-start-dialog').showModal();
    }
  });
  $('run-pipeline').onclick = async () => {
    if (activePipeline || pipelineStarting) return;
    if (selected && !saveNode()) return;
    const compute = training.selection();
    const secrets = {openrouter: openrouterKey, kaggle: $('kg-token').value.trim() || kaggleConnectionToken,
      huggingface: $('hf-token').value.trim() || hubToken};
    pipelineStarting = true; renderPipeline();
    try {
      await flushProject();
      const diagram = serializable();
      const reference = activeProject ? {project_id: activeProject.meta.id, revision: activeProject.meta.revision} : {};
      const plan = await api('/api/pipelines/validate', {diagram, ...reference});
      const kinds = new Set(plan.diagram.nodes.filter(node => plan.order.includes(node.id)).map(node => node.block.kind));
      for (const key of Object.keys(secrets)) if (!kinds.has(key)) secrets[key] = '';
      pipelineRun = await api('/api/pipelines/start', {diagram, run_id: uid(), ...reference, compute, secrets});
      activePipeline = ['waiting', 'running'].includes(pipelineRun.status) ? pipelineRun : null;
      ++historyRequest; ++stepRequest; pipelineStep = null;
      await loadPipelineHistory();
    } catch (error) { toast(error.message); }
    finally { pipelineStarting = false; renderPipeline(); schedulePipelinePoll(); }
  };
  $('close-pipeline-start').onclick = $('cancel-pipeline-start').onclick = () => $('pipeline-start-dialog').close();
  $('pipeline-start-dialog').addEventListener('close', () => {
    launchKaggleToken = ''; $('pipeline-hf-token').value = '';
    if (!pipelineStarting) {
      pendingPipeline = null;
      const target = launchReturnFocus?.getClientRects().length ? launchReturnFocus : $('viewport');
      target.focus({preventScroll: true});
    }
  });
  $('pipeline-start-form').onsubmit = async event => {
    event.preventDefault();
    if (!pendingPipeline || pipelineStarting) return;
    pipelineStarting = true; $('pipeline-start-submit').disabled = true; renderPipeline();
    try {
      pipelineRun = await api('/api/pipelines/start', {...pendingPipeline, compute: training.selection(), secrets: {openrouter: $('pipeline-openrouter-notice').hidden ? '' : openrouterKey,
        kaggle: launchKaggleToken, huggingface: $('pipeline-hf-token').value.trim()}});
      activePipeline = ['waiting', 'running'].includes(pipelineRun.status) ? pipelineRun : null;
      ++historyRequest; ++stepRequest; pipelineStep = null;
      $('pipeline-start-dialog').close();
      pendingPipeline = null;
      await loadPipelineHistory();
      if (pipelineRun.compute?.mode === 'gpu') await training.open(pipelineRun.id);
    } catch (error) { $('pipeline-start-error').textContent = error.message; }
    finally { pipelineStarting = false; $('pipeline-start-submit').disabled = false; renderPipeline(); schedulePipelinePoll(); }
  };
  $('cancel-pipeline-live').onclick = $('cancel-pipeline').onclick = async () => {
    if (!activePipeline) return;
    try {
      const record = await api('/api/pipelines/cancel', {run_id: activePipeline.id});
      activePipeline = ['waiting', 'running'].includes(record.status) ? record : null;
      if (pipelineRun?.id === record.id) pipelineRun = record;
      renderPipeline();
    } catch (error) { toast(error.message); }
  };
  $('pipeline-history').onclick = async () => {
    if (!window.WorkspaceNavigation.leave()) return;
    $('pipeline-dialog').showModal(); renderPipeline();
    try { await loadPipelineHistory(); } catch (error) { $('pipeline-summary').textContent = error.message; }
  };
  $('close-pipeline-history').onclick = () => $('pipeline-dialog').close();
  $('pipeline-runs').onchange = () => selectPipeline($('pipeline-runs').value).catch(error => { $('pipeline-summary').textContent = error.message; });

  const discussions = {open:async()=>{}};
  window.LabTools({api, compute: training, context: () => activeProject, contract: kind => Contracts.get(kind), download: downloadJSON,
    prepare: async () => {
      if (selected && !saveNode()) throw new Error('Проверьте настройки выбранного блока.');
      await flushProject(); return {diagram: serializable(), ...(activeProject ? {project_id: activeProject.meta.id, revision: activeProject.meta.revision} : {})};
    },
    secrets: () => ({openrouter: openrouterKey, kaggle: $('kg-token').value.trim() || kaggleConnectionToken, huggingface: $('hf-token').value.trim() || hubToken}),
    history: async id => { $('pipeline-dialog').showModal(); await loadPipelineHistory(id); },
    refreshRuns: async deleted => { if (deleted && pipelineRun?.id === deleted) { pipelineRun = null; pipelineStep = null; } await loadPipelineHistory(); }
  });
  window.ProjectInsights({api, context: () => activeProject, diagram: serializable, discussions, download: downloadJSON,
    history: async id => { $('pipeline-dialog').showModal(); await loadPipelineHistory(id); },
    save: async (id, research, description) => {
      if (activeProject?.meta.id !== id) throw new Error('Проект изменился. Откройте обзор заново.');
      activeProject.meta.research = research; activeProject.researchDirty = true; activeProject.description = description;
      activeProject.dirty = true; unsaved = true; cacheProjectDraft(); await flushProject();
    },
  });
  $('discuss-node').onclick = async () => {
    try { if (!activeProject) throw new Error('Сначала нажмите «Сохранить» над схемой.'); if (!saveNode()) return; await flushProject(); await discussions.open(activeProject.meta.id, {node_id: selected}); }
    catch (error) { toast(error.message); }
  };
  window.Experiments({api,
    context: () => ({project_id: activeProject?.meta.id || null, name: activeProject ? 'Проект: ' + activeProject.meta.name : 'Запуски несохранённых схем'}),
    history: openRunDiagram
  });
  window.PythonWorkbench({api, diagram: serializable, save: saveNode, download: downloadJSON,
    node: (id = selected) => { const n = state.nodes.find(n => n.id === id); return n && {...n, block: Contracts.fromExecution(n.execution)}; },
    context: () => ({...(activeProject ? {project_id: activeProject.meta.id} : {}), ...(pipelineRun ? {run_id: pipelineRun.id} : {})}),
    update: (id, settings) => {
      const n = state.nodes.find(n => n.id === id); if (!n) throw new Error('Блок удалён.');
      const block = Contracts.fromExecution(n.execution);
      const execution = Contracts.toExecution({...block, settings: {...block.settings, ...settings}});
      commit(() => { n.execution = execution; });
    },
    pack: id => { selected = id; multiSelected.clear(); render(); $('pack-subgraph').click(); }
  });

  const codexChat = window.CodexChat({api, account, project: () => activeProject,
    diagram: serializable, flush: flushProject, fit: () => fit(true),
    applyProposal: result => {
      Contracts.install(result.contracts);
      const next = validate(result.diagram);
      const original = JSON.stringify(serializable());
      commit(() => { state = next; selected = null; multiSelected.clear(); connection = null; });
      fit(true);
      const checkpoint = JSON.stringify(past[past.length - 1]), applied = JSON.stringify(serializable());
      toast('Изменения Codex применены. Их можно отменить.');
      return {status: () => {
        const current = JSON.stringify(serializable());
        return current === applied ? 'applied' : current === original ? 'undone' : 'changed';
      }, undo: () => {
        if (JSON.stringify(past[past.length - 1]) !== checkpoint || JSON.stringify(serializable()) !== applied)
          throw new Error('После применения схема изменилась. Используйте обычную отмену действий.');
        history(false); fit(true);
      }};
    }});
  community = window.Community({api, account, discussions,
    openDesignDocument: releaseId => openDesignDocuments(false, releaseId),
    connectionStatus: provider => provider === 'kaggle' ? !!kaggleConnectionToken : provider === 'huggingface' ? !!hubToken : !!(openrouterKey || serverKey),
    setConnection: (provider, value) => {
      if (value && !/^[!-~]{1,2048}$/.test(value)) throw new Error('Токен должен содержать только печатные символы без пробелов.');
      if (provider === 'kaggle') { kaggleConnectionToken = value; $('kg-token').value = ''; }
      else if (provider === 'huggingface') { hubToken = value; $('hf-token').value = ''; renderHubModel(); }
    },
    openOpenRouter: () => $('openrouter-settings').click(), project: () => activeProject, flush: async () => {
    if (selected && !saveNode()) throw new Error('Проверьте поля выбранного блока.');
    await flushProject();
  }, adopt: adoptProject, importBlock: value => importSubgraphPackage(value, true), beforeAccountChange: async () => {
    codexChat.reset();
    clearTimeout(projectSaveTimer);
    try { await flushProject(); } catch (error) { if (error.status !== 401) throw error; }
    if (activeProject?.dirty) cacheProjectDraft();
    unsaved = false;
  }});
  window.addEventListener('beforeunload', event => { if (unsaved) { event.preventDefault(); event.returnValue = ''; } });
  let learning;
  if (typeof window.Learning === 'function') {
    learning = window.Learning({api, storageKey: STORAGE_KEY + '.learning.v1', download: downloadJSON});
  } else {
    for (const id of ['learning', 'welcome-learning']) if ($(id)) {
      $(id).disabled = false;
      $(id).onclick = () => toast('Не удалось загрузить обучение. Обновите страницу.');
    }
  }
  mobile = window.MobileWorkspace?.({
    selected: () => state.nodes.find(node => node.id === selected),
    select: id => { selected = id; multiSelected.clear(); renderNodes(); renderInspector(); },
    storageKey: () => STORAGE_KEY + '.mobile.' + (activeProject?.meta.id || 'browser'),
    save: saveNode, behavior: updateBehavior,
    camera: () => camera,
    setCamera: value => { camera = value; renderCamera(); },
    snapshot: () => clone(state),
    move: (before, id, dx, dy) => {
      if (runView) return;
      const origin = before.nodes.find(node => node.id === id), node = state.nodes.find(node => node.id === id);
      if (!origin || !node) return;
      node.x = Math.max(-100000, Math.min(100000, origin.x + dx)); node.y = Math.max(-100000, Math.min(100000, origin.y + dy));
      const card = [...$('nodes').children].find(card => card.dataset.id === id);
      if (card) { card.style.left = node.x + 'px'; card.style.top = node.y + 'px'; } renderEdges();
    },
    cancelMove: before => { state = before; renderNodes(); renderEdges(); },
    finishMove: before => { if (JSON.stringify(before) !== JSON.stringify(state)) { past.push(before); if (past.length > 50) past.shift(); future = []; persist(); render(); } },
    cache: () => { if (activeProject?.dirty) cacheProjectDraft(); },
    outputs: node => Contracts.ports(node, 'output', state.edges),
    connections: fromPort => {
      const result = [];
      for (const node of state.nodes) for (const port of Contracts.ports(node, 'input', state.edges)) {
        const edge = {id: uid(), from: selected, fromPort, to: node.id, toPort: port.id, kind: port.type === 'annotation' ? 'annotation' : 'data'};
        if (!Contracts.connectionError(state.nodes, state.edges, edge)) result.push({edge, label: node.name + ' · ' + port.label});
      }
      return result;
    },
    connect: edge => {
      const error = Contracts.connectionError(state.nodes, state.edges, edge);
      if (error) throw new Error(error);
      if (state.edges.length >= 1000) throw new Error('Достигнут лимит связей.');
      commit(() => state.edges.push(edge));
    }
  });
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) { state = await prepareDiagram(JSON.parse(saved)); $('save-status').textContent = 'Схема восстановлена локально'; }
  } catch { toast('Не удалось восстановить сохранённую схему. Можно импортировать JSON или начать новую.'); }
  render();
  let projectId = new URL(location.href).searchParams.get('project');
  try { projectId ||= localStorage.getItem(ACTIVE_PROJECT_KEY); } catch {}
  try {
    if (projectId && (!account.enabled || account.user)) await openProject(projectId, true);
  } catch (error) {
    let restored = false;
    try {
      const cached = JSON.parse(localStorage.getItem(STORAGE_KEY + '.project.' + projectId) || 'null');
      if (cached?.project?.id === projectId) {
        state = await prepareDiagram(cached.diagram);
        activeProject = {meta: {...cached.project, name: cached.name}, description: cached.description, dirty: true, conflict: false, researchDirty: !!cached.researchDirty};
        unsaved = true; render(); renderProjectStatus(); restored = true;
      }
    } catch {}
    toast(restored ? 'Проект недоступен. Восстановлена резервная копия; сохраните её после восстановления соединения.' : 'Не удалось открыть проект: ' + error.message);
  }
  if (!account.enabled || account.user) loadPipelineHistory().catch(error => { $('pipeline-status').textContent = 'История недоступна: ' + error.message; });
  else community.openAccount();
  if (state.nodes.length) requestAnimationFrame(() => fit(true));
  const chatRequested = new URL(location.href).searchParams.get('chat') === '1';
  if (chatRequested && account.user && activeProject?.meta.id === new URL(location.href).searchParams.get('project')) await codexChat.open();
})();

// Local frame geometry only: never modifies nodes, connections or project data.
(() => {
  const stage = document.getElementById('canvas-stage');
  const editor = document.getElementById('canvas-editor');
  const move = document.getElementById('canvas-frame-move');
  const resize = document.getElementById('canvas-frame-resize');
  const layout = stage.parentElement, viewport = document.getElementById('viewport');
  const tools = editor.querySelector('.canvas-add-tools'), bottom = editor.querySelector('.canvas-bottom');
  const zoomBar = bottom.querySelector('.zoom-tools');
  const showField = document.createElement('button'); showField.id = 'scene-fit'; showField.textContent = 'Показать поле';
  showField.title = 'Вернуть весь лист в видимую область';
  zoomBar.append(showField);
  const expandField = document.createElement('button'); expandField.id = 'scene-expand'; expandField.textContent = 'Развернуть поле';
  expandField.title = 'Занять всю доступную область';
  zoomBar.append(expandField);
  const wide = matchMedia('(min-width: 1360px)');
  let frame = null, gesture = null, sceneScale = 1;
  stage.tabIndex = 0;
  stage.setAttribute('aria-label', 'Рабочая сцена. Стрелки — перемещение поля; Прокрутка — масштаб');
  const enabled = () => wide.matches && !window.DeviceUI?.mobile;
  const expanded = () => document.fullscreenElement === editor || editor.classList.contains('canvas-expanded');
  function current() {
    return frame || {x: editor.offsetLeft, y: editor.offsetTop, width: editor.offsetWidth, height: editor.offsetHeight};
  }
  function apply(next) {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!enabled() || !w || !h || expanded()) return;
    const width = Math.max(Math.min(480, w), next.width);
    const height = Math.max(Math.min(420, h), next.height);
    frame = {width, height, x: next.x, y: next.y};
    for (const [key, value] of Object.entries(frame)) editor.style.setProperty('--frame-' + key, value + 'px');
    editor.style.setProperty('--frame-scale', sceneScale);
    editor.dispatchEvent(new Event('frame-scale-change'));
  }
  function change(start, dx, dy, resizing) {
    if (resizing) apply({...start, width: start.width + dx / sceneScale, height: start.height + dy / sceneScale});
    else apply({...start, x: start.x + dx, y: start.y + dy});
  }
  function zoomScene(factor, point) {
    if (!enabled() || expanded() || gesture) return;
    const start = current(), previous = sceneScale;
    const rect = stage.getBoundingClientRect();
    const x = point ? point.x - rect.left : stage.clientWidth / 2;
    const y = point ? point.y - rect.top : stage.clientHeight / 2;
    sceneScale = Math.max(.15, Math.min(2, previous * factor));
    apply({...start, x: x - (x - start.x) * sceneScale / previous, y: y - (y - start.y) * sceneScale / previous});
  }
  layout.addEventListener('wheel', event => {
    if (!enabled() || expanded() || gesture || document.querySelector('dialog[open]:not(#codex-chat)') ||
        event.target.closest('.inspector, .library, .canvas-add-tools, .canvas-bottom, button, input, select, textarea, a')) return;
    event.preventDefault(); event.stopPropagation();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? stage.clientHeight : 1);
    zoomScene(Math.exp(-Math.max(-300, Math.min(300, delta)) * .002), {x: event.clientX, y: event.clientY});
  }, {passive: false, capture: true});
  for (const [id, factor] of [['zoom-in', 1.2], ['zoom-out', 1 / 1.2]]) {
    document.getElementById(id).addEventListener('click', event => {
      if (!enabled() || expanded()) return;
      event.preventDefault(); event.stopImmediatePropagation(); zoomScene(factor);
    }, true);
  }
  function sceneInsets() {
    const style = getComputedStyle(document.body);
    const left = parseFloat(style.getPropertyValue("--workspace-chat-slot")) || 0;
    const right = parseFloat(style.getPropertyValue("--workspace-inspector-slot")) || 0;
    return {left, width: stage.clientWidth - left - right};
  }
  function resetFrame() {
    frame = null;
    sceneScale = 1;
    for (const key of ['x', 'y', 'width', 'height', 'scale']) editor.style.removeProperty('--frame-' + key);
    editor.dispatchEvent(new Event('frame-scale-change'));
  }
  expandField.onclick = () => editor.dispatchEvent(new Event('frame-fit-request'));
  editor.addEventListener('frame-reset', resetFrame);
  editor.addEventListener('frame-fit-content', event => {
    if (!enabled() || expanded()) return;
    const detail = event.detail, start = current();
    if (detail.width <= viewport.clientWidth && detail.height <= viewport.clientHeight) return;
    const chromeWidth = editor.offsetWidth - viewport.clientWidth;
    const chromeHeight = editor.offsetHeight - viewport.clientHeight;
    sceneScale = 1;
    apply({width: Math.max(start.width, detail.width + chromeWidth),
      height: Math.max(start.height, detail.height + chromeHeight),
      x: start.x - detail.focusX, y: start.y - detail.focusY});
    detail.applied = true;
  });
  showField.onclick = () => {
    const start = current(), {left, width} = sceneInsets();
    sceneScale = Math.max(.15, Math.min(1, (width - 40) / start.width, (stage.clientHeight - 140) / start.height));
    apply({...start, x: left + (width - start.width * sceneScale) / 2, y: 80 + (stage.clientHeight - 140 - start.height * sceneScale) / 2});
  };
  for (const handle of [move, resize, editor, layout]) {
    handle.addEventListener('pointerdown', event => {
      if (!enabled() || event.button !== 0 || expanded()) return;
      if (handle === layout && event.target !== layout && event.target !== stage) return;
      if (handle === editor && (event.altKey || event.target.closest('.node, button, summary, input, select, textarea, a, [contenteditable]'))) return;
      event.preventDefault(); event.stopPropagation();
      (handle === layout ? stage : handle === editor ? viewport : handle).focus({preventScroll: true});
      gesture = {start: {...current()}, x: event.clientX, y: event.clientY, id: event.pointerId, handle, moved: false};
      handle.setPointerCapture(event.pointerId);
    }, handle === editor || handle === layout);
    handle.addEventListener('pointermove', event => {
      if (!gesture || gesture.id !== event.pointerId || gesture.handle !== handle) return;
      if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= 3) gesture.moved = true;
      if ((handle === editor || handle === layout) && !gesture.moved) return;
      change(gesture.start, event.clientX - gesture.x, event.clientY - gesture.y, handle === resize);
    });
    const end = event => {
      if (!gesture || gesture.id !== event.pointerId || gesture.handle !== handle) return;
      if (event.type === 'pointercancel') apply(gesture.start);
      if (event.type === 'pointerup' && handle === editor && !gesture.moved) editor.dispatchEvent(new Event('frame-background-click'));
      gesture = null;
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('lostpointercapture', event => { if (gesture?.handle === event.target) gesture = null; });
    handle.addEventListener('keydown', event => {
      if (handle === layout && event.target !== stage) return;
      if (handle === editor && !(event.key === 'Escape' && gesture?.handle === editor)) return;
      event.stopPropagation();
      if (event.key === 'Escape' && gesture) {
        event.preventDefault(); const active = gesture; apply(active.start); gesture = null;
        if (handle.hasPointerCapture(active.id)) handle.releasePointerCapture(active.id);
      }
      const direction = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
      if (!direction || !enabled()) return;
      event.preventDefault(); const step = event.shiftKey ? 30 : 10;
      change(current(), direction[0] * step, direction[1] * step, handle === resize);
    });
  }
  document.getElementById('canvas-frame-fill').onclick = () => {
    sceneScale = 1; apply({x: 0, y: 0, width: stage.clientWidth, height: stage.clientHeight});
  };
  new ResizeObserver(() => { if (frame) apply(frame); }).observe(stage);
  const tip = editor.querySelector('.canvas-tip'), originalTip = tip.textContent;
  function updateTip() {
    const active = enabled() && !expanded();
    document.body.classList.toggle('scene-mode', active);
    if (tools.parentElement !== (active ? stage : viewport)) {
      (active ? stage : viewport).prepend(tools);
      (active ? stage : viewport).append(bottom);
    }
    showField.hidden = expandField.hidden = !active;
    document.getElementById('fit').textContent = active ? 'Вписать схему' : 'Вписать';
    tip.textContent = active ? 'Тяните фон — перемещение · Прокрутка — масштаб поля' : originalTip;
    editor.dispatchEvent(new Event('frame-scale-change'));
  }
  wide.addEventListener('change', () => { if (frame) apply(frame); updateTip(); });
  document.addEventListener('fullscreenchange', updateTip);
  new MutationObserver(updateTip).observe(editor, {attributes: true, attributeFilter: ['class']});
  updateTip();
})();


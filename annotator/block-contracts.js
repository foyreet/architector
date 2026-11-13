'use strict';

// One registry is shared with Python. This module adapts the existing form fields
// to versioned block instances; it never imports functions or URLs from a diagram.
window.BlockContracts = async function () {
  const response = await fetch('/api/blocks/contracts');
  if (!response.ok) throw new Error('Не удалось загрузить контракты блоков. Перезапустите сервер.');
  const catalog = await response.json();
  const contracts = new Map(catalog.blocks.map(item => [item.kind, item]));
  const copy = value => JSON.parse(JSON.stringify(value));
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  const fail = message => { throw new Error(message || 'Некорректный контракт блока.'); };
  const get = (kind, version = 1) => {
    const value = contracts.get(kind);
    if (!value || value.version !== version) fail('Неизвестный тип или версия контракта блока.');
    return value;
  };
  function artifact(value, kind) {
    if (!object(value) || value.type !== 'artifact' || value.kind !== kind ||
        Object.keys(value).some(key => !['type', 'kind', 'provider', 'id', 'revision'].includes(key))) fail('Ожидается ссылка на локальный артефакт.');
    if (['table', 'trained_model', 'metrics', 'model_bundle', 'python_data'].includes(kind) || (kind === 'dataset' && value.provider === 'local')) {
      if (value.provider !== 'local' || typeof value.id !== 'string' || !/^[a-f0-9]{64}$/.test(value.id) || value.revision !== undefined) fail('Некорректный артефакт обучения.');
      return copy(value);
    }
    const valid = typeof value.id === 'string' && (kind === 'dataset' ?
      value.provider === 'kaggle' && value.revision === undefined && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}(?:\/versions\/[1-9][0-9]{0,8})?$/.test(value.id) :
      value.provider === 'huggingface' && /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}(?:\/[A-Za-z0-9_][A-Za-z0-9_.-]{0,95})?$/.test(value.id) &&
        !value.id.includes('..') && !value.id.includes('--') && typeof value.revision === 'string' && /^[a-f0-9]{40}$/.test(value.revision));
    if (!valid) fail('Некорректная ссылка на артефакт.');
    return copy(value);
  }
  function valueCheck(value, spec) {
    if (['dataset', 'model', 'table', 'trained_model', 'metrics', 'model_bundle', 'python_data'].includes(spec.type)) return artifact(value, spec.type);
    let valid = false;
    if (spec.type === 'json') {
      const visit = (item) => {
        if (Array.isArray(item)) item.forEach(visit);
        else if (object(item)) Object.values(item).forEach(visit);
        else if (!(item === null || typeof item === 'string' || typeof item === 'boolean' || typeof item === 'number' && Number.isFinite(item))) fail();
      };
      visit(value);
      return copy(value);
    }
    if (['text', 'string'].includes(spec.type)) valid = typeof value === 'string' && value.length <= (spec.maxLength ?? 32000) && (!spec.pattern || new RegExp(spec.pattern).test(value));
    if (['integer', 'number'].includes(spec.type)) valid = typeof value === 'number' && Number.isFinite(value) &&
      (spec.type !== 'integer' || Number.isInteger(value)) && value >= (spec.minimum ?? -Infinity) && value <= (spec.maximum ?? Infinity);
    if (spec.type === 'string[]') valid = Array.isArray(value) && value.length <= (spec.maxItems ?? 5000) && value.every(s => typeof s === 'string' && s.length <= (spec.maxLength ?? 500));
    if (spec.type === 'rows') {
      valid = Array.isArray(value);
      if (valid) for (const row of value) valueCheck(row, {type: 'row'});
    }
    if (spec.type === 'row') valid = object(value) && Object.values(value).every(cell =>
      (cell === null || typeof cell === 'boolean' || (typeof cell === 'number' && Number.isFinite(cell)) || (typeof cell === 'string')));
    if (!valid || (spec.enum && !spec.enum.includes(value))) fail(`Некорректное значение: ${spec.label}`);
    return copy(value);
  }
  function normalize(value) {
    if (!object(value)) fail();
    const contract = get(value.kind, value.version);
    if (value.version !== contract.version) fail();
    const result = {kind: contract.kind, version: contract.version, inputs: {}, settings: {}};
    for (const section of ['inputs', 'settings']) {
      const supplied = value[section] ?? {};
      if (!object(supplied)) fail();
      for (const spec of contract[section]) {
        if (Object.hasOwn(supplied, spec.id)) result[section][spec.id] = valueCheck(supplied[spec.id], spec);
        else if (Object.hasOwn(spec, 'default')) result[section][spec.id] = copy(spec.default);
      }
    }
    return result;
  }
  function defaults() {
    const values = {mode: 'note', input_values: {}, custom_settings: {}};
    for (const contract of contracts.values()) for (const spec of [...contract.inputs, ...contract.settings]) {
      if (spec.field && Object.hasOwn(spec, 'default')) values[spec.field] = copy(spec.default);
    }
    return values;
  }
  function fromExecution(execution) {
    const contract = get(execution.mode);
    const value = {kind: contract.kind, version: contract.version, inputs: {}, settings: {}};
    for (const section of ['inputs', 'settings']) for (const spec of contract[section]) {
      const item = spec.field ? execution[spec.field] : (section === 'inputs' ? execution.input_values : execution.custom_settings)?.[spec.id];
      if (item !== undefined) value[section][spec.id] = item;
    }
    return normalize(value);
  }
  function toExecution(value) {
    const block = normalize(value), contract = get(block.kind);
    const result = {...defaults(), mode: block.kind};
    for (const section of ['inputs', 'settings']) for (const spec of contract[section]) {
      if (!Object.hasOwn(block[section], spec.id)) continue;
      if (spec.field) result[spec.field] = copy(block[section][spec.id]);
      else (section === 'inputs' ? result.input_values : result.custom_settings)[spec.id] = copy(block[section][spec.id]);
    }
    return result;
  }
  function port(node, side, id) {
    if (id === 'annotation') return {id, label: 'Описание', type: 'annotation'};
    return get(node.execution.mode)[side === 'input' ? 'inputs' : 'outputs'].find(item => item.id === id);
  }
  function ports(node, side, edges) {
    const values = [...get(node.execution.mode)[side === 'input' ? 'inputs' : 'outputs']];
    if (node.execution.mode === 'note' || edges.some(edge => edge.kind === 'annotation' && edge[side === 'input' ? 'to' : 'from'] === node.id)) {
      values.push(port(node, side, 'annotation'));
    }
    return values;
  }
  function connectionError(nodes, edges, edge) {
    const from = nodes.find(item => item.id === edge.from), to = nodes.find(item => item.id === edge.to);
    if (!from || !to || from.id === to.id) return 'Связь должна соединять два разных существующих блока.';
    const output = port(from, 'output', edge.fromPort), input = port(to, 'input', edge.toPort);
    if (!output || !input) return 'Выбранный порт отсутствует в контракте блока.';
    if (output.type !== input.type) return `Несовместимые типы: ${catalog.types[output.type].label} → ${catalog.types[input.type].label}.`;
    if (edge.kind !== (output.type === 'annotation' ? 'annotation' : 'data')) return 'Некорректный вид связи.';
    const others = edges.filter(item => item.id !== edge.id);
    if (others.some(item => item.from === edge.from && item.to === edge.to && item.fromPort === edge.fromPort && item.toPort === edge.toPort)) return 'Эти порты уже соединены.';
    if (edge.kind === 'data' && others.some(item => item.kind === 'data' && item.to === edge.to && item.toPort === edge.toPort)) return 'У входа может быть только один источник данных. Сначала удалите прежнюю связь.';
    return '';
  }
  function install(values) {
    for (const contract of values) {
      if (!/^subgraph_[a-f0-9]{64}$/.test(contract.kind)) fail('Некорректный контракт подсхемы.');
      contracts.set(contract.kind, copy(contract));
    }
  }
  return {catalog, get, defaults, normalize, fromExecution, toExecution, port, ports, connectionError, install};
};


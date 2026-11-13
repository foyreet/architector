'use strict';
window.ProjectInsights = ({api, context, diagram, save, discussions, download, history}) => {
  const $ = id => document.getElementById(id);
  const el = (tag, text = '', cls = '') => { const n = document.createElement(tag); n.textContent = text; n.className = cls; return n; };
  const statuses = {ready: 'Готово', paused: 'Ожидает продолжения', error: 'Ошибка', running: 'Работает', waiting: 'Ожидает', cancelled: 'Остановлен'};
  const date = value => value ? new Date(value).toLocaleString() : '—';
  const button = (parent, text, fn) => { const b = el('button', text); b.type = 'button'; b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { const p = el('p', e.message, 'insight-error'); p.setAttribute('role', 'alert'); parent.append(p); } finally { b.disabled = false; } }; parent.append(b); return b; };
  const field = (parent, label, tag, value = '') => { const l = el('label', label), input = el(tag); input.value = value; l.append(input); parent.append(l); return input; };
  const dialog = el('dialog', '', 'insight-dialog'); dialog.id = 'insights-dialog'; document.body.append(dialog);
  let dirty = false, saving = false, generation = 0;
  dialog.addEventListener('cancel', e => { if (saving || (dirty && !confirm('План не сохранён. Закрыть без сохранения?'))) e.preventDefault(); });
  dialog.addEventListener('close', () => { if (!dialog.open) { ++generation; dirty = false; } });
  window.addEventListener('beforeunload', event => { if (dirty || saving) { event.preventDefault(); event.returnValue = ''; } });
  const number = value => new Intl.NumberFormat('ru-RU', {maximumSignificantDigits: 6}).format(value);
  // Summaries show quality scores, not every numeric field in a Python report.
  // Match whole metric names so accuracy_threshold and precision_bits stay in JSON.
  const qualityMetrics = new Set(['accuracy', 'acc', 'precision', 'recall', 'sensitivity', 'specificity',
    'f1', 'f1_score', 'f2', 'fbeta', 'fbeta_score', 'auc', 'roc_auc', 'auc_roc', 'pr_auc', 'auc_pr',
    'average_precision', 'mcc', 'cohen_kappa', 'kappa', 'log_loss', 'logloss', 'loss', 'cross_entropy',
    'brier_score', 'mae', 'mse', 'rmse', 'r2', 'r2_score', 'mape', 'smape', 'msle', 'rmsle', 'explained_variance']);
  function isQualityMetric(path) {
    let key = path.split('/').pop().trim().replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase().replace(/[\s-]+/g, '_');
    key = key.replace(/^(?:(?:train|training|test|val|valid|validation|macro|micro|weighted|mean|avg|balanced)_)+/, '')
      .replace(/_(?:macro|micro|weighted|mean|avg)$/, '');
    return qualityMetrics.has(key);
  }
  const visibleMetrics = values => Object.entries(values || {}).filter(([key, value]) => isQualityMetric(key) && typeof value === 'number' && Number.isFinite(value));
  function metricCards(parent, values, kind) {
    const grid = el('dl', '', 'result-metrics');
    for (const [key, value] of visibleMetrics(values)) {
      if (typeof value !== 'number' || !Number.isFinite(value)) continue;
      const known = kind === 'ml_evaluate' ? {
        accuracy: ['Доля верных ответов (accuracy)', value >= 0 && value <= 1 ? number(value * 100) + ' %' : number(value), 'Доля правильных предсказаний'],
        macro_f1: ['Macro F1', number(value), 'Среднее F1 по классам · от 0 до 1']
      }[key] : null;
      const item = el('div', '', 'result-metric');
      item.append(el('dt', known?.[0] || key), el('dd', known?.[1] || number(value)));
      if (known) item.append(el('small', known[2]));
      grid.append(item);
    }
    if (grid.children.length) parent.append(grid);
    else parent.append(el('p', 'Основные метрики качества не найдены. Полный результат доступен в JSON.'));
  }
  function resultTable(parent, caption, headings, rows) {
    const scroll = el('div', '', 'insight-scroll'); scroll.tabIndex = 0;
    scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', caption);
    const table = el('table', '', 'experiments-table'); table.append(el('caption', caption, 'sr-only'));
    const head = el('thead'), header = el('tr');
    for (const label of headings) { const th = el('th', label); th.scope = 'col'; header.append(th); }
    head.append(header); table.append(head);
    const body = el('tbody');
    for (const row of rows) {
      const tr = el('tr'); row.forEach((value, i) => { const cell = el(i ? 'td' : 'th', String(value)); if (!i) cell.scope = 'row'; tr.append(cell); }); body.append(tr);
    }
    table.append(body); scroll.append(table); parent.append(el('h3', caption, 'result-table-title'), scroll);
  }
  function classificationTables(parent, value) {
    if (!value) return;
    const classes = value.classes, matrix = value.confusion_matrix;
    if (Array.isArray(classes) && classes.length && Array.isArray(matrix) && matrix.length === classes.length && matrix.every(row => Array.isArray(row) && row.length === classes.length)) {
      resultTable(parent, 'Матрица ошибок · строки — фактический класс, столбцы — предсказанный', ['Факт / Прогноз', ...classes], classes.map((name, i) => [name, ...matrix[i]]));
    }
    const rows = Object.entries(value.report || {}).filter(([, metrics]) => metrics && typeof metrics === 'object').map(([name, metrics]) =>
      [name, ...['precision', 'recall', 'f1-score', 'support'].map(key => typeof metrics[key] === 'number' ? number(metrics[key]) : '—')]);
    if (rows.length) resultTable(parent, 'Показатели по классам и средние значения', ['Класс / Среднее', 'Precision', 'Recall', 'F1', 'Строк (support)'], rows);
  }
  function plot(run) {
    const entries = Object.entries(run.metrics);
    const modal = el('dialog', '', 'insight-dialog'); const heading = el('div', '', 'dialog-heading'); heading.append(el('h2', 'Метрики запуска'));
    button(heading, 'Закрыть', () => modal.close()); modal.append(heading, el('p', run.id));
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 800 ${80 + entries.length * 65}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Метрики запуска ' + run.id); svg.style.width = '100%';
    function shape(tag, attrs, text = '') { const n = document.createElementNS(svg.namespaceURI, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); n.textContent = text; svg.append(n); }
    shape('rect', {width: '100%', height: '100%', fill: '#fff'});
    shape('text', {x: 20, y: 25, fill: '#334155', 'font-size': 14}, run.id + ' · ' + date(run.created_at));
    resultTable(modal, 'Значения метрик · каждая величина указана отдельно', ['Метрика', 'Значение'], entries.map(([, m]) => [m.label, number(m.value)]));
    entries.forEach(([, m], i) => {
      const y = 60 + i * 65;
      shape('text', {x: 20, y, fill: '#334155', 'font-size': 14}, m.label.slice(0, 65));
      shape('text', {x: 780, y: y + 22, fill: '#334155', 'font-size': 16, 'text-anchor': 'end'}, number(m.value));
    });
    button(modal, 'Скачать сводку SVG', () => {
      const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], {type: 'image/svg+xml'}));
      const a = el('a'); a.href = url; a.download = 'metrics-' + run.id + '.svg'; modal.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    document.body.append(modal); modal.onclose = () => modal.remove(); modal.showModal();
  }
  function errorHelp(message) {
    const text = String(message || '');
    if (/scikit|sklearn|среда|интерпретатор/i.test(text)) return 'Среда обучения недоступна. Владельцу сервера нужно установить зависимости ML из инструкции запуска.';
    if (/Python-исполнитель недоступен|локальный Python/i.test(text)) return 'Перезапустите Архитектор через run_local.py: он подготовит зависимости Python.';
    if (/колон|признак|target|числ|пропуск/i.test(text)) return 'Откройте данные, проверьте целевую колонку, числовые признаки и обработку пропусков в подготовке.';
    if (/ключ|токен|401|403/i.test(text)) return 'Проверьте доступ к источнику и ключ в разделе «Подключения».';
    return 'Откройте историю запуска: там указан остановившийся блок и исходная ошибка. Проверьте его входы и настройки, затем повторите запуск.';
  }
  async function preview(title, load, exportValue = null) {
    const modal = el('dialog', '', 'insight-dialog'); const heading = el('div', '', 'dialog-heading'); heading.append(el('h2', title)); button(heading, 'Закрыть', () => modal.close()); modal.append(heading);
    const content = el('div'); modal.append(content); document.body.append(modal); modal.showModal(); modal.onclose = () => modal.remove();
    let serial = 0;
    const show = async page => {
      const token = ++serial; content.replaceChildren(el('p', 'Загрузка…'));
      try {
        const result = await load(page); if (!modal.open || token !== serial) return;
        content.replaceChildren();
        if (result.profile) {
          content.append(el('p', `${result.profile.rows} строк · ${result.profile.columns.length} колонок · ${result.profile.duplicates} повторов`));
          const details = el('details'); details.append(el('summary', 'Типы, пропуски и диапазоны'), el('pre', JSON.stringify(result.profile.columns, null, 2))); content.append(details);
          const scroll = el('div', '', 'insight-scroll'), table = el('table', '', 'experiments-table'), head = el('tr');
          const columns = result.profile.columns.map(c => c.name); for (const c of columns) head.append(el('th', c)); table.append(head);
          for (const row of result.rows) { const tr = el('tr'); for (const c of columns) tr.append(el('td', String(row[c] ?? ''))); table.append(tr); }
          scroll.append(table); content.append(scroll);
          const controls = el('div', '', 'insight-actions'); content.append(controls);
          button(controls, '← Предыдущие', () => show(page - 1)).disabled = page === 0;
          controls.append(el('span', 'Страница ' + (page + 1)));
          button(controls, 'Следующие →', () => show(page + 1)).disabled = (page + 1) * result.page_size >= result.profile.rows;
          if (result.preparation_error) content.append(el('p', 'Подготовка: ' + result.preparation_error));
        } else if (result.format === 'files') {
          content.append(el('p', 'Локальные файлы источника. Веса и датасеты хранятся отдельно от проекта.'));
          for (const f of result.content.files || []) {
            const row = el('div', '', 'insight-actions'); row.append(el('span', f.name + ' · ' + f.size + ' байт')); content.append(row);
            if (result.preview_files) button(row, 'Просмотреть файл', () => preview(f.name, () => load(0, f.name)));
          }
        } else if (result.metric_summary) {
          metricCards(content, result.metric_summary, result.block_kind);
          classificationTables(content, result.classification);
          if (result.classification_note) content.append(el('p', result.classification_note));
          const raw = el('details', '', 'result-raw'); raw.append(el('summary', 'Исходные данные JSON'), el('pre', result.text ?? JSON.stringify(result.content ?? result, null, 2))); content.append(raw);
        } else content.append(el('pre', result.text ?? JSON.stringify(result.content ?? result, null, 2)));
        if (result.truncated) content.append(el('p', 'Предпросмотр сокращён. Скачайте JSON для полного содержимого.'));
      } catch (e) { content.replaceChildren(el('p', e.message), el('p', errorHelp(e.message))); }
    };
    if (exportValue) button(modal, 'Скачать JSON', exportValue);
    await show(0);
  }
  async function open(view) {
    if (saving || (dirty && !confirm('План не сохранён. Продолжить без сохранения?'))) return;
    if (!window.WorkspaceNavigation.show(dialog, view)) return;
    dirty = false; const token = ++generation, project = context(), project_id = project?.meta.id;
    const current = () => token === generation && dialog.open && context()?.meta.id === project_id;
    dialog.replaceChildren(el('h2', view === 'overview' ? 'План эксперимента' : 'Результаты'));
    const tools = el('div', '', 'insight-actions'); dialog.append(tools);
    button(tools, 'Обновить', () => open(view));
    if (!project) { dialog.append(el('p', 'Откройте сохранённый проект через «+ → Каталог проектов» или нажмите «Сохранить» над текущей схемой.')); return; }
    dialog.append(el('p', `${project.meta.name} · редакция ${project.meta.revision}`));
    const body = el('div'); dialog.append(body);
    try {
      const data = await api('/api/pipelines/overview', {project_id}); if (!current()) return;
      for (const warning of data.warnings) body.append(el('p', warning));
      if (view === 'overview') overview(body, project, data, current);
      else await results(body, project, data, current);
    } catch (e) { if (current()) body.append(el('p', e.message, 'insight-error')); }
  }
  function overview(parent, project, data, current) {
    const plan = project.meta.research || {}, latest = data.runs[0];
    const state = el('section', '', 'insight-card'); state.append(el('h3', 'Последний запуск'));
    if (!latest) state.append(el('p', 'Запусков пока нет. Сохраните план и запустите пайплайн над схемой.'));
    else {
      state.append(el('p', `${statuses[latest.status] || latest.status} · ${date(latest.created_at)} · ${latest.id}`));
      if (latest.error) { state.append(el('p', errorHelp(latest.error))); const detail = el('details'); detail.append(el('summary', 'Исходная ошибка'), el('pre', typeof latest.error === 'string' ? latest.error : JSON.stringify(latest.error))); state.append(detail); }
      button(state, 'Открыть журнал запуска', () => history(latest.id));
    }
    parent.append(state);
    const form = el('section', '', 'insight-card'); form.append(el('h3', 'Постановка эксперимента')); parent.append(form);
    const description = field(form, 'Описание проекта', 'textarea', project.description);
    const hypothesis = field(form, 'Гипотеза', 'textarea', plan.hypothesis || ''); hypothesis.dataset.hypothesis = 'true';
    const options = new Map();
    for (const node of diagram().nodes) if (node.block?.kind === 'ml_evaluate') for (const key of ['accuracy', 'macro_f1']) options.set(node.id + '/' + key, node.name + ' · ' + key);
    for (const run of data.runs) for (const [key, value] of Object.entries(run.metrics)) options.set(key, value.label);
    const metricChoice = field(form, 'Основная метрика', 'select'); metricChoice.append(new Option('Выбрать позже', ''));
    for (const [id, label] of options) metricChoice.append(new Option(label, id));
    metricChoice.append(new Option('Свой ключ метрики (Python)', '__custom__'));
    metricChoice.value = plan.metric ? (options.has(plan.metric) ? plan.metric : '__custom__') : '';
    const metric = field(form, 'Ключ: ID блока/путь числа в report', 'input', plan.metric || ''); metric.placeholder = 'python_node/accuracy'; metric.parentElement.hidden = metricChoice.value !== '__custom__';
    const choices = el('datalist'); choices.id = 'insight-metrics'; for (const [id, label] of options) { const o = el('option', label); o.value = id; choices.append(o); } metric.setAttribute('list', choices.id); form.append(choices);
    form.append(el('p', 'Для Python используйте ID блока и путь числа в report, например python_node/accuracy. Ключи появятся в списке после запуска.', 'muted'));
    const direction = field(form, 'Лучшее значение', 'select'); direction.append(new Option('Больше', 'max'), new Option('Меньше', 'min')); direction.value = plan.direction || 'max';
    const baseline = field(form, 'Базовый успешный запуск', 'select'); baseline.append(new Option('Пока не выбран', ''));
    for (const r of data.runs.filter(r => r.status === 'ready')) baseline.append(new Option(date(r.created_at) + ' · ' + r.id, r.id));
    if (plan.baseline && !data.runs.some(r => r.id === plan.baseline)) baseline.append(new Option('Ранее выбранный · ' + plan.baseline, plan.baseline)); baseline.value = plan.baseline || '';
    for (const input of [description, hypothesis, metric, direction, baseline]) input.oninput = () => { dirty = true; };
    const status = el('p'); status.setAttribute('role', 'status'); form.append(status);
    button(form, 'Сохранить план', async () => {
      saving = true; for (const i of [description, hypothesis, metricChoice, metric, direction, baseline]) i.disabled = true;
      try { await save(project.meta.id, {hypothesis: hypothesis.value, metric: metric.value, direction: direction.value, baseline: baseline.value, tutorial: !!plan.tutorial}, description.value); if (current()) { dirty = false; status.textContent = 'План сохранён. Следующий запуск сохранит его снимок.'; } }
      finally { saving = false; for (const i of [description, hypothesis, metricChoice, metric, direction, baseline]) i.disabled = false; }
    });
    const chart = el('section', '', 'insight-card'); parent.append(chart);
    function draw() {
      chart.replaceChildren(el('h3', 'Основная метрика по запускам'), el('p', 'Сравниваются успешные запуски. Сопоставимость данных и условий проверяйте во вкладке «Эксперименты».'));
      const runs = data.runs.filter(r => r.status === 'ready' && Number.isFinite(r.metrics[metric.value]?.value));
      if (!runs.length) { chart.append(el('p', 'Для выбранного ключа ещё нет результатов.')); return; }
      const best = [...runs].sort((a, b) => (a.metrics[metric.value].value - b.metrics[metric.value].value) * (direction.value === 'min' ? 1 : -1))[0];
      chart.append(el('p', `Лучший результат: ${best.metrics[metric.value].value} · ${best.id}`));
      const base = runs.find(r => r.id === baseline.value), max = Math.max(...runs.map(r => Math.abs(r.metrics[metric.value].value)), 1e-12);
      for (const r of runs) {
        const v = r.metrics[metric.value].value, row = el('div', '', 'metric-row');
        row.append(el('span', date(r.created_at)), el('strong', String(v) + (base ? ' · Δ ' + (v - base.metrics[metric.value].value).toPrecision(4) : '')));
        const bar = el('div', '', 'metric-bar'); bar.style.width = Math.max(1, Math.abs(v) / max * 100) + '%'; row.append(bar); row.title = r.id; chart.append(row);
      }
      if (baseline.value && !base) chart.append(el('p', 'Базовый запуск вне выборки или в нём нет этой метрики. Разница не вычислена.'));
      button(chart, 'Скачать отчёт сравнения JSON', () => download({metric: metric.value, direction: direction.value, baseline: baseline.value, runs}, 'comparison'));
    }
    for (const i of [metric, direction, baseline]) i.addEventListener('input', draw);
    metricChoice.onchange = () => { dirty = true; metric.parentElement.hidden = metricChoice.value !== '__custom__'; if (metricChoice.value !== '__custom__') metric.value = metricChoice.value; draw(); }; draw();
  }
  function sourcePreview(project, node_id) { const snapshot = diagram(); return preview('Исходные данные', page => api('/api/data/preview', {project_id: project.meta.id, diagram: snapshot, node_id, page})); }
  async function results(parent, project, data, current) {
    const select = field(parent, 'Запуск', 'select'), list = el('div'); parent.append(list);
    const historyData = await api('/api/pipelines/runs', {project_id: project.meta.id}); if (!current()) return;
    for (const run of historyData.runs) select.append(new Option(date(run.created_at) + ' · ' + (statuses[run.status] || run.status) + ' · ' + run.id.slice(0, 8), run.id));
    let request = 0;
    const load = async () => {
      const token = ++request, run_id = select.value; list.replaceChildren();
      if (!run_id) { list.append(el('p', 'Запустите пайплайн: здесь появятся метрики.')); return; }
      list.append(el('p', 'Загрузка результатов…'));
      try {
        const response = await api('/api/pipelines/assets', {project_id: project.meta.id, run_id}); if (!current() || token !== request) return;
        list.replaceChildren();
        for (const w of response.warnings) list.append(el('p', w));
        const metricAssets = response.assets.filter(a => a.kind === 'metrics' || a.block_kind === 'python_code' && a.port === 'report');
        const summary = {id: run_id, created_at: response.run.created_at, metrics: {}};
        for (const asset of metricAssets) for (const [key, value] of visibleMetrics(asset.metric_summary)) summary.metrics[asset.node_id + '/' + key] = {label: asset.node_name + ' · ' + key, value};
        if (Object.keys(summary.metrics).length) button(list, 'Все метрики запуска', () => plot(summary));
        else if (!metricAssets.length) list.append(el('p', 'В этом запуске пока нет метрик качества.'));
        for (const a of metricAssets) {
          const card = el('article', '', 'insight-card'); card.dataset.kind = a.kind;
          card.append(el('h3', a.node_name + ' · ' + a.label));
          metricCards(card, a.metric_summary, a.block_kind);
          const ref = {project_id: project.meta.id, run_id, node_id: a.node_id, port: a.port};
          const exportValue = async () => { const value = await api('/api/pipelines/asset', {...ref, download: true}); download(value.content, a.node_id + '-' + a.port + '-' + run_id); };
          const controls = el('div', '', 'insight-actions'); card.append(controls);
          button(controls, 'Просмотреть', () => preview(a.label, page => api('/api/pipelines/asset', {...ref, page}), exportValue));
          button(controls, 'Скачать JSON', exportValue);
          list.append(card);
        }
      } catch (e) { if (current() && token === request) list.replaceChildren(el('p', e.message)); }
    };
    select.onchange = load; await load();
  }
  $('overview-tab').onclick = () => open('overview'); $('results-tab').onclick = () => open('results');
  return {open};
};


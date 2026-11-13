'use strict';
window.PipelineDebug = ({api, prepare, selected, currentRun, confirmRun}) => {
  const $ = id => document.getElementById(id);
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  const dialog = el('dialog'); dialog.id = 'debug-dialog'; dialog.className = 'insight-dialog';
  const heading = el('div'); heading.className = 'dialog-heading'; heading.append(el('h2', 'Отладка по шагам'));
  const close = el('button', 'Закрыть'); close.onclick = () => dialog.close(); heading.append(close); dialog.append(heading);
  dialog.append(el('p', 'Выберите блок, проверьте входы и выполните его. Продолжение создаёт новую запись истории и использует неизменившиеся готовые результаты. Просмотр ничего не запускает.'));
  function field(title) { const label = el('label', title), select = el('select'); label.append(select); dialog.append(label); return select; }
  const base = field('Использовать результаты запуска'); base.id = 'debug-base';
  const node = field('Выбранный блок'); node.id = 'debug-node';
  const mode = field('Действие'); mode.id = 'debug-mode'; mode.append(new Option('Выполнить выбранный блок', 'step'), new Option('Продолжить весь пайплайн', 'continue'));
  const refresh = el('button', 'Обновить входы и план'); refresh.id = 'debug-refresh'; dialog.append(refresh);
  const message = el('p'); message.id = 'debug-message'; message.setAttribute('role', 'status'); dialog.append(message);
  const content = el('div'); content.id = 'debug-content'; dialog.append(content);
  const execute = el('button', 'Выполнить блок'); execute.id = 'debug-execute'; execute.className = 'primary'; execute.disabled = true; dialog.append(execute);
  const results = el('section'); results.id = 'debug-results'; dialog.append(results); document.body.append(dialog);
  let request = 0, snapshot = null, plan = null, loading = false;
  dialog.onclose = () => { ++request; snapshot = null; plan = null; };
  function details(parent, title, value) { const d = el('details'); d.append(el('summary', title), el('pre', JSON.stringify(value, null, 2))); parent.append(d); return d; }
  function inspect(parent, title, ref) {
    const wrapper = el('details'); wrapper.append(el('summary', title)); parent.append(wrapper);
    const panel = el('div'); wrapper.append(panel); let loaded = false, revision = 0;
    const load = async page => {
      const serial = ++revision; panel.replaceChildren(el('p', 'Загрузка данных…'));
      try {
        const value = await api('/api/pipelines/asset', {...ref, page}); if (!wrapper.isConnected || serial !== revision) return;
        panel.replaceChildren();
        if (value.profile) {
          panel.append(el('p', `${value.profile.rows} строк · ${value.profile.columns.length} колонок · пропуски и типы — ниже`));
          details(panel, 'Профиль колонок', value.profile.columns);
          const scroll = el('div'); scroll.className = 'insight-scroll'; const table = el('table'); table.className = 'experiments-table'; const head = el('tr');
          for (const c of value.profile.columns) head.append(el('th', c.name)); table.append(head);
          for (const row of value.rows) { const tr = el('tr'); for (const c of value.profile.columns) tr.append(el('td', String(row[c.name] ?? ''))); table.append(tr); }
          scroll.append(table); panel.append(scroll);
          const previous = el('button', '← Предыдущие строки'), next = el('button', 'Следующие строки →');
          previous.disabled = page === 0; next.disabled = (page + 1) * value.page_size >= value.profile.rows;
          previous.onclick = () => load(page - 1); next.onclick = () => load(page + 1); panel.append(previous, next);
        } else {
          panel.append(el('pre', value.text ?? JSON.stringify(value.content ?? value, null, 2)));
          if (value.truncated) panel.append(el('p', 'Предпросмотр сокращён. Полный файл можно скачать в «Данных и результатах».'));
        }
      } catch (e) { if (wrapper.isConnected && serial === revision) panel.replaceChildren(el('p', e.message)); }
    };
    wrapper.ontoggle = () => { if (wrapper.open && !loaded) { loaded = true; load(0); } };
  }
  async function update() {
    const token = ++request; plan = null; execute.disabled = true; content.replaceChildren(); results.replaceChildren(); message.textContent = 'Проверяем схему и сохранённые входы…';
    try {
      const next = await prepare(); if (token !== request || !dialog.open) return;
      if (snapshot && snapshot.project_id !== next.project_id) throw new Error('Открыт другой проект. Закройте отладку и откройте её заново.');
      snapshot = next;
      const debug = {action: mode.value, node_id: node.value, base_run_id: base.value || null};
      const response = await api('/api/pipelines/debug-preview', {...snapshot, debug}); if (token !== request || !dialog.open) return;
      plan = {...response, debug};
      message.textContent = response.blocked.length ? 'Входы ещё не готовы. Сначала выполните указанные ниже блоки.' : response.execute.length ? 'Входы проверены. Запуск потребует подтверждения списка операций.' : 'Все шаги уже готовы. Выберите конкретный блок, если хотите выполнить его заново.';
      content.append(el('h3', 'Что произойдёт'), el('p', 'Выполнить: ' + (response.execute.map(n => n.name).join(' → ') || 'ничего')),
        el('p', 'Использовать готовые результаты: ' + (response.reused.map(n => n.name).join(', ') || 'нет')));
      if (response.remaining.length) content.append(el('p', 'Останется шагов: ' + response.remaining.length));
      for (const b of response.blocked) {
        const row = el('p', b.consumer + ' · вход ' + b.input + ': нужен результат «' + b.name + '». ');
        const pick = el('button', 'Перейти к источнику'); pick.onclick = () => { node.value = b.source_root || b.node_id; mode.value = 'step'; update(); }; row.append(pick); content.append(row);
      }
      if (Object.keys(response.invalidated).length) details(content, 'Почему некоторые результаты нельзя использовать', response.invalidated).open = true;
      content.append(el('h3', 'Входные данные и настройки'));
      content.append(el('p', 'Артефакты передаются ссылками. Для подсхемы показаны её внутренние операции.'));
      for (const input of response.inputs) {
        const section = el('section'); section.className = 'insight-card'; section.append(el('h4', input.name));
        for (const s of input.sources) {
          section.append(el('p', `${s.port} ← ${s.node}.${s.output} · ${s.ready ? 'сохранённый результат' : 'будет получен после выполнения источника'}`));
          if (s.ready) inspect(section, 'Открыть данные входа «' + s.port + '»', {project_id: snapshot.project_id ?? null, run_id: debug.base_run_id, node_id: s.node_id, port: s.output});
        }
        details(section, 'Значения входов', input.inputs).open = true; details(section, 'Настройки', input.settings); content.append(section);
      }
      execute.textContent = mode.value === 'step' ? 'Выполнить блок' : 'Продолжить пайплайн'; execute.disabled = response.blocked.length > 0 || !response.execute.length;
      if (base.value) {
        const record = await api('/api/pipelines/run', {project_id: snapshot.project_id ?? null, run_id: base.value}); if (token !== request || !dialog.open) return;
        results.append(el('h3', 'Сохранённый результат выбранного блока'), el('p', 'Запуск ' + record.id + '. Это результат прежних настроек; новое выполнение создаст отдельную запись.'));
        for (const id of (record.groups?.[node.value] || [node.value])) {
          if (record.nodes[id]?.status !== 'ready') { results.append(el('p', (record.nodes[id]?.name || node.value) + ': готового результата нет.')); continue; }
          const step = await api('/api/pipelines/step', {project_id: snapshot.project_id ?? null, run_id: record.id, node_id: id}); if (token !== request || !dialog.open) return;
          const json = JSON.stringify(step.outputs, null, 2);
          const d = el('details'); d.open = true; d.append(el('summary', record.nodes[id].name), el('pre', json)); results.append(d);
          if (step.reused_from) results.append(el('p', 'Результат повторно использован из запуска ' + step.reused_from.run_id));
          for (const port of Object.keys(step.outputs)) inspect(results, 'Открыть данные выхода «' + port + '»', {project_id: snapshot.project_id ?? null, run_id: record.id, node_id: id, port});
        }
      }
    } catch (error) { if (token === request && dialog.open) { message.textContent = error.message; execute.disabled = true; } }
  }
  async function open() {
    if (loading) return; loading = true;
    try {
      snapshot = await prepare();
      node.replaceChildren(); for (const n of snapshot.diagram.nodes.filter(n => n.block.kind !== 'note')) node.append(new Option(n.name, n.id));
      if (!node.options.length) throw new Error('Добавьте исполняемый блок.');
      if ([...node.options].some(o => o.value === selected())) node.value = selected();
      base.replaceChildren(new Option('Начать без готовых результатов', ''));
      const list = await api('/api/pipelines/runs', {project_id: snapshot.project_id ?? null});
      for (const r of list.runs.filter(r => !['waiting', 'running'].includes(r.status))) base.append(new Option(new Date(r.created_at).toLocaleString() + ' · ' + r.id.slice(0, 8), r.id));
      const id = currentRun()?.id; if ([...base.options].some(o => o.value === id)) base.value = id;
      mode.value = 'step'; dialog.showModal(); await update();
    } catch (e) { alert(e.message); } finally { loading = false; }
  }
  execute.onclick = async () => {
    if (!plan || execute.disabled) return;
    const approved = plan, body = snapshot;
    execute.disabled = true;
    try { await confirmRun({...body, debug: approved.debug, plan_digest: approved.digest}, approved); dialog.close(); }
    catch (e) { message.textContent = e.message; execute.disabled = false; }
  };
  base.onchange = node.onchange = mode.onchange = refresh.onclick = update;
  $('debug-pipeline').onclick = $('debug-node-open').onclick = open;
};


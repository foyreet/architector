'use strict';

window.PythonWorkbench = ({api, node, diagram, context, save, update, pack, download}) => {
  const $ = id => document.getElementById(id);
  const el = (tag, text = '') => { const value = document.createElement(tag); value.textContent = text; return value; };
  let dataNode, dataPage = 0, dataAfter = false, dataResult, dataRequest = 0;
  let codeNode, codeRequest = 0, codeRunning = false, codeSaved = '', codeArtifact;
  function table(container, rows, columns) {
    container.replaceChildren();
    if (!rows.length) { container.append(el('p', 'Нет строк.')); return; }
    columns ||= [...new Set(rows.flatMap(row => Object.keys(row)))];
    const grid = el('table'), head = el('tr');
    for (const name of columns) head.append(el('th', name));
    grid.append(head);
    for (const row of rows) {
      const line = el('tr');
      for (const name of columns) {
        const value = row[name] === null || row[name] === undefined ? '—' : String(row[name]);
        const cell = el('td', value.slice(0, 200)); cell.title = value.slice(0, 2000); line.append(cell);
      }
      grid.append(line);
    }
    container.append(grid);
  }
  function body(id) { return {diagram: diagram(), node_id: id, ...context()}; }
  function codeText() { return JSON.stringify([$('python-code').value, $('python-params').value]); }
  function renderData() {
    const value = dataAfter && dataResult.prepared ? dataResult.prepared : dataResult;
    table($('data-rows'), value.rows, value.profile.columns.map(c => c.name));
    $('data-page').textContent = `Страница ${dataPage + 1} · показано ${value.rows.length} из ${value.profile.rows} строк`;
    $('data-prev').disabled = dataPage === 0;
    $('data-next').disabled = (dataPage + 1) * 50 >= value.profile.rows;
    $('data-before').classList.toggle('primary', !dataAfter); $('data-after').classList.toggle('primary', dataAfter);
  }
  async function loadData(rebuild = true) {
    const request = ++dataRequest;
    dataResult = null; $('data-rows').replaceChildren();
    $('data-status').textContent = 'Чтение входных данных…';
    $('data-apply').disabled = $('data-next').disabled = $('data-prev').disabled = true;
    try {
      const result = await api('/api/data/preview', {...body(dataNode), page: dataPage});
      if (request !== dataRequest || !$('data-dialog').open) return;
      dataResult = result;
      const current = node(dataNode); if (!current) throw new Error('Блок удалён.');
      const editable = current.block.kind === 'ml_prepare';
      $('data-config').hidden = $('data-apply').hidden = !editable;
      const source = result.sources.map(s => {
        if (!s.file) return `${s.node} · результат запуска ${s.finished_at || ''}`;
        return `${s.file}: прочитано ${s.row_count} строк · кодировка ${s.encoding || 'не указана'}` +
          (s.generated_headers?.length ? ` · пустые заголовки названы автоматически: ${s.generated_headers.join(', ')}` : '') +
          (s.truncated ? ' · сохранённый результат содержит только часть файла; выполните CSV заново' : '');
      }).join('; ');
      $('data-status').textContent = `${result.profile.rows} строк · ${result.profile.columns.length} колонок · полных дублей: ${result.profile.duplicates}. ${source}`;
      if (rebuild) {
        $('data-target').replaceChildren(el('option', 'Выберите цель'));
        $('data-target').firstChild.value = '';
        for (const column of result.profile.columns) { const option = el('option', column.name); option.value = column.name; $('data-target').append(option); }
        $('data-target').value = current.block.settings.target || '';
        $('data-missing').value = current.block.settings.missing || 'error';
        $('data-duplicates').value = current.block.settings.duplicates || 'keep';
        const settings = current.block.settings;
        const chosen = (settings.features || '').split(',').map(s => s.trim()).filter(Boolean);
        const excluded = (settings.drop || '').split(',').map(s => s.trim());
        const grid = el('table'), head = el('tr');
        for (const label of ['Признак', 'Колонка', 'Тип', 'Пропуски', 'Уникальных', 'Диапазон / частые значения']) head.append(el('th', label));
        grid.append(head);
        for (const column of result.profile.columns) {
          const row = el('tr'), checkCell = el('td'), check = el('input'); check.type = 'checkbox'; check.dataset.column = column.name;
          check.setAttribute('aria-label', 'Признак ' + column.name);
          check.checked = chosen.length ? chosen.includes(column.name) : column.name !== settings.target && !excluded.includes(column.name);
          check.disabled = !editable || column.name === settings.target;
          checkCell.append(check); row.append(checkCell, el('th', column.name), el('td', column.type === 'number' ? 'Число' : 'Текст'),
            el('td', String(column.missing)), el('td', String(column.unique)), el('td', column.type === 'number' ? `${column.minimum} … ${column.maximum}` : column.common.map(v => `${v.value} (${v.count})`).join(', ')));
          grid.append(row);
        }
        $('data-columns').replaceChildren(grid);
      }
      $('data-after').disabled = !result.prepared;
      $('data-prepared-status').textContent = result.preparation_error || (result.prepared ? `После подготовки: ${result.prepared.profile.rows} строк, ${result.prepared.details.features.length} признаков. Удалено неполных: ${result.prepared.details.dropped_rows}; дублей: ${result.prepared.details.duplicates_removed}.` : '');
      if (!result.prepared) dataAfter = false;
      renderData();
    } catch (error) {
      if (request === dataRequest) { $('data-status').textContent = error.message; $('data-rows').replaceChildren(); }
    } finally { if (request === dataRequest) $('data-apply').disabled = false; }
  }
  $('preview-data').onclick = () => {
    if (!save()) return;
    dataNode = node()?.id; if (!dataNode) return;
    dataPage = 0; dataAfter = false; dataResult = null;
    $('data-columns').replaceChildren(); $('data-rows').replaceChildren(); $('data-prepared-status').textContent = '';
    $('data-config').hidden = $('data-apply').hidden = true; $('data-after').disabled = true;
    $('data-dialog').showModal(); loadData();
  };
  $('data-target').onchange = () => {
    for (const input of $('data-columns').querySelectorAll('input')) {
      input.disabled = input.dataset.column === $('data-target').value;
      if (input.disabled) input.checked = false;
    }
  };
  $('data-apply').onclick = () => {
    const features = [...$('data-columns').querySelectorAll('input:checked:not(:disabled)')].map(input => input.dataset.column);
    if (!features.length) { $('data-prepared-status').textContent = 'Выберите хотя бы один признак.'; return; }
    update(dataNode, {target: $('data-target').value, features: features.join(','), missing: $('data-missing').value, duplicates: $('data-duplicates').value});
    dataPage = 0; dataAfter = true; loadData();
  };
  $('data-before').onclick = () => { if (!dataResult) return; dataAfter = false; renderData(); };
  $('data-after').onclick = () => { if (!dataResult?.prepared) return; dataAfter = true; renderData(); };
  $('data-prev').onclick = () => { dataPage = Math.max(0, dataPage - 1); loadData(false); };
  $('data-next').onclick = () => { dataPage++; loadData(false); };
  $('close-data').onclick = () => $('data-dialog').close();
  $('data-dialog').addEventListener('close', () => { dataRequest++; });

  function applyCode() {
    try {
      const params = JSON.parse($('python-params').value);
      if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error('Параметры должны быть объектом JSON.');
      update(codeNode, {code: $('python-code').value, params: JSON.stringify(params)});
      codeSaved = codeText(); $('python-status').textContent = 'Код сохранён в схеме.'; return true;
    } catch (error) { $('python-status').textContent = error.message; return false; }
  }
  $('open-python-code').onclick = async () => {
    if (!save()) return;
    const current = node(); if (current?.block.kind !== 'python_code') return;
    codeNode = current.id; codeArtifact = null; codeRequest++;
    $('python-code').value = current.block.settings.code;
    try { $('python-params').value = JSON.stringify(JSON.parse(current.block.settings.params), null, 2); }
    catch { $('python-params').value = current.block.settings.params; }
    codeSaved = codeText(); $('python-result').hidden = true; $('python-status').textContent = '';
    $('python-dialog').showModal();
  };

  $('python-code').addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    event.preventDefault(); const field = event.target;
    field.setRangeText('    ', field.selectionStart, field.selectionEnd, 'end'); field.dispatchEvent(new Event('input'));
  });
  for (const id of ['python-code','python-params']) $(id).addEventListener('input', () => {
    codeRequest++; $('python-result').hidden = true; $('python-status').textContent = 'Есть несохранённые изменения.';
  });
  $('python-apply').onclick = applyCode;
  $('python-test').onclick = async () => {
    if (codeRunning || !applyCode()) return;
    const request = ++codeRequest; codeRunning = true; $('python-test').disabled = true; $('python-result').hidden = true;
    $('python-status').textContent = 'Код выполняется в локальном процессе Python…';
    try {
      const result = await api('/api/code/test', body(codeNode));
      if (request !== codeRequest || !$('python-dialog').open) return;
      $('python-report').textContent = JSON.stringify(result.outputs.report, null, 2);
      table($('python-rows'), result.outputs.rows.slice(0, 50));
      $('python-logs').textContent = result.details.logs || 'Нет сообщений.';
      codeArtifact = result.outputs.data;
      $('python-result').hidden = false;
      $('python-status').textContent = `Готово. Выход rows: ${result.outputs.rows.length} строк; показано до 50. Результат data сохранён как артефакт. Для передачи результата по связям запустите пайплайн.`;
    } catch (error) { if (request === codeRequest) $('python-status').textContent = error.message; }
    finally { codeRunning = false; $('python-test').disabled = false; }
  };
  $('python-download').onclick = async () => {
    if (!codeArtifact) return;
    try { download(await api('/api/code/export', {artifact: codeArtifact}), 'python-result'); }
    catch (error) { $('python-status').textContent = error.message; }
  };
  $('python-pack').onclick = () => { if (applyCode()) { $('python-dialog').close(); pack(codeNode); } };
  $('save-python-block').onclick = () => { if (save()) pack(node().id); };
  function closeCode() {
    if (codeText() !== codeSaved && !confirm('Закрыть редактор без сохранения изменений кода?')) return;
    $('python-dialog').close();
  }
  $('close-python').onclick = closeCode;
  $('python-dialog').addEventListener('cancel', event => { event.preventDefault(); closeCode(); });
  $('python-dialog').addEventListener('close', () => { codeRequest++; });
};


'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search), id = params.get('id');
  function page(path, treeId) {
    const url = new URL(path, location.origin);
    if (params.has('project')) url.searchParams.set('project', params.get('project'));
    if (treeId) url.searchParams.set('id', treeId);
    return url;
  }
  $('back').href = id ? page('/problem-space.html', id) : page('/architecture.html');
  $('back').textContent = id ? '← К дереву вопросов' : '← К схеме';
  $('switch-tree').hidden = !id;
  $('switch-tree').href = page('/solution-space.html');
  const labels = {title:'Кейс', validation:'Критерий готовности', rationale:'Почему это нужно', approach:'Возможный подход',
    tradeoffs:'Ограничения и компромиссы', assumptions:'Предположения', business_query:'Запрос по бизнес-задаче', query:'Запрос по технической задаче'};
  const status = text => { $('status').textContent = text; };
  let source, working, proposal, version, dirty = false, generation = 0, busy = false;
  function element(tag, text) {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  }
  async function api(action, data = {}) {
    const response = await fetch('/api/solution-spaces/' + action, {method:'POST',
      headers:{'Content-Type':'application/json','X-Architect-Request':'1'}, body: JSON.stringify({id, ...data})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Ошибка запроса');
    return result;
  }
  function controls() {
    $('generate').disabled = busy || !source?.answers.length;
    $('save').disabled = busy || !dirty;
    $('workspace').inert = busy;
    $('stale').textContent = working && source.revision !== working.source.revision ?
      'Дерево изменилось после подготовки кейсов. Можно запросить новые предложения.' : '';
  }
  function mark() { dirty = true; controls(); }
  function showSources(box, items) {
    box.replaceChildren();
    for (const item of items || []) {
      const block = document.createElement('section');
      const link = element('a', item.title);
      link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      block.append(link, element('small', item.provider + ' · ' + item.outcome));
      for (const [name, text] of [['Бизнесовое сходство',item.business],['Техническое сходство',item.technical],['Что можно применить',item.reuse]]) {
        block.append(element('strong', name), element('p', text));
      }
      if (item.quote) block.append(element('blockquote',item.quote));
      box.append(block);
    }
  }
  function cards(container, plan, editable) {
    container.replaceChildren();
    for (const item of plan.options) {
      const card = document.createElement('article');
      if (editable) card.id = 'case-' + (container.children.length + 1);
      for (const [key, label] of Object.entries(labels)) {
        if (!editable) {
          if (item[key]) card.append(element(key === 'title' ? 'h3' : 'strong', key === 'title' ? item[key] : label));
          if (key !== 'title' && item[key]) card.append(element('p', item[key]));
          continue;
        }
        const field = element('label', label), input = document.createElement('textarea');
        input.rows = ['approach','rationale','tradeoffs'].includes(key) ? 3 : 2;
        input.value = item[key]; input.oninput = () => { item[key] = input.value; mark(); };
        field.append(input); card.append(field);
      }
      const refs = document.createElement('details');
      refs.append(element('summary','На каких ответах основан кейс'));
      for (const i of item.evidence) {
        const a = plan.source.answers[i - 1];
        refs.append(element('strong',a.path.join(' → ')), element('p', a.answer));
      }
      card.append(refs);
      if (editable) {
        const find = element('button','Найти аналоги в интернете'), note = element('p','');
        const sources = document.createElement('div'); sources.className = 'sources';
        note.setAttribute('role','status');
        find.onclick = async () => {
          busy = true; controls(); note.textContent = 'Ищем внедрения, разборы неудач, статьи и реализации…';
          try {
            const data = await api('research', {case:item, source_revision:plan.source.revision});
            if (data.sources.length) {
              const byUrl = new Map((item.sources || []).map(s => [s.url,s]));
              data.sources.forEach(s => byUrl.set(s.url,s));
              item.sources = [...byUrl.values()]; showSources(sources,item.sources); mark();
            }
            note.textContent = (data.sources.length ? 'Найдено источников: ' + data.sources.length : 'Подходящих источников не найдено.') +
              (data.unavailable.length ? ' Недоступны: ' + data.unavailable.join(', ') : '');
          } catch (e) { note.textContent = e.message; }
          finally { busy = false; controls(); }
        };
        card.append(element('p','В поисковые сервисы будут отправлены два запроса выше.'),find,note,sources);
        showSources(sources,item.sources);
      }
      container.append(card);
    }
  }
  function hidePreview() {
    generation++; proposal = null; busy = false;
    $('preview').hidden = $('cancel').hidden = true; controls();
  }
  $('generate').onclick = async () => {
    hidePreview();
    const token = generation;
    busy = true; controls(); $('cancel').hidden = false;
    status('Модель разбирает ответы на кейсы…');
    try {
      const result = await api('generate');
      if (token !== generation) return;
      proposal = result; cards($('proposals'), proposal, false); $('preview').hidden = false;
      status(working ? 'Принятые предложения заменят текущие кейсы. Сохранение отдельной кнопкой.' : 'Проверьте кейсы и их связь с ответами.');
    } catch (e) { if (token === generation) status(e.message); }
    finally { if (token === generation) { busy = false; $('cancel').hidden = true; controls(); } }
  };
  $('cancel').onclick = $('discard').onclick = () => { hidePreview(); status('Предложение отменено.'); };
  $('apply').onclick = () => {
    if (!proposal || busy) return;
    if (working && !confirm('Заменить текущие кейсы и их подборки источников предложенными?')) return;
    working = proposal; source = proposal.source; hidePreview(); cards($('options'), working, true);
    $('workspace').hidden = false; status('Кейсы приняты. Можно искать аналоги и сохранять изменения.'); mark();
  };
  $('save').onclick = async () => {
    busy = true; controls();
    try {
      const result = await api('save', {version, source_revision:working.source.revision, options:working.options});
      version = result.version; dirty = false; status('Кейсы сохранены.');
    } catch (e) { status(e.message); }
    finally { busy = false; controls(); }
  };
  window.addEventListener('beforeunload', e => { if (dirty) e.preventDefault(); });
  async function start() {
    const data = await api('get');
    $('editor').hidden = false;
    source = data.source; version = data.version; working = data.saved;
    $('title').textContent = source.title; $('problem').textContent = source.problem;
    for (const a of source.answers) $('answers').append(element('strong', a.path.join(' → ')),element('p', a.answer));
    if (working) { cards($('options'), working, true); $('workspace').hidden = false; }
    if (!source.answers.length) status('Запишите хотя бы один ответ в дереве, чтобы построить кейсы.');
    controls();
    if (/^#case-\d+$/.test(location.hash)) {
      if (params.has('version') && String(version) !== params.get('version')) status('Подборка кейсов изменилась. Открыта текущая версия.');
      else document.getElementById(location.hash.slice(1))?.scrollIntoView();
    }
  }
  async function library() {
    $('library').hidden = false;
    status('Загрузка деревьев…');
    const {trees} = await api('list');
    status('');
    const list = $('tree-list');
    if (!trees.length) {
      const create = element('a', 'Создать дерево проблем');
      const url = page('/problem-space.html');
      url.searchParams.set('new', '1');
      create.href = url;
      list.append(element('p', 'Пока нет сохранённых деревьев.'), create);
    }
    for (const tree of trees) {
      const link = document.createElement('a');
      link.className = 'document-row';
      link.href = page('/solution-space.html', tree.id);
      link.append(element('strong', tree.title), element('small', tree.has_cases ? 'Есть сохранённые кейсы' : 'Кейсы ещё не созданы'));
      list.append(link);
    }
  }
  (id ? start() : library()).catch(e => status(e.message));
})();

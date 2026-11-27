'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search), id = params.get('id');
  function page(path, treeId) {
    const url = new URL(path, location.origin);
    if (params.has('project')) url.searchParams.set('project', params.get('project'));
    if (path !== '/architecture.html' && (!treeId || !params.get('tree') || treeId === params.get('tree'))) {
      for (const key of ['tree', 'metric', 'doc', 'draft']) {
        if (params.has(key)) url.searchParams.set(key, params.get(key));
      }
    }
    if (treeId) url.searchParams.set('id', treeId);
    return url;
  }
  $('back').href = page('/architecture.html');
  const labels = {title:'Кейс', validation:'Критерий готовности', rationale:'Почему это нужно', approach:'Возможный подход',
    tradeoffs:'Ограничения и компромиссы', assumptions:'Предположения', business_query:'Запрос по бизнес-задаче', query:'Запрос по технической задаче'};
  const status = text => { $('status').textContent = text; };
  // Messages about building cases stay next to the button that starts it.
  const generateNote = text => { $('generate-status').textContent = text; };
  let source, working, proposal, version, dirty = false, generation = 0, busy = false;
  function element(tag, text) {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  }
  async function api(action, data = {}, resource = 'solution-spaces') {
    const response = await fetch('/api/' + resource + '/' + action, {method:'POST',
      headers:{'Content-Type':'application/json','X-Architect-Request':'1'}, body: JSON.stringify({id, ...data})});
    const result = await response.json();
    if (!response.ok) throw Object.assign(Error(result.error || 'Ошибка запроса'), {status: response.status});
    return result;
  }
  window.setupMethodEditor({
    first:'cases',
    load:() => api('method'),
    save:changes => api('save-method', {changes})
  });
  function controls() {
    $('generate').disabled = busy || !source?.answers.length;
    // Once cases exist, regeneration is a secondary action and saving becomes the primary one.
    $('generate').classList.toggle('primary', !working);
    $('save').hidden = !working;
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
  const searchKeys = ['business_query', 'query'];
  function cards(container, plan, editable) {
    container.replaceChildren();
    for (const item of plan.options) {
      const card = document.createElement('article');
      const number = container.children.length + 1;
      if (editable) card.id = 'case-' + number;
      const search = document.createElement('section');
      search.className = 'case-search';
      search.append(element('h4', 'Поиск аналогов'));
      for (const [key, label] of Object.entries(labels)) {
        if (!editable) {
          if (item[key]) card.append(element(key === 'title' ? 'h3' : 'strong', key === 'title' ? item[key] : label));
          if (key !== 'title' && item[key]) card.append(element('p', item[key]));
          continue;
        }
        const field = element('label', label), input = document.createElement('textarea');
        if (key === 'title') {
          const name = element('span', label + ' ' + number), badge = element('span', String(number));
          name.className = 'visually-hidden';
          badge.className = 'step-number';
          badge.setAttribute('aria-hidden', 'true');
          field.className = 'case-title';
          field.replaceChildren(name, badge);
          input.rows = 1;
        } else input.rows = ['approach','rationale','tradeoffs'].includes(key) ? 3 : 2;
        input.value = item[key]; input.placeholder = 'Не заполнено';
        input.oninput = () => { item[key] = input.value; mark(); };
        field.append(input);
        (searchKeys.includes(key) ? search : card).append(field);
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
        note.className = 'search-note';
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
        const hint = element('p','В поисковые сервисы будут отправлены два запроса выше.');
        hint.className = 'search-hint';
        search.append(hint, find, note, sources);
        card.append(search);
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
    generateNote('Модель разбирает ответы на кейсы…');
    try {
      const result = await api('generate');
      if (token !== generation) return;
      proposal = result; cards($('proposals'), proposal, false); $('preview').hidden = false;
      generateNote(working ? 'Принятые предложения заменят текущие кейсы. Сохранение отдельной кнопкой.' : 'Проверьте кейсы и их связь с ответами.');
    } catch (e) { if (token === generation) generateNote(e.message); }
    finally { if (token === generation) { busy = false; $('cancel').hidden = true; controls(); } }
  };
  $('cancel').onclick = $('discard').onclick = () => { hidePreview(); generateNote('Предложение отменено.'); };
  $('apply').onclick = () => {
    if (!proposal || busy) return;
    if (working && !confirm('Заменить текущие кейсы и их подборки источников предложенными?')) return;
    working = proposal; source = proposal.source; hidePreview(); cards($('options'), working, true);
    $('workspace').hidden = false; generateNote('Кейсы приняты. Можно искать аналоги и сохранять изменения.'); mark();
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
    window.designFlow.remember('solutions');
    $('editor').hidden = false;
    source = data.source; version = data.version; working = data.saved;
    $('title').textContent = taskTitle || source.title; $('problem').textContent = source.problem;
    for (const a of source.answers) $('answers').append(element('strong', a.path.join(' → ')),element('p', a.answer));
    if (working) { cards($('options'), working, true); $('workspace').hidden = false; }
    if (!source.answers.length) generateNote('Запишите хотя бы один ответ в дереве, чтобы построить кейсы.');
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
    window.designFlow.remember('solutions');
    const attachDoc = params.has('attach') && params.get('doc');
    const draftTask = params.has('draft') && params.get('doc');
    if (!trees.length || attachDoc || draftTask) {
      const create = element('a', 'Создать дерево проблем');
      const url = page('/problem-space.html');
      url.searchParams.set('new', '1');
      if (attachDoc) url.searchParams.set('attach', '1');
      create.href = url;
      list.append(element('p', attachDoc || draftTask ? 'Для этой задачи выберите сохранённое дерево проблем или создайте новое.' :
        'Пока нет сохранённых деревьев.'), create);
    }
    for (const tree of trees) {
      const link = document.createElement(attachDoc || draftTask ? 'button' : 'a');
      link.className = 'document-row';
      const target = page('/solution-space.html', tree.id);
      if (attachDoc || draftTask) {
        link.onclick = async () => {
          if (list.inert) return;
          list.inert = true;
          try {
            const task = draftTask ? {draft_task:draftTask, companion:params.get('metric')} : {doc:attachDoc};
            await api('attach', {...task, id:tree.id}, 'problem-spaces');
            location.assign(target);
          } catch (error) { status(error.message); list.inert = false; }
        };
      } else link.href = target;
      link.append(element('strong', tree.title), element('small', tree.has_cases ? 'Есть сохранённые кейсы' : 'Кейсы ещё не созданы'));
      list.append(link);
    }
  }
  // A step link may point at a tree that exists only as an unsaved draft: offer the saved ones instead.
  async function fallback(error) {
    if (error.status !== 404) throw error;
    await library();
    status('Это дерево ещё не сохранено. Выберите сохранённое дерево или вернитесь к вопросам.');
  }
  let taskTitle;
  async function openStage() {
    taskTitle = await window.designFlow.taskTitle();
    if (taskTitle) {
      $('title').textContent = taskTitle;
      document.title = taskTitle + ' · ' + document.title;
    }
    if (id) await start().catch(fallback);
    else await library();
  }
  openStage().catch(e => status(e.message));
})();

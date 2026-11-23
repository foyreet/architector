'use strict';
window.setupDesignAssistant = function ({fields, api, read, changed, getId}) {
  const $ = id => document.getElementById(id);
  const dialog = $('design-assist-dialog');
  let refs = {}, token = 0;
  function el(tag, text) {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  }
  function url(path, id) {
    const link = new URL(path, location.origin);
    link.searchParams.set('id', id);
    const project = new URLSearchParams(location.search).get('project');
    if (project) link.searchParams.set('project', project);
    return link;
  }
  function link(text, href) {
    const item = el('a', text);
    item.href = href;
    item.target = '_blank';
    item.rel = 'noopener';
    return item;
  }
  function evidence(ref) {
    const box = el('details', '');
    box.append(el('summary', 'Источники раздела'), link(ref.title + ' · версия ' + ref.revision, url('/problem-space.html', ref.tree_id)));
    for (const a of ref.answers) box.append(el('p', a.path.join(' → ') + ' — ' + a.answer));
    for (const c of ref.cases) {
      const target = url('/solution-space.html', ref.tree_id);
      target.searchParams.set('version', ref.version);
      target.hash = 'case-' + c.id;
      box.append(el('p', 'Кейс из версии ' + ref.version + ' · '), link(c.title, target));
    }
    return box;
  }
  function showRefs() {
    document.querySelectorAll('.section-sources').forEach(box => box.remove());
    for (const [key, ref] of Object.entries(refs)) {
      const input = $('section-' + key);
      if (!input) continue;
      const box = evidence(ref);
      box.className = 'section-sources';
      input.after(box);
    }
  }
  async function checkUpdates() {
    const documentId = getId(), current = refs;
    if (!documentId) return;
    const versions = new Map();
    for (const ref of Object.values(current)) {
      if (!versions.has(ref.tree_id)) versions.set(ref.tree_id, api('get', {id: ref.tree_id}, 'solution-spaces').catch(() => null));
    }
    const stale = [];
    for (const [key, label] of fields) {
      const ref = current[key];
      if (!ref) continue;
      const latest = await versions.get(ref.tree_id);
      if (documentId !== getId() || current !== refs) return;
      const treeChanged = latest && latest.source.revision !== ref.revision &&
        (!ref.answers.length || ref.problem !== latest.source.problem || ref.title !== latest.source.title ||
         ref.answers.some(a => !latest.source.answers.some(b => b.answer === a.answer && JSON.stringify(b.path) === JSON.stringify(a.path))));
      if (!latest || treeChanged || (ref.cases.length && latest.version !== ref.version)) stale.push(label);
    }
    $('source-update').textContent = stale.length ? 'Проверьте источники разделов: ' + stale.join(', ') + '. Можно собрать новый черновик.' : '';
  }
  window.addEventListener('focus', checkUpdates);
  function status(text) { $('assist-status').textContent = text; }
  function open(title) {
    token++;
    $('assist-heading').textContent = title;
    $('assist-content').replaceChildren();
    $('assist-footer').replaceChildren();
    status('');
    dialog.showModal();
    return token;
  }
  function action(text, run) {
    const button = el('button', text);
    $('assist-footer').append(button);
    button.onclick = async () => {
      const active = token;
      button.disabled = true;
      try { await run(); }
      catch (error) { if (active === token) status(error.message); }
      finally { if (active === token) button.disabled = false; }
    };
    return button;
  }
  function check(text, checked) {
    const label = el('label', '');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = checked;
    label.append(input, document.createTextNode(text));
    return {label, input};
  }
  function preview(proposals, initial) {
    const content = $('assist-content'), choices = [];
    content.replaceChildren();
    $('assist-footer').replaceChildren();
    $('assist-heading').textContent = 'Предпросмотр черновика';
    status('Выберите разделы для применения. Заполненные разделы можно заменить по отдельности.');
    for (const [key, name] of fields) {
      const proposal = proposals[key];
      if (!proposal) continue;
      const section = el('section', ''), choice = check(name, !initial.sections[key].trim());
      choices.push([key, choice.input, proposal]);
      section.append(choice.label);
      if (initial.sections[key]) {
        section.append(el('strong', 'Сейчас в документе'), el('p', initial.sections[key]));
      }
      section.append(el('strong', 'Предложение'), el('p', proposal.text), evidence(proposal.source));
      content.append(section);
    }
    action('Применить выбранные разделы', () => {
      const selected = choices.filter(([, input]) => input.checked);
      if (!selected.length) return status('Отметьте хотя бы один раздел.');
      if (selected.some(([key]) => $('section-' + key).value !== initial.sections[key])) {
        return status('Текст изменился после запроса. Откройте новый предпросмотр.');
      }
      refs = {...refs};
      for (const [key, , proposal] of selected) {
        $('section-' + key).value = proposal.text;
        refs[key] = proposal.source;
      }
      showRefs(); changed(); dialog.close(); checkUpdates();
    });
    content.scrollIntoView({block:'start'});
  }
  async function compose() {
    const active = open('Собрать черновик');
    status('Загружаем деревья…');
    const {trees} = await api('list', {}, 'solution-spaces');
    if (token !== active) return;
    const content = $('assist-content');
    if (!trees.length) {
      status('Сначала сохраните дерево в пространстве проблем.');
      content.append(link('Открыть пространство проблем', '/problem-space.html'));
      return;
    }
    const label = el('label', 'Дерево проблем'), select = document.createElement('select');
    select.append(new Option('Выберите дерево', ''));
    trees.forEach(t => select.append(new Option(t.title, t.id)));
    label.append(select);
    const cases = el('fieldset', '');
    cases.hidden = true;
    content.append(label, cases); status('');
    let loaded, sequence = 0;
    const generate = action('Подготовить предложение', async () => {
      if (!loaded) return;
      const initial = read();
      select.disabled = cases.disabled = true;
      status('Модель готовит черновик…');
      try {
        const data = await api('compose', {...initial, tree_id:select.value, revision:loaded.source.revision,
          version:loaded.version, cases:[...cases.querySelectorAll(':checked')].map(c => Number(c.value))});
        if (token === active) preview(data.proposals, initial);
      } finally { select.disabled = cases.disabled = false; }
    });
    generate.disabled = true;
    select.onchange = async () => {
      const step = ++sequence;
      loaded = null; generate.disabled = true;
      cases.hidden = true; cases.replaceChildren(); status('');
      if (!select.value) return;
      status('Загружаем кейсы…');
      try {
        const result = await api('get', {id:select.value}, 'solution-spaces');
        if (step !== sequence || token !== active) return;
        loaded = result;
        const options = result.saved?.options || [];
        cases.append(el('legend','Кейсы для черновика'), el('p', options.length ? 'Оставьте все кейсы пустыми, чтобы использовать только дерево.' : 'Сохранённых кейсов пока нет. Черновик можно собрать из дерева.'));
        const previousCases = Object.values(refs).filter(ref => ref.tree_id === select.value && ref.version === result.version)
          .flatMap(ref => ref.cases.map(c => c.id));
        options.forEach((item, i) => {
          const choice = check(item.title, previousCases.includes(i + 1));
          choice.input.value = i + 1;
          cases.append(choice.label);
        });
        cases.hidden = false; generate.disabled = false;
        status('Дерево · версия ' + result.source.revision + (result.saved ? '. Кейсы · версия ' + result.version + ', по дереву версии ' + result.saved.source.revision : ''));
      } catch (error) { if (step === sequence && token === active) status(error.message); }
    };
    const previous = Object.values(refs)[0]?.tree_id;
    if (trees.some(t => t.id === previous) || trees.length === 1) {
      select.value = trees.some(t => t.id === previous) ? previous : trees[0].id;
      await select.onchange();
    }
  }
  async function review() {
    const active = open('Ревью документа'), draft = read();
    if (!Object.values(draft.sections).some(s => s.trim())) return status('Чтобы провести ревью, заполните хотя бы один раздел.');
    status('Модель читает текущий текст…');
    const {comments} = await api('review', draft);
    if (token !== active) return;
    status(comments.length ? 'Вопросы к текущей версии документа' : 'У модели нет вопросов к этому черновику.');
    for (const comment of comments) {
      const section = el('section', '');
      section.append(el('h3', fields.find(([key]) => key === comment.section)[1]), el('blockquote', comment.quote),
        el('p', comment.reason), el('strong', comment.question));
      $('assist-content').append(section);
    }
  }
  function launch(fn) {
    const pending = fn(), active = token;
    pending.catch(error => { if (active === token) status(error.message); });
  }
  $('compose-doc').onclick = () => launch(compose);
  $('review-doc').onclick = () => launch(review);
  $('assist-close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { token++; });
  return {
    sources: () => refs,
    load(value) {
      refs = value || {};
      $('source-update').textContent = '';
      showRefs(); checkUpdates();
    }
  };
};

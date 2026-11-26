'use strict';
window.setupDesignAssistant = function ({fields, api, read, changed, getId, linksChanged}) {
  const $ = id => document.getElementById(id);
  const dialog = $('design-assist-dialog');
  let refs = {}, links = {}, token = 0;
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
    box.append(el('summary', 'Источники раздела'));
    if (ref.tree_id) box.append(link(ref.title + ' · версия ' + ref.revision, url('/problem-space.html', ref.tree_id)));
    for (const a of ref.answers || []) box.append(el('p', a.path.join(' → ') + ' — ' + a.answer));
    for (const c of ref.cases || []) {
      const target = url('/solution-space.html', ref.tree_id);
      target.searchParams.set('version', ref.version);
      target.hash = 'case-' + c.id;
      box.append(el('p', 'Кейс из версии ' + ref.version + ' · '), link(c.title, target));
    }
    const tree = ref.metric_tree;
    if (tree) {
      box.append(el('p', 'Иерархия метрик'), link(tree.title + ' · версия ' + tree.revision, url('/metric-tree.html', tree.id)));
      if (tree.goal) box.append(el('p', 'Бизнес-цель: ' + tree.goal));
      for (const node of tree.nodes) {
        const details = el('details', '');
        details.append(el('summary', node.path.join(' → ')));
        for (const [key, label] of Object.entries({role:'Роль', definition:'Определение', unit:'Единица',
          direction:'Направление', measurement:'Измерение', relation:'Связь с родителем', check:'Проверка связи'})) {
          if (node[key]) details.append(el('p', label + ': ' + node[key]));
        }
        box.append(details);
      }
    }
    return box;
  }
  function showRefs() {
    document.querySelectorAll('.section-sources').forEach(box => box.remove());
    for (const [key, ref] of Object.entries(refs)) {
      const input = $('section-' + (key === 'data_features' ? 'dataset' : key));
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
    function latest(endpoint, id) {
      const key = endpoint + '/' + id;
      if (!versions.has(key)) versions.set(key, api('get', {id}, endpoint).catch(() => null));
      return versions.get(key);
    }
    const stale = [];
    for (const [key, label] of fields) {
      const ref = current[key];
      if (!ref) continue;
      const [state, metric] = await Promise.all([
        ref.tree_id && latest('solution-spaces', ref.tree_id),
        ref.metric_tree && latest('metric-trees', ref.metric_tree.id)
      ]);
      if (documentId !== getId() || current !== refs) return;
      const treeChanged = state && state.source.revision !== ref.revision &&
        (!ref.answers.length || ref.problem !== state.source.problem || ref.title !== state.source.title ||
         ref.answers.some(a => !state.source.answers.some(b => b.answer === a.answer && JSON.stringify(b.path) === JSON.stringify(a.path))));
      if ((ref.tree_id && (!state || treeChanged || (ref.cases.length && state.version !== ref.version))) ||
          (ref.metric_tree && metric?.revision !== ref.metric_tree.revision)) stale.push(label);
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
  function preview(proposals, initial, selectedLinks) {
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
        section.append(el('strong', 'Сейчас в документе'), window.ChatMarkdown(initial.sections[key]));
      }
      section.append(el('strong', 'Предложение'), window.ChatMarkdown(proposal.text));
      if (Object.keys(proposal.source).length) section.append(evidence(proposal.source));
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
        if (Object.keys(proposal.source).length) refs[key] = proposal.source;
        else delete refs[key];
      }
      links = selectedLinks; linksChanged(links);
      showRefs(); changed(); dialog.close(); checkUpdates();
    });
    content.scrollIntoView({block:'start'});
  }
  async function compose(bindOnly = false) {
    const active = open(bindOnly ? 'Связать этапы задачи' : 'Собрать черновик');
    status('Загружаем деревья…');
    const [problems, metrics] = await Promise.all([api('list', {}, 'solution-spaces'), api('list', {}, 'metric-trees')]);
    if (token !== active) return;
    const content = $('assist-content'), trees = problems.trees;
    function picker(caption, empty, options) {
      const label = el('label', caption), select = document.createElement('select');
      select.append(new Option(empty, ''));
      options.forEach(t => select.append(new Option(t.title, t.id)));
      label.append(select); content.append(label);
      return select;
    }
    const select = picker('Дерево проблем', 'Не использовать', trees);
    const cases = el('fieldset', '');
    cases.hidden = true;
    content.append(cases);
    const metric = picker('Иерархия метрик', 'Не использовать', metrics.trees);
    const metricInfo = el('p', '');
    content.append(metricInfo);
    function restoreChoice(select, options, id) {
      if (!id) return;
      if (!options.some(option => option.id === id)) {
        select.append(new Option('Источник недоступен — выберите замену', id));
        select.lastElementChild.disabled = true;
      }
      select.value = id;
    }
    restoreChoice(metric, metrics.trees, links.metric_tree_id);
    let loaded, sequence = 0;
    const generate = action(bindOnly ? 'Применить связи' : 'Подготовить предложение', async () => {
      const initial = read(), chosen = metrics.trees.find(t => t.id === metric.value);
      const selectedLinks = {};
      if (select.value) selectedLinks.tree_id = select.value;
      if (chosen) selectedLinks.metric_tree_id = chosen.id;
      if (loaded) {
        selectedLinks.case_version = loaded.version;
        selectedLinks.cases = [...cases.querySelectorAll(':checked')].map(c => Number(c.value));
      }
      if (bindOnly) {
        links = selectedLinks; linksChanged(links); changed(); dialog.close();
        return;
      }
      select.disabled = cases.disabled = metric.disabled = true;
      status('Модель готовит черновик…');
      try {
        const data = await api('compose', {...initial, tree_id:select.value, revision:loaded?.source.revision,
          version:loaded?.version, cases:selectedLinks.cases || [],
          metric_tree_id:chosen?.id, metric_revision:chosen?.revision});
        if (token === active) preview(data.proposals, initial, selectedLinks);
      } finally { select.disabled = cases.disabled = metric.disabled = false; }
    });
    function ready() {
      generate.disabled = Boolean((metric.value && !metrics.trees.some(t => t.id === metric.value)) ||
        (select.value && !loaded) || (!bindOnly && !select.value && !metric.value));
    }
    metric.onchange = () => {
      const chosen = metrics.trees.find(t => t.id === metric.value);
      metricInfo.replaceChildren();
      if (chosen) metricInfo.append(link('Открыть дерево · версия ' + chosen.revision, url('/metric-tree.html', chosen.id)));
      else if (!metrics.trees.length) metricInfo.append(link('Создать иерархию метрик', '/metric-tree.html'));
      ready();
    };
    metric.onchange();
    if (!trees.length) content.append(link('Открыть пространство проблем', '/problem-space.html'));
    status(trees.length || metrics.trees.length ? '' : 'Сначала сохраните дерево проблем или иерархию метрик.');
    select.onchange = async () => {
      const step = ++sequence;
      loaded = null; ready();
      cases.hidden = true; cases.replaceChildren(); status('');
      if (!select.value) return;
      status('Загружаем кейсы…');
      try {
        const result = await api('get', {id:select.value}, 'solution-spaces');
        if (step !== sequence || token !== active) return;
        loaded = result;
        const options = result.saved?.options || [];
        cases.append(el('legend','Кейсы для черновика'), el('p', options.length ? 'Отметьте кейсы, которые нужно учесть.' : 'У этого дерева пока нет сохранённых кейсов.'));
        const sameTree = links.tree_id === select.value;
        const previousCases = sameTree && links.case_version === result.version ? (links.cases || []) : [];
        if (sameTree && links.cases?.length && links.case_version !== result.version) {
          cases.append(el('p', 'Версия кейсов изменилась. Выберите нужные кейсы заново.'));
        }
        options.forEach((item, i) => {
          const choice = check(item.title, previousCases.includes(i + 1));
          choice.input.value = i + 1;
          cases.append(choice.label);
        });
        cases.hidden = false; ready();
        status('Дерево · версия ' + result.source.revision + (result.saved ? '. Кейсы · версия ' + result.version + ', по дереву версии ' + result.saved.source.revision : ''));
      } catch (error) { if (step === sequence && token === active) status(error.message); }
    };
    restoreChoice(select, trees, links.tree_id);
    if (select.value) await select.onchange();
    ready();
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
  $('link-task').onclick = () => launch(() => compose(true));
  $('compose-doc').onclick = () => launch(compose);
  $('review-doc').onclick = () => launch(review);
  $('assist-close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { token++; });
  return {
    sources: () => refs,
    taskLinks: () => links,
    load(value, taskLinks) {
      links = taskLinks || {};
      refs = value || {};
      $('source-update').textContent = '';
      showRefs(); checkUpdates();
    }
  };
};

'use strict';

window.problemSpace = function (changed, suggest, metrics = false) {
  const $ = id => document.getElementById(id);
  const levels = ['Общий вопрос', 'Уточнение задачи', 'Технический вопрос'];
  const nameKey = metrics ? 'name' : 'question';
  const headingFor = depth => metrics ? 'Метрика' : levels[depth];
  const canExtend = depth => metrics || depth < 2;
  const fields = metrics ? [
    ['name', 'Название метрики'], ['role', 'Роль'],
    ['definition', 'Определение или формула'], ['unit', 'Единица измерения'], ['direction', 'Направление улучшения'],
    ['measurement', 'Данные и окно измерения'], ['relation', 'Связь с родителем'], ['check', 'Как проверить связь']
  ] : [['question', 'Вопрос'], ['answer', 'Ответ']];
  // Short metric fields are single-line inputs; role and direction offer common values but stay free text.
  const lines = metrics ? {role: ['бизнес', 'онлайн', 'офлайн', 'прокси', 'функция потерь'],
    unit: [], direction: ['больше', 'меньше', 'ближе к целевому значению']} : {};
  for (const [field, values] of Object.entries(lines)) {
    if (!values.length) continue;
    const list = document.createElement('datalist');
    list.id = 'metric-' + field + '-options';
    for (const value of values) list.append(new Option(value));
    document.body.append(list);
  }
  const roles = [['business', 'бизнес'], ['online', 'онлайн'], ['offline', 'офлайн'], ['proxy', 'прокси'], ['loss', 'потер'], ['loss', 'loss']];
  const roleKind = role => {
    const value = (role || '').toLowerCase();
    return (roles.find(([kind, word]) => value.includes(word) || value.includes(kind)) || [''])[0];
  };
  let roots = [], selected = null;
  const viewport = $('tree-viewport'), map = $('tree-map');
  let focusedPath = null, scale = 1;
  function setScale(value) {
    scale = value;
    map.style.zoom = String(scale);
    $('tree-scale').textContent = Math.round(scale * 100) + '%';
  }
  $('tree-smaller').onclick = () => setScale(Math.max(.1, scale / 1.25));
  $('tree-larger').onclick = () => setScale(Math.min(3, scale * 1.25));
  $('tree-fit').onclick = () => {
    setScale(1);
    setScale(Math.min(1, viewport.clientWidth / map.offsetWidth, viewport.clientHeight / map.offsetHeight));
    viewport.scrollTo(0, 0);
  };
  $('tree-all').onclick = () => { focusedPath = null; renderBranches(); revealSelected(); };
  let drag = null;
  viewport.onpointerdown = event => {
    if (event.pointerType !== 'mouse' || event.button !== 0 || event.target.closest('button')) return;
    drag = [event.clientX, event.clientY, viewport.scrollLeft, viewport.scrollTop];
    viewport.setPointerCapture(event.pointerId);
  };
  viewport.onpointermove = event => {
    if (drag) viewport.scrollTo(drag[2] + drag[0] - event.clientX, drag[3] + drag[1] - event.clientY);
  };
  viewport.onpointerup = viewport.onlostpointercapture = () => { drag = null; };
  function revealSelected() {
    const card = map.querySelector('[aria-current=true]');
    if (!card || !viewport.clientWidth) return;
    const rect = card.getBoundingClientRect(), frame = viewport.getBoundingClientRect();
    if (rect.right > frame.right || rect.left < frame.left) viewport.scrollLeft += rect.left - frame.left - 16;
    if (rect.bottom > frame.bottom || rect.top < frame.top) viewport.scrollTop += rect.top - frame.top - 16;
  }
  function updateOrigin() {
    const origin = $('tree-origin');
    const text = $('formulation').value.trim() || $('title').value.trim() || (metrics ? 'Задать бизнес-цель' : 'Сформулировать проблему');
    origin.firstElementChild.textContent = text;
    origin.title = text;
  }
  $('tree-origin').onclick = () => {
    $('root-editor').showModal();
    $('formulation').focus();
  };
  const folded = new Set();
  function question(text, children = []) { return {question: text, answer: '', children}; }
  function button(label, action) {
    const item = document.createElement('button');
    item.type = 'button';
    item.textContent = label;
    item.onclick = action;
    return item;
  }
  let selectionPath = [], generation = 0;
  const ai = $('tree-ai'), target = $('tree-target'), status = $('tree-ai-status');
  let proposal = null;
  function clearProposal() {
    generation++;
    proposal = null;
    $('tree-generate').disabled = false;
    $('tree-proposal').hidden = true;
    $('tree-preview').replaceChildren();
    status.textContent = '';
  }
  function select(item, siblings, depth, focus = false) {
    if (selected !== item && target.value === 'branch') clearProposal();
    selected = item;
    target.options[1].disabled = !canExtend(depth);
    if (!canExtend(depth)) target.value = 'root';
    renderBranches();
    const editor = $('question-editor');
    editor.hidden = !focus;
    editor.replaceChildren();
    const heading = document.createElement('h2');
    heading.textContent = headingFor(depth);
    const close = button('×', () => {
      editor.hidden = true;
      map.querySelector('[aria-current=true]')?.focus();
    });
    close.className = 'inspector-close';
    close.title = 'Закрыть';
    close.setAttribute('aria-label', 'Закрыть');
    const head = document.createElement('div');
    head.className = 'inspector-head';
    head.append(heading, close);
    editor.append(head);
    for (const [field, label] of fields) {
      const wrapper = document.createElement('label');
      wrapper.textContent = label;
      const input = document.createElement(field in lines ? 'input' : 'textarea');
      if (lines[field]?.length) input.setAttribute('list', 'metric-' + field + '-options');
      if (!(field in lines)) input.rows = field === 'answer' ? 4 : 2;
      input.value = item[field];
      input.oninput = () => {
        clearProposal();
        item[field] = input.value;
        renderBranches();
        changed();
      };
      wrapper.append(input);
      editor.append(wrapper);
    }
    const actions = document.createElement('div');
    actions.className = 'actions';
    if (canExtend(depth)) actions.append(button(metrics ? 'Добавить дочернюю метрику' : depth === 0 ? 'Добавить уточнение' : 'Добавить технический вопрос', () => {
      focusedPath = null;
      folded.delete(item);
      add(item.children, depth + 1);
    }));
    if (canExtend(depth)) actions.append(button('Углубить с AI', () => {
      target.value = 'branch';
      showAI(true);
    }));
    if (metrics) {
      const label = document.createElement('label'), move = document.createElement('select');
      label.textContent = 'Перенести ветвь';
      move.append(new Option('Выберите нового родителя', ''));
      const destinations = [];
      function destination(nodes, title, depth) {
        if (nodes !== siblings) {
          destinations.push({nodes, depth});
          move.append(new Option(title, String(destinations.length)));
        }
        for (const child of nodes) {
          if (child !== item) destination(child.children, title + ' → ' + child.name, depth + 1);
        }
      }
      destination(roots, 'Бизнес-цель', 0);
      move.onchange = () => {
        if (!move.value) return;
        const dest = destinations[Number(move.value) - 1];
        clearProposal(); folded.clear(); focusedPath = null;
        siblings.splice(siblings.indexOf(item), 1);
        dest.nodes.push(item);
        select(item, dest.nodes, dest.depth, true); changed();
      };
      label.append(move); editor.append(label);
    }
    const focusBranch = button('Показать только эту ветвь', () => {
      focusedPath = selectionPath.slice();
      renderBranches();
      revealSelected();
      $('tree-all').focus();
    });
    focusBranch.className = 'link-button';
    const remove = button(metrics ? 'Удалить метрику' : 'Удалить вопрос', () => {
      if (!confirm(metrics ? 'Удалить метрику вместе со всей ветвью?' : 'Удалить этот вопрос вместе с его ответом и уточнениями?')) return;
      siblings.splice(siblings.indexOf(item), 1);
      load(roots);
      changed();
      $('add-root').focus();
    });
    remove.className = 'danger-button';
    const footer = document.createElement('div');
    footer.className = 'inspector-footer';
    footer.append(focusBranch, remove);
    editor.append(actions, footer);
    revealSelected();
    if (focus) { const input = editor.querySelector('textarea'); input.focus(); input.select(); }
  }
  function descendants(item) {
    return item.children.reduce((count, child) => count + 1 + descendants(child), 0);
  }
  function renderBranches() {
    const container = $('tree-branches');
    updateOrigin();
    $('tree-all').hidden = !focusedPath;
    container.replaceChildren();
    selectionPath = [];
    function branch(items, path) {
      const list = document.createElement('ul');
      for (const [i, item] of items.entries()) {
        if (focusedPath && path.length < focusedPath.length && i !== focusedPath[path.length]) continue;
        const itemPath = [...path, i], depth = path.length;
        if (item === selected) selectionPath = itemPath;
        const li = document.createElement('li'), row = document.createElement('div');
        row.className = 'branch-row';
        row.dataset.level = depth;
        if (item.children.length) {
          const toggle = button(folded.has(item) ? '+' + descendants(item) : '−', () => {
            if (folded.has(item)) folded.delete(item);
            else {
              if (selectionPath.length > itemPath.length && itemPath.every((v, i) => selectionPath[i] === v)) select(item, items, depth);
              folded.add(item);
            }
            renderBranches();
            container.querySelectorAll('[aria-expanded]')[index].focus();
          });
          const index = toggles++;
          toggle.setAttribute('aria-expanded', String(!folded.has(item)));
          toggle.setAttribute('aria-label', (metrics ? 'Ветвь метрики «' : 'Уточнения к вопросу «') + item[nameKey] + '»');
          row.append(toggle);
        }
        const choose = button(item[nameKey] || headingFor(depth), () => select(item, items, depth, true));
        choose.setAttribute('aria-current', String(item === selected));
        const state = document.createElement('small');
        if (metrics) {
          const kind = roleKind(item.role);
          if (kind) row.dataset.role = kind;
          if (item.role) {
            const chip = document.createElement('span');
            chip.className = 'metric-role';
            chip.textContent = item.role;
            state.append(chip);
          }
          const rest = [item.direction, item.relation].filter(Boolean).join(' · ');
          if (rest) state.append(rest);
        } else {
          const answered = !!item.answer.trim();
          row.dataset.state = answered ? 'answered' : 'open';
          state.textContent = answered ? 'Есть ответ' : 'Без ответа';
        }
        choose.setAttribute('aria-label', item[nameKey] || headingFor(depth));
        if (state.childNodes.length) choose.append(state);
        row.prepend(choose); li.append(row);
        if (item.children.length && !folded.has(item)) li.append(branch(item.children, itemPath));
        list.append(li);
      }
      return list;
    }
    let toggles = 0;
    if (roots.length) container.append(branch(roots, []));
    else container.append(emptyGuide());
    progress();
  }
  // The empty canvas explains the method: broad questions first, then narrower ones.
  function emptyGuide() {
    const guide = document.createElement('div');
    guide.className = 'tree-empty';
    const title = document.createElement('p');
    title.className = 'tree-empty-title';
    title.textContent = metrics ? 'Постройте дерево от бизнес-цели' : 'Сначала вопросы, потом решение';
    const steps = document.createElement('ol');
    const items = metrics ? [
      ['Бизнес-метрика', 'что изменится для компании'],
      ['Онлайн-метрики', 'что видно в работающей системе и A/B-тесте'],
      ['Офлайн-метрики и функция потерь', 'что считаем до внедрения и что минимизирует модель']
    ] : [
      ['Общие вопросы', 'зачем это бизнесу, кто пользователь, что болит сейчас'],
      ['Уточнения', 'как устроен процесс, где он ошибается, сколько стоит ошибка'],
      ['Технические вопросы', 'какие данные есть на момент решения, какие ограничения у системы']
    ];
    for (const [name, text] of items) {
      const li = document.createElement('li');
      const strong = document.createElement('strong');
      strong.textContent = name;
      li.append(strong, document.createTextNode(text));
      steps.append(li);
    }
    const hint = document.createElement('p');
    hint.textContent = metrics
      ? 'Добавьте метрику вручную или попросите AI предложить иерархию.'
      : 'Добавьте общий вопрос вручную или попросите AI предложить первые вопросы.';
    guide.append(title, steps, hint);
    return guide;
  }
  function progress() {
    const output = $('tree-progress');
    if (!output) return;
    let total = 0, done = 0;
    (function count(nodes) {
      for (const node of nodes) {
        total++;
        if (String((metrics ? node.definition : node.answer) || '').trim()) done++;
        count(node.children);
      }
    })(roots);
    output.textContent = !total ? '' : metrics
      ? 'С определением: ' + done + ' из ' + total
      : 'Отвечено: ' + done + ' из ' + total;
  }
  function add(list, depth) {
    const item = metrics
      ? {...Object.fromEntries(fields.map(([key]) => [key, ''])), name: 'Новая метрика', children: []}
      : question(levels[depth]);
    list.push(item);
    select(item, list, depth, true);
    changed();
  }
  function load(nodes) {
    clearProposal();
    focusedPath = null;
    roots = nodes;
    folded.clear();
    if (roots.length) select(roots[0], roots, 0);
    else { selected = null; target.value = 'root'; target.options[1].disabled = true; renderBranches(); $('question-editor').replaceChildren(); }
  }
  $('add-root').onclick = () => { focusedPath = null; add(roots, 0); };
  function preview(items) {
    const list = document.createElement('ul');
    for (const item of items) {
      const li = document.createElement('li');
      li.textContent = item[nameKey];
      if (metrics) {
        const detail = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Описание метрики'; detail.append(summary);
        for (const [key, label] of fields.slice(1)) {
          if (!item[key]) continue;
          const line = document.createElement('p');
          line.textContent = label + ' · ' + item[key]; detail.append(line);
        }
        li.append(detail);
      }
      if (item.children.length) li.append(preview(item.children));
      list.append(li);
    }
    return list;
  }
  function showAI(open) {
    clearProposal();
    ai.hidden = !open;
    $('tree-ai-open').setAttribute('aria-expanded', String(open));
    (open ? $('tree-request') : $('tree-ai-open')).focus();
  }
  $('tree-ai-open').onclick = () => showAI(ai.hidden);
  // Escape closes the side panels; an input with suggestions keeps it for its own list.
  ai.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.target.list) { event.stopPropagation(); showAI(false); }
  });
  $('question-editor').addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.target.list || event.target.tagName === 'SELECT') return;
    event.stopPropagation();
    $('question-editor').hidden = true;
    map.querySelector('[aria-current=true]')?.focus();
  });
  $('tree-cancel').onclick = () => showAI(false);
  target.onchange = clearProposal;
  $('tree-request').oninput = clearProposal;
  $('tree-generate').onclick = async () => {
    clearProposal();
    const request = $('tree-request').value.trim();
    if (!request) {
      status.textContent = 'Опишите задачу для модели.';
      $('tree-request').focus();
      return;
    }
    const id = generation, parent = target.value === 'branch' ? selected : null;
    $('tree-generate').disabled = true;
    status.textContent = metrics ? 'Модель готовит метрики…' : 'Модель готовит вопросы…';
    try {
      const result = await suggest(request, parent ? selectionPath : []);
      if (id !== generation) return;
      proposal = {items: metrics ? result.metrics : result.questions, parent};
      $('tree-preview').append(preview(proposal.items));
      $('tree-proposal').hidden = false;
      status.textContent = metrics ? 'Проверьте определения и связи перед добавлением.' : 'Проверьте вопросы перед добавлением.';
    } catch (error) {
      if (id === generation) status.textContent = error.message;
    } finally {
      if (id === generation) $('tree-generate').disabled = false;
    }
  };
  $('tree-apply').onclick = () => {
    if (!proposal) return;
    const {items, parent} = proposal;
    const destination = parent ? parent.children : roots;
    focusedPath = null;
    if (parent) folded.delete(parent);
    for (const item of items) destination.push(item);
    showAI(false);
    select(items[0], destination, parent ? selectionPath.length : 0, true);
    changed();
  };
  return {
    load(nodes) {
      setScale(1);
      ai.hidden = true;
      $('tree-ai-open').setAttribute('aria-expanded', 'false');
      $('tree-request').value = '';
      load(nodes);
    },
    updateOrigin,
    value: () => roots
  };
};

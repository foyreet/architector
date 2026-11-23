'use strict';

window.problemSpace = function (changed, suggest) {
  const $ = id => document.getElementById(id);
  const levels = ['Общий вопрос', 'Уточнение задачи', 'Технический вопрос'];
  let roots = [], selected = null;
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
    target.options[1].disabled = depth >= 2;
    if (depth >= 2) target.value = 'root';
    renderBranches();
    const editor = $('question-editor');
    editor.replaceChildren();
    const heading = document.createElement('h2');
    heading.textContent = levels[depth];
    editor.append(heading);
    for (const [field, label] of [['question', 'Вопрос'], ['answer', 'Ответ']]) {
      const wrapper = document.createElement('label');
      wrapper.textContent = label;
      const input = document.createElement('textarea');
      input.rows = field === 'answer' ? 4 : 2;
      input.value = item[field];
      input.oninput = () => {
        item[field] = input.value;
        if (field === 'question') renderBranches();
        changed();
      };
      wrapper.append(input);
      editor.append(wrapper);
    }
    const actions = document.createElement('div');
    actions.className = 'actions';
    if (depth < 2) actions.append(button(depth === 0 ? 'Добавить уточнение' : 'Добавить технический вопрос', () => {
      folded.delete(item);
      add(item.children, depth + 1);
    }));
    actions.append(button('Удалить вопрос', () => {
      if (!confirm('Удалить этот вопрос вместе с его ответом и уточнениями?')) return;
      siblings.splice(siblings.indexOf(item), 1);
      load(roots);
      changed();
      $('add-root').focus();
    }));
    editor.append(actions);
    if (focus) { const input = editor.querySelector('textarea'); input.focus(); input.select(); }
  }
  function renderBranches() {
    const container = $('tree-branches');
    container.replaceChildren();
    selectionPath = [];
    function branch(items, path) {
      const list = document.createElement('ul');
      for (const [i, item] of items.entries()) {
        const itemPath = [...path, i], depth = path.length;
        if (item === selected) selectionPath = itemPath;
        const li = document.createElement('li'), row = document.createElement('div');
        row.className = 'branch-row';
        if (item.children.length) {
          const toggle = button(folded.has(item) ? '▸' : '▾', () => {
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
          toggle.setAttribute('aria-label', 'Уточнения к вопросу «' + item.question + '»');
          row.append(toggle);
        }
        const choose = button(item.question || levels[depth], () => select(item, items, depth, true));
        choose.setAttribute('aria-current', String(item === selected));
        row.append(choose); li.append(row);
        if (item.children.length && !folded.has(item)) li.append(branch(item.children, itemPath));
        list.append(li);
      }
      return list;
    }
    let toggles = 0;
    if (roots.length) container.append(branch(roots, []));
  }
  function add(list, depth) {
    const item = question(levels[depth]);
    list.push(item);
    select(item, list, depth, true);
    changed();
  }
  function load(nodes) {
    clearProposal();
    roots = nodes;
    folded.clear();
    if (roots.length) select(roots[0], roots, 0);
    else { selected = null; target.value = 'root'; target.options[1].disabled = true; renderBranches(); $('question-editor').replaceChildren(); }
  }
  $('add-root').onclick = () => add(roots, 0);
  function preview(items) {
    const list = document.createElement('ul');
    for (const item of items) {
      const li = document.createElement('li');
      li.textContent = item.question;
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
    status.textContent = 'Модель готовит вопросы…';
    try {
      const result = await suggest(request, parent ? selectionPath : []);
      if (id !== generation) return;
      proposal = {items: result.questions, parent};
      $('tree-preview').append(preview(proposal.items));
      $('tree-proposal').hidden = false;
      status.textContent = 'Проверьте вопросы перед добавлением.';
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
    if (parent) folded.delete(parent);
    for (const item of items) destination.push(item);
    showAI(false);
    select(items[0], destination, parent ? selectionPath.length : 0, true);
    changed();
  };
  return {
    load(nodes) {
      ai.hidden = true;
      $('tree-ai-open').setAttribute('aria-expanded', 'false');
      $('tree-request').value = '';
      load(nodes);
    },
    value: () => roots
  };
};

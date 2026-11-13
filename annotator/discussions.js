'use strict';
window.Discussions = ({api}) => {
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  const call = (action, body) => api('/api/community/' + action, body);
  async function mount(parent, target, attachment = null, selectedNode = '') {
    const section = el('section'); section.className = 'insight-card discussion'; parent.append(section);
    section.append(el('h4', 'Обсуждение'));
    const status = el('p', 'Загрузка…'); status.setAttribute('role', 'status'); section.append(status);
    try {
      const data = await call('comments', target); if (!section.isConnected) return;
      status.textContent = data.audience;
      const list = el('div'); section.append(list);
      const render = comments => {
        list.replaceChildren();
        if (!comments.length) list.append(el('p', 'Комментариев пока нет.'));
        for (const c of comments) {
          const item = el('article'); item.className = 'discussion-comment';
          item.append(el('small', '@' + c.username + ' · ' + new Date(c.created * 1000).toLocaleString()));
          if (c.context.node) item.append(el('strong', 'Блок: ' + c.context.node.name));
          item.append(el('p', c.message));
          if (c.context.result) {
            const r = c.context.result;
            item.append(el('p', `Результат: ${r.project} / ${r.node} / ${r.port} · запуск ${r.run_id}`));
            const details = el('details'); details.append(el('summary', 'Снимок метрик и ссылки на артефакт'), el('pre', JSON.stringify(r, null, 2))); item.append(details);
          }
          list.append(item);
        }
      }; render(data.comments);
      const label = el('label', 'К чему относится комментарий'), nodes = el('select');
      nodes.append(new Option('Общее обсуждение', ''));
      for (const n of data.nodes) nodes.append(new Option(n.name, n.id));
      nodes.value = data.nodes.some(n => n.id === selectedNode) ? selectedNode : '';
      label.append(nodes); section.append(label);
      if (attachment) section.append(el('p', 'При отправке участникам этого обсуждения будут доступны номер запуска, название проекта, метрики и ссылка на артефакт. Файлы, строки датасета и журнал не передаются.'));
      const textLabel = el('label', 'Комментарий'), text = el('textarea'); text.rows = 3; textLabel.append(text); section.append(textLabel);
      const send = el('button', 'Отправить комментарий'); section.append(send);
      send.onclick = async () => {
        if (!text.value.trim()) { status.textContent = 'Введите комментарий.'; return; }
        send.disabled = true;
        try { const response = await call('comment', {...target, node_id: nodes.value, message: text.value, ...(attachment ? {result: attachment} : {})}); if (section.isConnected) { render(response.comments); text.value = ''; status.textContent = response.audience; } }
        catch (e) { status.textContent = e.message; } finally { send.disabled = false; }
      };
    } catch (e) { status.textContent = e.message; }
  }
  async function open(project_id, {result = null, node_id = ''} = {}) {
    const dialog = el('dialog'); dialog.className = 'insight-dialog';
    const close = el('button', 'Закрыть'), content = el('div'), status = el('p', 'Загрузка…');
    close.onclick = () => dialog.close(); const heading = el('div'); heading.className = 'dialog-heading'; heading.append(el('h2', 'Обсуждение'), close); dialog.append(heading, status, content); document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove()); dialog.showModal();
    try {
      const {targets} = await call('discussion-targets', {project_id}); if (!dialog.open) return;
      const label = el('label', 'Где обсуждать'), select = el('select'); targets.forEach((t, i) => select.append(new Option(t.label, i))); label.append(select); status.replaceWith(label);
      const show = () => { content.replaceChildren(); mount(content, targets[Number(select.value)], result, node_id); };
      select.onchange = show; show();
    } catch (e) { status.textContent = e.message; }
  }
  return {mount, open};
};


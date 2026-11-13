'use strict';
window.CodexChat = ({api, account, project, diagram, flush, fit, applyProposal}) => {
  const $ = id => document.getElementById(id);
  const screen = $('codex-chat'), field = $('codex-message');
  // Desktop grid keeps the chat below the full-width project header.
  document.querySelector('.workspace-main').append(screen);
  if (window.DeviceUI?.mobile) {
    field.placeholder = 'Опишите схему или задайте вопрос…';
    $('codex-pending').textContent = 'AI готовит ответ…';
  }
  function viewportMode() {
    const keyboard = !!window.DeviceUI?.mobile && screen.open && (window.visualViewport?.height || innerHeight) < 540;
    const compact = keyboard || (!window.DeviceUI?.mobile && screen.open && screen.clientHeight < 500);
    if (document.body.classList.contains('chat-compact') !== compact) $('codex-settings').open = !compact;
    document.body.classList.toggle('chat-compact', compact);
    document.body.classList.toggle('chat-keyboard', keyboard);
  }
  window.visualViewport?.addEventListener('resize', viewportMode);
  window.addEventListener('resize', viewportMode);
  const drafts = new Map();
  const attachmentDrafts = new Map();
  let uploading = false;
  const attachments = () => attachmentDrafts.get(scope) || [];
  function renderAttachments() {
    $('codex-attachments').replaceChildren();
    for (const item of attachments()) {
      const row = document.createElement('div'); row.className = 'codex-attachment';
      const label = document.createElement('span'); label.textContent = item.name; label.title = item.name;
      const size = document.createElement('small'); size.textContent = (item.size / 1024 / 1024).toFixed(1) + ' МиБ';
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Удалить файл ' + item.name);
      remove.disabled = uploading || sending || pending;
      remove.onclick = async () => {
        const identity = scope, selected = body(); remove.disabled = true;
        try {
          await api('/api/codex/remove-attachment', {...selected, attachment_id: item.id});
          attachmentDrafts.set(identity, (attachmentDrafts.get(identity) || []).filter(a => a.id !== item.id));
          if (scope === identity) { renderAttachments(); controls(); }
        } catch (e) { if (scope === identity) { error(e.message); renderAttachments(); } }
      };
      row.append(label, size, remove); $('codex-attachments').append(row);
    }
  }
  let designState={document:null,version:0},designBusy=false;
  function renderDesign(value) {
    if(value.version<designState.version)return;
    designState=value;const doc=value.document;$('codex-design').hidden=!doc;
    $('codex-design-title').textContent=doc?'📄 '+doc.title:'';
    $('codex-design-title').title=doc?.title||'';
    $('codex-design-state').textContent=!doc?'':value.unavailable?'Источник недоступен. Используется прикреплённая версия.':value.changed?'Документ изменён · Обновите, чтобы использовать правки':doc.source_type==='release'?'Публикация · версия '+doc.revision:'Прикреплённая версия';
    $('codex-design-update').hidden=!doc||doc.source_type==='release';controls();
  }
  $('codex-design-read').onclick=()=>{if(designState.document)window.DesignChat.read(designState.document);};
  async function changeDesign(action){
    const token=generation,selected=body(),version=designState.version;
    designBusy=true;controls();error();
    try{const value=await api('/api/codex/design-'+action,{...selected,design_version:version});if(token===generation)renderDesign(value);}
    catch(e){if(token===generation){error(e.message);await refresh();}}
    finally{designBusy=false;controls();}
  }
  $('codex-design-update').onclick=()=>changeDesign('update');$('codex-design-remove').onclick=()=>changeDesign('remove');
  $('codex-attach').setAttribute('aria-controls','codex-attach-menu');$('codex-attach').setAttribute('aria-expanded','false');
  const closeAttach=()=>{$('codex-attach-menu').hidden=true;$('codex-attach').setAttribute('aria-expanded','false');};
  $('codex-attach').onclick=()=>{const hidden=!$('codex-attach-menu').hidden;$('codex-attach-menu').hidden=hidden;$('codex-attach').setAttribute('aria-expanded',String(!hidden));};
  $('codex-attach-file').onclick=()=>{closeAttach();$('codex-file').click();};
  $('codex-attach-design').onclick=()=>{
    closeAttach();const token=generation,identity=scope,selected=body();
    window.DesignChat.choose(api,async source=>{
      if(token!==generation||identity!==key())throw Error('Чат изменился. Выберите документ заново.');
      designBusy=true;controls();
      try{const value=await window.DesignChat.attach(api,selected,source);if(token===generation&&value)renderDesign(value);return value;}
      finally{designBusy=false;controls();}
    });
  };
  $('codex-file').onchange = async () => {
    const files = Array.from($('codex-file').files || []); $('codex-file').value = '';
    if (!files.length) return;
    if (files.some(file => !file.size)) { error('Прикрепите непустой документ.'); return; }
    const identity = scope, selected = body(), token = generation;
    uploading = true; error(); controls(); renderAttachments();
    $('codex-upload-status').hidden = false; $('codex-upload-status').textContent = 'Подготовка документа…';
    try {
      for (const file of files) {
        if (token !== generation) break;
        const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = () => reject(new Error('Не удалось прочитать файл.')); reader.readAsDataURL(file); });
        const item = await api('/api/codex/upload', {...selected, name: file.name, data});
        if (token !== generation) break;
        attachmentDrafts.set(identity, [...(attachmentDrafts.get(identity) || []), item]);
        if (identity === scope) renderAttachments();
      }
    } catch (e) { if (scope === identity) error(e.message); }
    finally { uploading = false; $('codex-upload-status').hidden = true; renderAttachments(); controls(); }
  };
  const appliedProposals = new Map();
  const staleProposals = new Set(), proposalViews = new Set();
  window.addEventListener('architect-diagram-change', () => { for (const update of proposalViews) update(); });
  let scope = '', generation = 0, timer, connected = false, pending = false, sending = false;
  let login = null, rendered = '', opening = false;
  const body = () => project() ? {project_id: project().meta.id} : {};
  const key = () => (account.user?.id || '-') + ':' + (project()?.meta.id || 'general');
  function error(message = '') { $('codex-error').textContent = message; $('codex-error').hidden = !message; }
  const modelSelect = $('codex-model'), effortSelect = $('codex-effort');
  let preferenceKey = '';
  const settingsKey = () => 'opensource.codex.settings.' + (account.user?.id || 'guest');
  let models = [], modelsLoaded = false, modelsLoading = false, modelsFailed = false;
  let preferences = {};
  function readPreferences() {
    preferenceKey = settingsKey(); preferences = {};
    try { const value = JSON.parse(localStorage.getItem(preferenceKey) || '{}'); if (value && typeof value === 'object' && !Array.isArray(value)) preferences = value; } catch {}
  }
  readPreferences();
  const effortLabels = {none: 'Без рассуждения', minimal: 'Минимальный', low: 'Низкий', medium: 'Средний', high: 'Высокий', xhigh: 'Очень высокий', max: 'Максимальный', ultra: 'Предельный'};
  function savePreferences() {
    preferences = {model: modelSelect.value, effort: effortSelect.value};
    try { localStorage.setItem(preferenceKey, JSON.stringify(preferences)); } catch {}
  }
  function renderEfforts(wanted = '') {
    const selected = models.find(m => m.id === modelSelect.value) || (!modelSelect.value && models.find(m => m.default));
    effortSelect.replaceChildren(new Option(selected?.default_effort ? 'По умолчанию · ' + (effortLabels[selected.default_effort] || selected.default_effort) : 'По умолчанию', ''));
    for (const effort of selected?.efforts || []) effortSelect.append(new Option(effortLabels[effort] || effort, effort));
    effortSelect.value = selected?.efforts.includes(wanted) ? wanted : '';
    controls();
  }
  function modelNotice(text = '') {
    $('codex-model-status').textContent = text;
    $('codex-model-notice').hidden = !text;
  }
  async function loadModels() {
    if (modelsLoading || !connected) return;
    modelsLoading = true; modelsFailed = false; controls();
    const identity = settingsKey();
    try {
      const value = await api('/api/codex/models', body());
      if (identity !== settingsKey() || !connected) return;
      models = value.models || []; modelsLoaded = true;
      const wanted = modelSelect.value || preferences.model || '';
      modelSelect.replaceChildren(new Option('Настроенная модель', ''));
      for (const model of models) modelSelect.append(new Option(model.name, model.id));
      if (wanted && !models.some(m => m.id === wanted)) modelSelect.append(new Option('Недоступна: ' + wanted, wanted));
      modelSelect.value = wanted;
      renderEfforts(preferences.effort);
      modelNotice(wanted && !models.some(m => m.id === wanted) ? 'Выберите другую модель: прежней нет в каталоге.' : !models.length ? 'Список моделей пуст. Проверьте настройки подключения.' : '');
    } catch (e) {
      if (identity !== settingsKey()) return;
      modelsFailed = true; modelNotice('Не удалось загрузить модели. Повторите или выберите настройки по умолчанию.');
    } finally { modelsLoading = false; controls(); }
  }
  if (typeof preferences.model === 'string' && preferences.model) {
    modelSelect.append(new Option(preferences.model, preferences.model)); modelSelect.value = preferences.model;
  }
  modelSelect.onchange = () => { renderEfforts(effortSelect.value); savePreferences(); modelNotice(); };
  effortSelect.onchange = savePreferences;
  $('codex-model-retry').onclick = () => { modelsLoaded = false; loadModels(); };

  const speechAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  const Recognition = window.isSecureContext && typeof speechAPI === 'function' ? speechAPI : null;
  let recognition = null, listening = false;
  function voiceStatus(text = '') { $('codex-voice-status').textContent = text; $('codex-voice-status').hidden = !text; }
  function voiceControls() {
    const mic = $('codex-voice');
    mic.hidden = !Recognition;
    mic.textContent = listening ? '■ Стоп' : '🎙 Голос';
    mic.setAttribute('aria-label', listening ? 'Остановить диктовку' : 'Начать диктовку');
    mic.setAttribute('aria-pressed', String(listening));
    mic.disabled = !Recognition || (!listening && (sending || pending));
    field.readOnly = listening;
  }
  function abortVoice() {
    const active = recognition; recognition = null; listening = false;
    if (active) { try { active.abort(); } catch {} }
    if (Recognition) voiceStatus();
    voiceControls(); controls();
  }
  if (!Recognition) voiceStatus(window.isSecureContext
    ? 'Диктовка в этой версии браузера недоступна. Введите текст или используйте системную диктовку.'
    : 'Для диктовки откройте сайт по HTTPS. Пока можно ввести текст с клавиатуры.');
  $('codex-voice').onclick = () => {
    if (recognition) {
      voiceStatus('Завершаю диктовку…');
      try { recognition.stop(); } catch { abortVoice(); }
      return;
    }
    if (!Recognition || sending || pending) return;
    let current;
    try { current = new Recognition(); } catch { voiceStatus('Не удалось включить диктовку в этом браузере.'); return; }
    const identity = scope, prefix = field.value.trimEnd();
    recognition = current; listening = true;
    current.lang = 'ru-RU'; current.continuous = true; current.interimResults = true;
    const valid = () => recognition === current && identity === scope && screen.open;
    current.onstart = () => { if (valid()) voiceStatus('Слушаю… Нажмите «Стоп», когда закончите.'); };
    current.onresult = event => {
      if (!valid()) return;
      let final = '', interim = '';
      for (const result of event.results) {
        if (result.isFinal) final += result[0].transcript + ' ';
        else interim += result[0].transcript + ' ';
      }
      const value = [prefix, final.trim()].filter(Boolean).join(' ');
      field.value = value; drafts.set(identity, field.value);
      voiceStatus(interim.trim() || 'Слушаю… Нажмите «Стоп», когда закончите.');
    };
    current.onerror = event => {
      if (!valid()) return;
      const messages = {'not-allowed': 'Разрешите доступ к микрофону в настройках сайта.', 'service-not-allowed': 'Сервис диктовки недоступен в этом браузере. Используйте системную диктовку или введите текст.', 'audio-capture': 'Микрофон недоступен. Проверьте подключение и разрешения.', 'no-speech': 'Речь не распознана. Попробуйте ещё раз.', network: 'Сервис диктовки не ответил. Проверьте подключение или введите текст с клавиатуры.', 'language-not-supported': 'Браузер не поддерживает диктовку на русском.'};
      abortVoice(); voiceStatus(messages[event.error] || 'Диктовка остановлена. Можно продолжить ввод с клавиатуры.');
    };
    current.onend = () => {
      if (!valid()) return;
      recognition = null; listening = false; voiceControls(); controls();
      voiceStatus('Диктовка завершена. Проверьте текст перед отправкой.');
      field.focus({preventScroll: true});
    };
    voiceStatus('Подключаю микрофон…'); voiceControls(); controls();
    try {
      current.start();
    } catch { abortVoice(); voiceStatus('Не удалось включить микрофон. Проверьте разрешения браузера.'); }
  };
  document.addEventListener('visibilitychange', () => { if (document.hidden && listening) { abortVoice(); voiceStatus('Диктовка остановлена.'); } });
  window.addEventListener('pagehide', abortVoice);
  function controls() {
    screen.classList.toggle('codex-ready', connected);
    $('codex-send').disabled = !connected || pending || sending || uploading || designBusy || listening || modelsLoading || (modelSelect.value && !models.some(m => m.id === modelSelect.value)) || !field.value.trim();
    $('codex-connect').disabled = opening || !!login;
    $('codex-attachments').querySelectorAll('button').forEach(button => button.disabled = pending || sending || uploading);
    $('codex-attach').disabled = !account.user || pending || sending || uploading || designBusy;
    $('codex-attach-file').disabled = !connected;
    for(const id of ['codex-design-update','codex-design-remove'])$(id).disabled=pending||sending||uploading||designBusy;
    $('codex-attach-design').disabled = pending||sending||uploading||designBusy;
    $('codex-clear').disabled = pending || sending || uploading;
    $('codex-disconnect').disabled = pending || sending || uploading;
    $('codex-pending').hidden = !pending;
    modelSelect.disabled = !connected || modelsLoading || sending || pending;
    effortSelect.disabled = !connected || modelsLoading || sending || pending || effortSelect.options.length < 2;
    $('codex-model-retry').disabled = modelsLoading || !connected;
    voiceControls();
  }
  let setupPrompted = false;
  const setup = window.AIConnection({api, changed: async () => { modelsLoaded=false; modelsLoading=false; modelsFailed=false; await refresh(); }});
  function renderStatus(status) {
    connected = status.connected === true;
    if (!connected) { modelsLoaded = false; modelsFailed = false; models = []; }
    if (connected && !modelsLoaded && !modelsLoading && !modelsFailed) loadModels();
    login = status.login || null;
    screen.classList.toggle('codex-auth', !!login);
    $('codex-connect').hidden = false;
    $('codex-connect').textContent = connected ? 'Настроить AI' : !status.available ? 'Как подключить' : 'Подключить AI';
    if((status.provider==='none' || !status.available) && !setupPrompted){setupPrompted=true;setup.open();}
    $('codex-disconnect').hidden = !connected && !login;
    $('codex-disconnect').textContent = login ? 'Отменить вход' : 'Отключить';
    $('codex-connection').textContent = !status.available ? 'Для входа через ChatGPT нужно подготовить подключение.' : connected ? (status.label || 'Codex') + (status.endpoint ? ' · ' + status.endpoint : ' подключён') : login ? 'Завершите вход на странице OpenAI' : 'Подключите свою модель';
    $('codex-login').hidden = !login;
    $('codex-login-code').textContent = login?.code || '';
    if (login?.url === 'https://auth.openai.com/codex/device') $('codex-login-link').href = login.url;
    else $('codex-login-link').removeAttribute('href');
    if (status.login_error) error('Вход не завершён. Попробуйте подключить Codex ещё раз.');
    controls();
  }
  function proposalCard(proposal) {
    const card = document.createElement('section'); card.className = 'codex-proposal';
    card.setAttribute('aria-label', 'Изменения схемы');
    const title = document.createElement('h3'); title.textContent = 'Изменения схемы';
    const name = document.createElement('p'); name.className = 'muted'; name.textContent = proposal.name;
    const counts = {added: 0, changed: new Set(), removed: 0, links: 0};
    for (const change of proposal.changes) {
      if (change.path[1] === 'nodes') {
        if (change.path.length === 3 && change.action === 'added') counts.added++;
        else if (change.path.length === 3 && change.action === 'removed') counts.removed++;
        else counts.changed.add(change.path[2]);
      } else if (change.path[1] === 'edges') counts.links++;
    }
    const summary = document.createElement('p'); summary.textContent = [
      counts.added && `Добавлено блоков: ${counts.added}`, counts.changed.size && `Изменено блоков: ${counts.changed.size}`,
      counts.removed && `Удалено блоков: ${counts.removed}`, counts.links && `Изменено связей: ${counts.links}`
    ].filter(Boolean).join(' · ');
    const details = document.createElement('details'), label = document.createElement('summary');
    label.textContent = 'Посмотреть изменения'; details.append(label);
    for (const change of proposal.changes) {
      const row = document.createElement('div'), heading = document.createElement('strong'), value = document.createElement('pre');
      heading.textContent = ({added: 'Добавлено: ', removed: 'Удалено: ', changed: 'Изменено: '}[change.action] || '') + change.label;
      const format = item => item === null ? '—' : typeof item === 'string' ? item : JSON.stringify(item, null, 2);
      value.textContent = format(change.display_before) + '\n→\n' + format(change.display_after);
      row.append(heading, value); details.append(row);
    }
    const note = document.createElement('p'); note.className = 'codex-proposal-note';
    note.textContent = proposal.validation?.ready ? 'Готово к применению. Выполнение не запускалось.' :
      'До запуска потребуется настройка: ' + (proposal.validation?.note || 'проверьте блоки');
    const status = document.createElement('p'); status.setAttribute('role', 'status');
    const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'primary';
    const undo = document.createElement('button'); undo.type = 'button'; undo.textContent = 'Отменить изменения';
    const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Обновить предложение'; retry.hidden = true;
    const identity = scope, proposalKey = identity + ':' + proposal.id;
    function state() {
      const phase = appliedProposals.get(proposalKey)?.status();
      const applied = phase && phase !== 'undone', stale = staleProposals.has(proposalKey);
      apply.textContent = applied ? 'Применено' : 'Применить к схеме';
      apply.disabled = !!applied || stale || identity !== key() || proposal.project_id !== (project()?.meta.id || null);
      undo.hidden = phase !== 'applied';
      retry.classList.toggle('primary', stale);
      if (phase === 'undone') status.textContent = 'Изменения отменены.';
      else if (phase === 'applied') status.textContent = 'Изменения применены к схеме.';
      else if (phase === 'changed') status.textContent = 'После применения схема изменилась. Для отмены используйте ↶ на полотне.';
      if (stale) { retry.hidden = false; status.textContent = 'Схема изменилась после запроса. Обновите предложение.'; }
    }
    proposalViews.add(state);
    state();
    apply.onclick = async () => {
      if (apply.disabled) return;
      const token = generation, snapshot = diagram(), signature = JSON.stringify(snapshot);
      apply.disabled = true; status.textContent = 'Проверяем изменения…'; retry.hidden = true;
      try {
        if (scope !== identity || key() !== identity) throw new Error('Откройте проект, для которого подготовлено предложение.');
        if (project()) await flush();
        if (token !== generation || key() !== identity) return;
        const result = await api('/api/codex/proposal', {...body(), proposal_id: proposal.id, diagram: snapshot});
        if (token !== generation || key() !== identity) return;
        if (JSON.stringify(diagram()) !== signature) throw new Error('Схема изменилась во время проверки. Запросите новое предложение.');
        appliedProposals.set(proposalKey, applyProposal(result));
        status.textContent = 'Изменения применены к схеме.';
      } catch (e) {
        if (token !== generation) return;
        if (e.status === 409 || e.message.startsWith('Схема изменилась')) staleProposals.add(proposalKey);
        status.textContent = e.message; retry.hidden = false;
      } finally { state(); }
    };
    undo.onclick = () => {
      try {
        if (key() !== identity) throw new Error('Откройте исходный проект для отмены.');
        appliedProposals.get(proposalKey).undo();
        status.textContent = 'Изменения отменены.'; state();
      } catch (e) { status.textContent = e.message; }
    };
    retry.onclick = () => {
      field.value = 'Обнови последнее предложение с учётом текущей схемы. Сохрани мои ручные изменения.';
      $('codex-include-context').checked = true; drafts.set(scope, field.value); controls(); field.focus();
    };
    card.append(title, name, summary, details, note, status, apply, undo, retry);
    return card;
  }
  function renderHistory(record) {
    pending = !!record.pending;
    screen.classList.toggle('codex-has-history', !!record.messages.length || pending);
    const fingerprint = JSON.stringify(record.messages);
    if (rendered !== fingerprint) {
      rendered = fingerprint;
      proposalViews.clear();
      $('codex-messages').replaceChildren();
      for (const message of record.messages) {
        const article = document.createElement('article'); article.className = 'codex-bubble ' + (message.role === 'user' ? 'user' : 'assistant');
        const label = document.createElement('strong'); label.className = 'codex-author'; label.textContent = message.role === 'user' ? 'Вы' : 'AI';
        const text = message.role === 'user' ? document.createElement('p') : window.ChatMarkdown(message.text);
        if (message.role === 'user') text.textContent = message.text;
        article.append(label, text);
        for (const item of message.attachments || []) {
          const file = document.createElement('div'); file.className = 'codex-sent-attachment'; file.textContent = '📎 ' + item.name; article.append(file);
        }
        if(message.design_document){const note=document.createElement('div');note.className='codex-sent-attachment';note.textContent='📄 '+message.design_document.title+' · версия '+message.design_document.revision;article.append(note);}
        if (message.proposal) article.append(proposalCard(message.proposal));
        $('codex-messages').append(article);
      }
      $('codex-empty').hidden = record.messages.length > 0;
      $('codex-transcript').scrollTop = $('codex-transcript').scrollHeight;
    }
    if (record.error) error(record.error);
    controls();
  }
  function schedule() {
    clearTimeout(timer);
    if (screen.open) timer = setTimeout(refresh, login || pending ? 1800 : 8000);
  }
  async function refresh() {
    if (!screen.open) return;
    if (scope !== key()) return open();
    const token = generation;
    try {
      const [status, history, design] = await Promise.all([api('/api/codex/status', body()), api('/api/codex/history', body()),api('/api/codex/design-get',body())]);
      if (token !== generation || !screen.open) return;
      renderStatus(status); renderHistory(history);renderDesign(design);
    } catch (e) {
      if (token !== generation) return;
      connected = false; controls(); error(e.message);
      $('codex-connection').textContent = 'Не удалось проверить подключение AI';
    } finally { if (token === generation) schedule(); }
  }
  async function open() {
    if (preferenceKey !== settingsKey()) {
      readPreferences(); models = []; modelsLoaded = false; modelsFailed = false;
      modelSelect.replaceChildren(new Option('Настроенная модель', ''));
      if (typeof preferences.model === 'string' && preferences.model) { modelSelect.append(new Option(preferences.model, preferences.model)); modelSelect.value = preferences.model; }
      renderEfforts();
    }
    if (listening) abortVoice();
    document.body.classList.add('chat-open');
    $('codex-chat-open').setAttribute('aria-expanded', 'true');
    if (!screen.open) {
      screen.show(); $('codex-chat-close').focus({preventScroll: true});
      // Wide desktop already reserves this space; keep the user's camera untouched.
      if (!getComputedStyle(document.body).getPropertyValue('--workspace-chat-slot').trim()) {
        requestAnimationFrame(() => fit?.());
      }
    }
    viewportMode();
    drafts.set(scope, field.value);
    scope = key(); generation++; rendered = ''; connected = false; pending = false;
    field.value = drafts.get(scope) || ''; designState={document:null,version:0};renderDesign(designState);closeAttach();error(); controls(); renderAttachments();
    $('codex-messages').replaceChildren(); $('codex-empty').hidden = false;
    screen.classList.remove('codex-has-history');
    $('codex-context').textContent = project()?.meta.name || 'Черновик в браузере';
    $('codex-connection').textContent = 'Проверяем подключение…';
    await refresh();
  }
  $('codex-chat-open').onclick = () => { if (screen.open) $('codex-chat-close').click(); else open(); };
  $('codex-chat-close').onclick = () => { screen.close(); $(window.DeviceUI?.mobile ? 'mobile-menu' : 'codex-chat-open').focus({preventScroll: true}); };
  screen.addEventListener('close', () => {
    if (screen.open) return;
    abortVoice();
    document.body.classList.remove('chat-open');
    document.body.classList.remove('chat-keyboard', 'chat-compact');
    $('codex-chat-open').setAttribute('aria-expanded', 'false');
    drafts.set(scope, field.value); clearTimeout(timer); generation++;
  });
  screen.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); if(!$('codex-attach-menu').hidden){closeAttach();$('codex-attach').focus();}else $('codex-chat-close').click(); }
    event.stopPropagation();
  });
  // The chat stays open while the project changes; never submit a draft in a new scope.
  new MutationObserver(() => {
    if (!screen.open) return;
    if (scope !== key()) open();
    else $('codex-context').textContent = project()?.meta.name || 'Черновик в браузере';
  }).observe($('project-status'), {childList: true, characterData: true, subtree: true});
  field.addEventListener('input', () => { drafts.set(scope, field.value); controls(); });
  field.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !window.DeviceUI?.mobile) {
      event.preventDefault(); if (!$('codex-send').disabled) $('codex-form').requestSubmit();
    }
  });
  document.querySelectorAll('[data-codex-example]').forEach(button => button.onclick = () => {
    field.value = button.dataset.codexExample; drafts.set(scope, field.value); controls(); field.focus();
  });
  $('codex-connect').onclick = () => setup.open();
  $('codex-copy-code').onclick = async () => {
    try { await navigator.clipboard.writeText(login.code); $('codex-copy-code').textContent = 'Код скопирован'; }
    catch { error('Выделите код и скопируйте его через меню телефона.'); }
  };
  $('codex-disconnect').onclick = async () => {
    const token = generation;
    try { const status = await api('/api/codex/logout', body()); if (token === generation) { error(); renderStatus(status); } }
    catch (e) { if (token === generation) error(e.message); }
  };
  $('codex-clear').onclick = async () => {
    if (!confirm('Удалить историю этого чата?')) return;
    const token = generation;
    try { const record = await api('/api/codex/clear', body()); if (token === generation) { attachmentDrafts.delete(scope); renderAttachments();renderDesign({document:null,version:record.design_version||0});error(); renderHistory(record); } }
    catch (e) { if (token === generation) error(e.message); }
  };
  $('codex-form').onsubmit = async event => {
    event.preventDefault();
    if (scope !== key()) { await open(); return; }
    if ($('codex-send').disabled) return;
    const token = generation, identity = scope, message = field.value.trim(), selected = body();
    const include_context = $('codex-include-context').checked;
    const files = attachments().map(a => a.id);
    const options = {...(modelSelect.value ? {model: modelSelect.value} : {}), ...(effortSelect.value ? {effort: effortSelect.value} : {})};
    sending = true; controls(); error();
    try {
      if (include_context && selected.project_id) await flush();
      if (token !== generation) return;
      const record = await api('/api/codex/send', {...selected, message, include_context, ...options, ...(files.length ? {attachments: files} : {}),
        ...(include_context ? {diagram: diagram()} : {})});
      drafts.set(identity, ''); attachmentDrafts.delete(identity);
      if (token !== generation) return;
      field.value = ''; renderAttachments(); renderHistory(record);
    } catch (e) { if (token === generation) error(e.message); }
    finally { sending = false; controls(); schedule(); }
  };
  window.addEventListener('focus', () => { if (screen.open) refresh(); });
  return {open,reset() {
    abortVoice(); models = []; modelsLoaded = false; modelsFailed = false;
    designState={document:null,version:0};renderDesign(designState);closeAttach();
    generation++; clearTimeout(timer); drafts.clear(); attachmentDrafts.clear(); renderAttachments(); appliedProposals.clear(); staleProposals.clear(); proposalViews.clear(); field.value = ''; scope = ''; connected = false;
    login = null; pending = false; $('codex-messages').replaceChildren(); $('codex-login').hidden = true;
    $('codex-login-code').textContent = ''; $('codex-login-link').removeAttribute('href');
    if (screen.open) screen.close();
  }};
};


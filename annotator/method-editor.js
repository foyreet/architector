'use strict';
window.setupMethodEditor = function ({load, save, first}) {
  const $ = id => document.getElementById(id);
  const dialog = $('method-dialog'), field = $('method-text'), selector = $('method-kind');
  const openButton = $('edit-method'), message = $('method-message');
  let settings = {}, drafts = {}, active = first, generation = 0, writing = false;

  function controls() {
    const ready = !!settings[active] && !writing;
    const keys = Object.keys(drafts);
    field.disabled = !ready;
    if (selector) selector.disabled = !ready;
    $('cancel-method').disabled = writing;
    $('default-method').disabled = !ready || drafts[active] === settings[active].default;
    const empty = keys.find(key => !drafts[key].trim());
    $('save-method').disabled = !ready || !!empty || !keys.some(key => drafts[key].trim() !== settings[key].text);
    if (empty && ready) {
      const label = selector && [...selector.options].find(option => option.value === empty)?.text;
      message.textContent = label ? 'Заполните методику «' + label + '» или верните встроенную.' :
        'Введите методику или верните встроенную.';
    }
  }
  function showText() {
    const current = settings[active];
    field.value = drafts[active];
    message.textContent = drafts[active] !== current.text ? 'Есть несохранённые изменения' :
      current.text === current.default ? 'Встроенная методика' : 'Своя методика';
    controls();
    field.setSelectionRange(0, 0);
    field.scrollTop = 0;
  }
  openButton.onclick = async () => {
    const token = ++generation;
    active = first;
    if (selector) selector.value = first;
    settings = {}; drafts = {};
    field.value = '';
    message.textContent = 'Загрузка…';
    controls();
    dialog.showModal();
    try {
      const loaded = await load();
      if (token !== generation || !dialog.open) return;
      settings = loaded;
      drafts = Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, value.text]));
      showText();
      field.focus();
    } catch (error) {
      if (token === generation) message.textContent = error.message;
    }
  };
  if (selector) selector.onchange = () => {
    active = selector.value;
    showText();
  };
  field.oninput = () => {
    drafts[active] = field.value;
    message.textContent = '';
    controls();
  };
  $('default-method').onclick = () => {
    drafts[active] = settings[active].default;
    showText();
    if (drafts[active] !== settings[active].text) message.textContent = 'Нажмите «Сохранить», чтобы применить встроенную методику.';
    field.focus();
  };
  $('cancel-method').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (writing) event.preventDefault(); });
  dialog.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      event.stopPropagation();
      $('save-method').click();
    }
  });
  $('save-method').onclick = async () => {
    const changes = {};
    for (const [key, draft] of Object.entries(drafts)) {
      const text = draft.trim();
      if (text !== settings[key].text) {
        changes[key] = {text:text === settings[key].default ? null : text, previous:settings[key].text};
      }
    }
    writing = true;
    controls();
    message.textContent = 'Сохранение…';
    try {
      await save(changes);
      dialog.close();
      if (!selector) openButton.title = changes[first].text === null ? 'Встроенная методика' : 'Своя методика';
    } catch (error) {
      message.textContent = error.message;
    } finally {
      writing = false;
      controls();
    }
  };
};

'use strict';
window.DesignChat = (() => {
  const fields = [['problem','Проблема и текущий процесс'],['target','Цели, таргет и антицели'],['metric_validation','Метрики'],['dataset','Датасет'],['validation','Валидация'],['model_training','Решение, альтернативы и обучение']];
  const node = (tag, text, cls='') => { const e=document.createElement(tag); e.textContent=text; e.className=cls; return e; };
  function modal(title) {
    const dialog=document.createElement('dialog');dialog.className='design-chat-dialog';dialog.setAttribute('aria-label',title);
    const header=node('div','','design-chat-heading'),close=node('button','×');close.type='button';close.setAttribute('aria-label','Закрыть');
    header.append(node('h2',title),close);const content=node('div','','design-chat-content'),error=node('p','','design-chat-error');error.hidden=true;error.setAttribute('role','alert');
    const footer=node('div','','design-chat-footer');dialog.append(header,content,error,footer);document.body.append(dialog);
    let busy=false;close.onclick=()=>{if(!busy)dialog.close();};dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});dialog.addEventListener('close',()=>dialog.remove());dialog.showModal();
    return {dialog,content,footer,setBusy(value){busy=value;close.disabled=value;},error(text){error.textContent=text;error.hidden=!text;if(text){error.tabIndex=-1;error.focus();error.scrollIntoView({block:'nearest'});}}};
  }
  function sections(parent, snapshot) {
    parent.replaceChildren(node('h3',snapshot.title));
    [...fields, ...('data_features' in snapshot.sections ? [['data_features','Признаки из прежней версии']] : [])].filter(([key]) => key in snapshot.sections).forEach(([key,label],i)=>{const section=node('section','','design-chat-section');section.append(node('h4',`${i+1}. ${label}`),node('p',snapshot.sections[key]||'Не заполнено'));parent.append(section);});
  }
  function read(snapshot) { const m=modal('Прикреплённый дизайн-документ');sections(m.content,snapshot); }
  return {read};
})();

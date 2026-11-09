'use strict';
window.DesignChat = (() => {
  const fields = [['problem','Проблема'],['target','Таргет'],['data_features','Данные и признаки'],['metric_validation','Метрика и проверка'],['model_training','Модель и обучение']];
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
    fields.forEach(([key,label],i)=>{const section=node('section','','design-chat-section');section.append(node('h4',`${i+1}. ${label}`),node('p',snapshot.sections[key]||'Не заполнено'));parent.append(section);});
  }
  function read(snapshot) { const m=modal('Прикреплённый дизайн-документ');sections(m.content,snapshot); }
  async function attach(api, scope, source) {
    const current=await api('/api/codex/design-get',scope);
    if(current.document && (current.document.source_id!==source.source_id || current.document.source_type!==source.source_type)) {
      if(!confirm(`Заменить «${current.document.title}» на «${source.title}» в этом чате?`))return false;
    }
    return api('/api/codex/design-attach',{...scope,source_type:source.source_type,source_id:source.source_id,source_revision:source.revision,design_version:current.version});
  }
  async function choose(api,onChoose) {
    const m=modal('Мои дизайн-документы');m.content.append(node('p','Загружаем документы…'));
    let selection=null,request=0;
    const add=node('button','Добавить в AI Chat','primary');add.type='button';add.disabled=true;m.footer.append(add);
    add.onclick=async()=>{if(!selection)return;add.disabled=true;m.setBusy(true);m.error('');try{if(await onChoose(selection)!==false)m.dialog.close();}catch(e){m.error(e.message);}finally{m.setBusy(false);add.disabled=false;}};
    try {
      const result=await api('/api/design-documents/list',{});if(!m.dialog.open)return;
      const list=node('div','','design-chat-list'),preview=node('div');m.content.replaceChildren(list,preview);
      if(!result.documents.length)list.append(node('p','У вас пока нет сохранённых дизайн-документов.'));
      for(const item of result.documents){const button=node('button',item.title);button.type='button';list.append(button);button.onclick=async()=>{
        const token=++request;selection=null;add.disabled=true;m.error('');
        try{const {document:doc}=await api('/api/design-documents/get',{id:item.id});if(token!==request||!m.dialog.open)return;
          selection={...doc,source_type:'private',source_id:doc.id};sections(preview,doc);add.disabled=false;
          for(const b of list.children)b.setAttribute('aria-pressed',String(b===button));preview.scrollIntoView({block:'start'});
        }catch(e){if(token===request&&m.dialog.open)m.error(e.message);}
      };}
    }catch(e){if(m.dialog.open){m.content.replaceChildren();m.error(e.message);}}
  }
  function pickProject(api) {
    return new Promise(resolve=>{const m=modal('В какой AI Chat добавить документ?');let result=null;m.dialog.addEventListener('close',()=>resolve(result));
      const label=node('label','Схема'),select=document.createElement('select');select.setAttribute('aria-label','Схема');select.append(new Option('Выберите схему',''));label.append(select);m.content.append(label);
      const add=node('button','Добавить','primary');add.disabled=true;m.footer.append(add);select.onchange=()=>add.disabled=!select.value;add.onclick=()=>{result=select.value;m.dialog.close();};
      api('/api/projects/list',{}).then(data=>{if(!m.dialog.open)return;for(const p of data.projects)select.append(new Option(p.name+' · '+new Date(p.updated_at).toLocaleString('ru-RU'),p.id));if(!data.projects.length)m.content.append(node('p','Сначала создайте схему, затем добавьте документ в её AI Chat.'));}).catch(e=>m.error(e.message));
    });
  }
  return {read,choose,attach,pickProject};
})();


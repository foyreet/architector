(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const legacy = new URL(location.href);
  if (legacy.searchParams.get('mode') === 'problems') {
    legacy.pathname = '/problem-space.html';
    legacy.searchParams.delete('mode');
    legacy.searchParams.set('legacy', '1');
    location.replace(legacy);
    return;
  }
  const fields = window.DesignChat.fields;
  const query=new URLSearchParams(location.search),project=query.get('project');
  if(/^[a-f0-9-]{36}$/.test(project||''))$('back-schema').href+='?project='+encodeURIComponent(project);
  let account=null,doc=null,release=null,dirty=false,conflicted=false,blocked=false,saving=null,working=false,mode='mine',preview=null;
  const draftKey=()=>`architect.design-document.${account.id}.${doc.id}`;
  function node(tag,text,cls=''){const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;}
  function message(text=''){ $('message').textContent=text;$('message').hidden=!text; }
  function error(text='',target='editor-error'){const e=$(target);e.textContent=text;e.hidden=!text;if(text&&!e.closest('[hidden]')){e.tabIndex=-1;e.focus({preventScroll:true});e.scrollIntoView({block:'nearest'});}}
  async function api(action,body={},community=false){
    let r;try{r=await fetch('/api/'+(community === true ? 'community/' : typeof community === 'string' ? community + '/' : 'design-documents/')+action,{method:'POST',headers:{'Content-Type':'application/json','X-Architect-Request':'1',...(account?{'X-Architect-Account':account.id}:{})},body:JSON.stringify(body)});}catch{throw Error('Не удалось связаться с сервером. Повторите попытку; введённый текст сохранён в редакторе.');}
    const data=await r.json();if(!r.ok){const e=Error(data.error||'Не удалось выполнить запрос.');e.status=r.status;throw e;}return data;
  }
  const assistant = window.setupDesignAssistant({fields, api, read:value, changed, getId:()=>doc?.id});
  function value(){return {sources:assistant.sources(),title:$('title').value,sections:Object.fromEntries(fields.map(([k])=>[k,$('section-'+k).value]))};}
  function same(a,b){return JSON.stringify(a.sources||{})===JSON.stringify(b.sources||{})&&a.title===b.title&&fields.every(([k])=>a.sections[k]===b.sections[k]);}
  function controls(){ $('compose-doc').disabled=!!saving||conflicted||blocked;$('add-chat').disabled=!!saving||conflicted||blocked;$('save').disabled=(!dirty&&!!doc?.revision)||!!saving||conflicted||blocked;$('publish').disabled=!!saving||conflicted||blocked;$('conflict').hidden=!conflicted;$('save-status').textContent=doc?(saving?'Сохранение…':dirty?'Есть несохранённые изменения':doc.revision?'Все изменения сохранены':'Новый документ · ещё не сохранён'):''; }
  function cache(){if(!doc||release)return;try{if(dirty)localStorage.setItem(draftKey(),JSON.stringify({...value(),revision:doc.revision}));else localStorage.removeItem(draftKey());}catch{error('Браузер не сохранил резервную копию. Сохраните документ на сервер перед закрытием.');}}
  function changed(){const insert=$('dataset-insert');if(insert)insert.hidden=!!$('section-dataset').value.trim();dirty=!same(value(),doc);cache();controls();}
  const datasetOutline = [
    ['ETL', 'Что означает один пример? Из каких источников, за какой период и по каким ключам собирается выборка? Где и в каком формате она хранится, как часто обновляется?'],
    ['Фильтрация', 'Какие примеры включаем или исключаем? Как обрабатываем пропуски, дубли, шум и редкие случаи? Что проверяем вручную?'],
    ['Генерация признаков', 'Из каких исходных полей и метаданных вычисляем признаки или эмбеддинги? Какие преобразования и окна используем? Что известно на момент прогноза?'],
    ['Разметка', 'Какая метка нужна и откуда она берётся? Если её ставит человек, как описаны классы, спорные примеры и проверка качества?']
  ];
  function datasetGuide(input) {
    const guide = node('div', '', 'dataset-guide');
    const help = document.createElement('details');
    help.append(node('summary', 'Что описать в каждом подразделе'));
    const list = document.createElement('dl');
    for (const [heading, question] of datasetOutline) list.append(node('dt', heading), node('dd', question));
    help.append(list);
    const insert = node('button', 'Вставить структуру');
    insert.type = 'button';
    insert.id = 'dataset-insert';
    insert.hidden = !!input.value.trim();
    insert.onclick = () => {
      if (input.value.trim()) return;
      input.value = datasetOutline.map(([heading]) => heading + '\n').join('\n');
      input.dispatchEvent(new Event('input', {bubbles:true}));
      input.focus();
      const start = datasetOutline[0][0].length + 1;
      input.setSelectionRange(start, start);
    };
    guide.append(help, insert);
    return guide;
  }
  function metricsGuide() {
    const help = node('details', '', 'metrics-guide');
    help.append(node('summary', 'Памятка — функция потерь, офлайн- и онлайн-метрики'));
    const list = document.createElement('dl');
    const items = [
      ['Функция потерь', 'Что модель минимизирует при обучении? Укажите функцию, причину выбора и веса ошибок. Учтите, одинаково ли стоят недооценка и переоценка. Например, в прогнозе спроса квантильная функция потерь позволяет учитывать разную цену дефицита и избытка.'],
      ['Офлайн-метрики', 'Как сравниваем модели до внедрения? Укажите метрику, отложенную выборку, базовую модель и важные срезы. Проверьте влияние баланса классов и устойчивость результатов. Например, качество поиска можно оценить по NDCG или MRR на размеченных запросах.'],
      ['Онлайн-метрики', 'Как измеряем эффект работающей системы для пользователей и бизнеса? Укажите основной показатель, контрольный вариант, окно наблюдения и способ проверки эффекта, например A/B-тест. Запишите показатели, ухудшение которых недопустимо. Для поиска это могут быть покупки, выручка и поведение пользователей.']
    ];
    for (const [heading, text] of items) list.append(node('dt', heading), node('dd', text));
    help.append(list, node('p', 'Для каждой метрики задайте определение или формулу, единицу измерения и направление улучшения. Объясните связь с бизнес-целью и способ её проверки. Рост кликов может сопровождаться отсутствием роста покупок — проверку этой гипотезы стоит зафиксировать в документе.'));
    return help;
  }
  function renderSections(parent, data, editable) {
    parent.replaceChildren();
    fields.forEach(([key, label], index) => {
      const section = node('section', '', 'doc-section');
      if (editable) {
        const title = node('label', (index + 1) + '. ' + label);
        const input = document.createElement('textarea');
        input.id = title.htmlFor = 'section-' + key;
        input.value = data[key] ?? '';
        input.addEventListener('input', changed);
        section.append(title);
        if (key === 'metric_validation') section.append(metricsGuide());
        if (key === 'dataset') {
          input.placeholder = 'ETL · Фильтрация · Генерация признаков · Разметка';
          section.append(datasetGuide(input));
        }
        section.append(input);
      } else {
        section.append(node('h3', (index + 1) + '. ' + label), node('p', data[key] || 'Не заполнено', 'section-text'));
      }
      parent.append(section);
    });
  }
  function updateURL(values){const url=new URL(location.href);for(const k of ['id','release','new','view'])url.searchParams.delete(k);for(const [k,v]of Object.entries(values))url.searchParams.set(k,v);history.replaceState(null,'',url);}
  async function save(){
    if(saving)return saving;if(!dirty&&doc.revision)return true;if(conflicted||blocked)return false;
    const sent=value();if(!sent.title.trim()){error('Введите название документа.');$('title').focus();return false;}
    saving=(async()=>{try{const result=await api(doc.revision?'save':'create',{id:doc.id,revision:doc.revision,...sent});doc=result.document;updateURL({id:doc.id});dirty=!same(value(),doc);cache();error();message('Документ сохранён.');return true;}
      catch(e){if(e.status===409&&e.message.includes('другой вкладке'))conflicted=true;else if(e.status===401||e.status===404||e.status===409)blocked=true;error(e.message);return false;}
      finally{saving=null;controls();}})();controls();return saving;
  }
  async function leaveEditor(){
    if(saving){await saving;return false;}
    if(!doc||release||!dirty)return true;
    if(!confirm('Выйти без сохранения? Несохранённые изменения будут потеряны. Чтобы сохранить текст, нажмите «Отмена», затем «Сохранить».'))return false;
    return true;
  }
  function discardDraft(){if(doc){try{localStorage.removeItem(draftKey());}catch{}}dirty=false;}
  async function task(fn){if(working)return;working=true;try{await fn();}catch(e){if($('editor').hidden)message(e.message);else error(e.message);}finally{working=false;}}
  function openEditor(document,restore=true){
    doc=document;release=null;dirty=false;conflicted=false;blocked=false;let content=document;
    error();message();
    if(restore){try{const draft=JSON.parse(localStorage.getItem(draftKey())||'null');
      if(draft?.sections && !Object.hasOwn(draft.sections,'dataset')) {
        draft.sections.dataset=document.sections.dataset;
        if(document.sources?.dataset) draft.sources={...draft.sources,dataset:document.sources.dataset};
      }
      if(typeof draft?.sections?.data_features === 'string') {
        const addition='Генерация признаков (из прежнего раздела)\n'+draft.sections.data_features;
        if(draft.sections.data_features.trim() && !draft.sections.dataset.includes(addition))
          draft.sections.dataset=(draft.sections.dataset+'\n\n'+addition).replace(/^\n+/, '');
        delete draft.sections.data_features;
      }
      if(draft&&typeof draft.title==='string'&&fields.every(([k])=>typeof draft.sections?.[k]==='string')){
      if(same(draft,document))localStorage.removeItem(draftKey());else{content=draft;dirty=true;conflicted=draft.revision!==document.revision;message('Восстановлены несохранённые изменения из этого браузера.');}
    }}catch{error('Не удалось прочитать локальный черновик.');}}
    $('auth').hidden=true;$('list').hidden=true;$('editor').hidden=false;$('title-label').hidden=false;$('title').hidden=false;$('title').value=content.title;$('read-title').hidden=true;
    $('save').hidden=false;$('publish').hidden=false;$('copy').hidden=true;$('publication-info').hidden=!doc.source_release;
    $('publication-info').textContent=doc.source_release?'Личная копия публикации. Ваши изменения не затрагивают оригинал.':'';
    renderSections($('sections'),content.sections,true);$('doc-assist').hidden=false;assistant.load(content.sources);updateURL(doc.revision?{id:doc.id}:{new:doc.id});$('back-list').textContent='← Мои документы';controls();window.scrollTo(0,0);
  }
  async function open(id){const result=await api('get',{id});openEditor(result.document);}
  function retryId(kind){const k='architect.design-pending.'+account.id+'.'+kind;let id;try{id=sessionStorage.getItem(k);}catch{}id ||= crypto.randomUUID();try{sessionStorage.setItem(k,id);}catch{}return {id,clear(){try{sessionStorage.removeItem(k);}catch{}}};}
  async function create(id=crypto.randomUUID()){
    openEditor({id,title:'Новый дизайн-документ',sections:Object.fromEntries(fields.map(([k])=>[k,''])),revision:0});$('title').focus();$('title').select();
  }
  async function list(next='mine'){
    if(!await leaveEditor())return;const result=next==='mine'?await api('list'):await api('catalog',{kind:'design_document',search:$('search').value},true);
    discardDraft();
    mode=next;doc=null;release=null;dirty=false;error();message();$('auth').hidden=true;$('editor').hidden=true;$('list').hidden=false;$('search-form').hidden=mode!=='catalog';
    $('mine').setAttribute('aria-current',mode==='mine'?'page':'false');$('catalog').setAttribute('aria-current',mode==='catalog'?'page':'false');
    updateURL({view:mode});$('documents').replaceChildren();
    const rows=mode==='mine'?result.documents:result.releases;
    if(!rows.length)$('documents').append(node('p',mode==='mine'?'У вас пока нет дизайн-документов.':$('search').value?'По этому запросу документов нет.':'В сообществе пока нет опубликованных дизайн-документов.','muted'));
    for(const row of rows){const item=node('div','','document-item'),button=node('button','','document-row');button.append(node('strong',row.title||row.name));if(mode==='catalog')button.append(node('small',`@${row.username} · версия ${row.number}`));button.onclick=()=>task(()=>mode==='mine'?open(row.id):openRelease(row.id));item.append(button);
      if(mode==='mine'){const remove=node('button','Удалить','delete-document');remove.setAttribute('aria-label','Удалить документ «'+row.title+'»');remove.onclick=()=>task(async()=>{
        if(!confirm('Удалить документ «'+row.title+'»? Это действие нельзя отменить.'))return;
        remove.disabled=true;try{await api('delete',{id:row.id,revision:row.revision});try{localStorage.removeItem(`architect.design-document.${account.id}.${row.id}`);}catch{}await list('mine');message('Документ удалён.');$('create').focus();}finally{remove.disabled=false;}
      });item.append(remove);}$('documents').append(item);}
    window.scrollTo(0,0);
  }
  async function openRelease(id){
    const result=await api('release',{release_id:id},true);if(result.kind!=='design_document')throw Error('Это не публикация дизайн-документа.');
    release=result;doc=null;dirty=false;conflicted=false;blocked=false;error();message();
    $('auth').hidden=true;$('list').hidden=true;$('editor').hidden=false;$('title-label').hidden=true;$('title').hidden=true;$('read-title').hidden=false;$('read-title').textContent=result.name;
    $('save').hidden=true;$('publish').hidden=true;$('copy').hidden=false;$('publication-info').hidden=false;$('publication-info').textContent=`@${result.username} · версия ${result.number} · Опубликованный документ`;
    $('doc-assist').hidden=true;renderSections($('sections'),result.package.sections,false);updateURL({release:id});$('back-list').textContent='← Каталог сообщества';controls();window.scrollTo(0,0);
  }
  $('add-chat').onclick=()=>task(async()=>{
    if(!release&&(!doc.revision||dirty)){error('Сначала нажмите «Сохранить», чтобы добавить актуальный документ в AI Chat.');return;}
    const source=release?{...release.package,title:release.name,source_type:'release',source_id:release.id,revision:release.number}:{...doc,source_type:'private',source_id:doc.id};
    const call=async(path,body)=>{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Architect-Request':'1','X-Architect-Account':account.id},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Не удалось прикрепить документ.');return data;};
    const selected=project||await window.DesignChat.pickProject(call);if(!selected)return;
    if(!await window.DesignChat.attach(call,{project_id:selected},source))return;
    location.href='/architecture.html?project='+encodeURIComponent(selected)+'&chat=1';
  });
  $('title').addEventListener('input',changed);
  $('save').onclick=()=>task(save);$('create').onclick=()=>task(()=>create());$('mine').onclick=()=>task(()=>list('mine'));$('catalog').onclick=()=>task(()=>list('catalog'));
  $('search-form').onsubmit=e=>{e.preventDefault();task(()=>list('catalog'));};$('back-list').onclick=()=>task(()=>list(release?'catalog':'mine'));
  $('back-schema').onclick=e=>{if(!doc||(!dirty&&!saving))return;e.preventDefault();task(async()=>{if(await leaveEditor()){discardDraft();location.href=$('back-schema').href;}});};
  $('copy').onclick=()=>task(async()=>{const attempt=retryId('copy.'+release.id),r=await api('copy',{id:attempt.id,release_id:release.id});attempt.clear();openEditor(r.document);message('Документ сохранён в «Мои документы».');});
  $('save-separate').onclick=()=>task(async()=>{const attempt=retryId('separate.'+doc.id),oldKey=draftKey();const r=await api('create',{id:attempt.id,...value()});try{localStorage.removeItem(oldKey);}catch{}attempt.clear();openEditor(r.document,false);message('Ваш вариант сохранён отдельным документом.');});
  $('reload-saved').onclick=()=>task(async()=>{if(!confirm('Загрузить сохранённую версию? Несохранённый текст в этой вкладке будет заменён.'))return;const r=await api('get',{id:doc.id});try{localStorage.removeItem(draftKey());}catch{}openEditor(r.document,false);});
  $('publish').textContent='Экспорт JSON';
  $('publish').onclick=()=>task(async()=>{const content=value();if(!content.title.trim()){error('Введите название документа.');$('title').focus();return;}const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify({format:'architect.design-document',version:1,...content},null,2)],{type:'application/json'}));link.download=content.title+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);});
  const upload=document.createElement('input');upload.type='file';upload.accept='.json,application/json';upload.hidden=true;document.body.append(upload);
  const importButton=document.createElement('button');importButton.textContent='Импорт JSON';$('create').after(importButton);importButton.onclick=()=>upload.click();
  upload.onchange=()=>task(async()=>{const file=upload.files[0];upload.value='';if(!file)return;const result=await api('import',{id:crypto.randomUUID(),package:JSON.parse(await file.text())});await open(result.document.id);});
  const closePreview=()=>{if(!$('publish-confirm').disabled)$('publish-dialog').close();};$('preview-close').onclick=closePreview;$('publish-cancel').onclick=closePreview;
  $('publish-dialog').addEventListener('cancel',e=>{if($('publish-confirm').disabled)e.preventDefault();});
  $('publish-confirm').onclick=async()=>{const button=$('publish-confirm');if(button.disabled)return;button.disabled=true;error('','publish-error');try{const r=await api('publish',{id:doc.id,revision:preview.revision,digest:preview.digest});$('publish-dialog').close();await openRelease(r.release_id);message('Документ опубликован в каталоге сообщества.');}catch(e){error(e.message,$('publish-dialog').open?'publish-error':'editor-error');}finally{button.disabled=false;}};
  window.addEventListener('beforeunload',e=>{if(dirty){cache();e.preventDefault();e.returnValue='';}});
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&doc){e.preventDefault();task(save);}});
  async function start(){const session=await api('session',{},true);account=session.user;$('register').hidden=session.registration_open===false||!session.enabled;if(!account){$('auth').hidden=false;return;}$('account').textContent='На этом компьютере';
    if(query.has('release'))await openRelease(query.get('release'));else if(query.has('id'))await open(query.get('id'));else if(query.has('new'))await create(/^[a-f0-9-]{36}$/.test(query.get('new'))?query.get('new'):undefined);else await list(query.get('view')==='catalog'?'catalog':'mine');}
  async function login(register){try{await api(register?'register':'login',{username:$('username').value,password:$('password').value},true);$('password').value='';await start();}catch(e){message(e.message);}}
  $('login-form').onsubmit=e=>{e.preventDefault();login(false);};$('register').onclick=()=>{if($('login-form').reportValidity())login(true);};
  start().catch(e=>{message(e.message);if(account){$('list').hidden=false;$('documents').append(node('p','Можно открыть свои документы или создать новый.','muted'));}});
})();


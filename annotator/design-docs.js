(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const fields=[['problem','Проблема'],['target','Таргет'],['data_features','Данные и признаки'],['metric_validation','Метрика и проверка'],['model_training','Модель и обучение']];
  const query=new URLSearchParams(location.search),project=query.get('project');
  if(/^[a-f0-9-]{36}$/.test(project||''))$('back-schema').href+='?project='+encodeURIComponent(project);
  let account=null,doc=null,release=null,dirty=false,conflicted=false,blocked=false,saving=null,working=false,mode='mine',preview=null;
  const draftKey=()=>`architect.design-document.${account.id}.${doc.id}`;
  function node(tag,text,cls=''){const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;}
  function message(text=''){ $('message').textContent=text;$('message').hidden=!text; }
  function error(text='',target='editor-error'){const e=$(target);e.textContent=text;e.hidden=!text;if(text&&!e.closest('[hidden]')){e.tabIndex=-1;e.focus({preventScroll:true});e.scrollIntoView({block:'nearest'});}}
  async function api(action,body={},community=false){
    let r;try{r=await fetch('/api/'+(community?'community/':'design-documents/')+action,{method:'POST',headers:{'Content-Type':'application/json','X-Architect-Request':'1',...(account?{'X-Architect-Account':account.id}:{})},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});}catch{throw Error('Не удалось связаться с сервером. Повторите попытку; введённый текст сохранён в редакторе.');}
    const data=await r.json();if(!r.ok){const e=Error(data.error||'Не удалось выполнить запрос.');e.status=r.status;throw e;}return data;
  }
  function value(){return {title:$('title').value,sections:Object.fromEntries(fields.map(([k])=>[k,$('section-'+k).value]))};}
  function same(a,b){return a.title===b.title&&fields.every(([k])=>a.sections[k]===b.sections[k]);}
  function controls(){ $('add-chat').disabled=!!saving||conflicted||blocked;$('save').disabled=!dirty||!!saving||conflicted||blocked;$('publish').disabled=!!saving||conflicted||blocked;$('conflict').hidden=!conflicted; }
  function cache(){if(!doc||release)return;try{if(dirty)localStorage.setItem(draftKey(),JSON.stringify({...value(),revision:doc.revision}));else localStorage.removeItem(draftKey());}catch{error('Браузер не сохранил резервную копию. Сохраните документ на сервер перед закрытием.');}}
  function changed(){dirty=!same(value(),doc);cache();controls();}
  function renderSections(parent,data,editable){parent.replaceChildren();fields.forEach(([k,label],i)=>{const section=node('section','','doc-section');if(editable){const l=node('label',`${i+1}. ${label}`);l.htmlFor='section-'+k;const input=document.createElement('textarea');input.id=l.htmlFor;input.maxLength=20000;input.value=data[k];input.addEventListener('input',changed);section.append(l,input);}else{section.append(node('h3',`${i+1}. ${label}`),node('p',data[k]||'Не заполнено','section-text'));}parent.append(section);});}
  function updateURL(values){const url=new URL(location.href);for(const k of ['id','release','new','view'])url.searchParams.delete(k);for(const [k,v]of Object.entries(values))url.searchParams.set(k,v);history.replaceState(null,'',url);}
  async function save(){
    if(saving)return saving;if(!dirty)return true;if(conflicted||blocked)return false;
    const sent=value();if(!sent.title.trim()){error('Введите название документа.');$('title').focus();return false;}
    saving=(async()=>{try{const result=await api('save',{id:doc.id,revision:doc.revision,...sent});doc=result.document;dirty=!same(value(),doc);cache();error();message('Документ сохранён.');return true;}
      catch(e){if(e.status===409&&e.message.includes('другой вкладке'))conflicted=true;else if(e.status===401||e.status===404||e.status===409)blocked=true;error(e.message);return false;}
      finally{saving=null;controls();}})();controls();return saving;
  }
  async function flush(){if(release||!doc)return true;while(dirty){if(!await save())return false;}return true;}
  async function task(fn){if(working)return;working=true;try{await fn();}catch(e){if($('editor').hidden)message(e.message);else error(e.message);}finally{working=false;}}
  function openEditor(document,restore=true){
    doc=document;release=null;dirty=false;conflicted=false;blocked=false;let content=document;
    error();message();
    if(restore){try{const draft=JSON.parse(localStorage.getItem(draftKey())||'null');if(draft&&typeof draft.title==='string'&&fields.every(([k])=>typeof draft.sections?.[k]==='string')){
      if(same(draft,document))localStorage.removeItem(draftKey());else{content=draft;dirty=true;conflicted=draft.revision!==document.revision;message('Восстановлены несохранённые изменения из этого браузера.');}
    }}catch{error('Не удалось прочитать локальный черновик.');}}
    $('auth').hidden=true;$('list').hidden=true;$('editor').hidden=false;$('title-label').hidden=false;$('title').hidden=false;$('title').value=content.title;$('read-title').hidden=true;
    $('save').hidden=false;$('publish').hidden=false;$('copy').hidden=true;$('publication-info').hidden=!doc.source_release;
    $('publication-info').textContent=doc.source_release?'Личная копия публикации. Ваши изменения не затрагивают оригинал.':'';
    renderSections($('sections'),content.sections,true);updateURL({id:doc.id});$('back-list').textContent='← Мои документы';controls();window.scrollTo(0,0);
  }
  async function open(id){const result=await api('get',{id});openEditor(result.document);}
  function retryId(kind){const k='architect.design-pending.'+account.id+'.'+kind;let id;try{id=sessionStorage.getItem(k);}catch{}id ||= crypto.randomUUID();try{sessionStorage.setItem(k,id);}catch{}return {id,clear(){try{sessionStorage.removeItem(k);}catch{}}};}
  async function create(){const attempt=retryId('create');const r=await api('create',{id:attempt.id});attempt.clear();openEditor(r.document);$('title').focus();$('title').select();}
  async function list(next='mine'){
    if(!await flush())return;const result=next==='mine'?await api('list'):await api('catalog',{kind:'design_document',search:$('search').value},true);
    mode=next;doc=null;release=null;dirty=false;error();message();$('auth').hidden=true;$('editor').hidden=true;$('list').hidden=false;$('search-form').hidden=mode!=='catalog';
    $('mine').setAttribute('aria-current',mode==='mine'?'page':'false');$('catalog').setAttribute('aria-current',mode==='catalog'?'page':'false');
    updateURL({view:mode});$('documents').replaceChildren();
    const rows=mode==='mine'?result.documents:result.releases;
    if(!rows.length)$('documents').append(node('p',mode==='mine'?'У вас пока нет дизайн-документов.':$('search').value?'По этому запросу документов нет.':'В сообществе пока нет опубликованных дизайн-документов.','muted'));
    for(const row of rows){const button=node('button','','document-row');button.append(node('strong',row.title||row.name));if(mode==='catalog')button.append(node('small',`@${row.username} · версия ${row.number}`));button.onclick=()=>task(()=>mode==='mine'?open(row.id):openRelease(row.id));$('documents').append(button);}
    if(rows.length===200)$('documents').append(node('p','Показаны последние 200 документов.','muted'));window.scrollTo(0,0);
  }
  async function openRelease(id){
    const result=await api('release',{release_id:id},true);if(result.kind!=='design_document')throw Error('Это не публикация дизайн-документа.');
    release=result;doc=null;dirty=false;conflicted=false;blocked=false;error();message();
    $('auth').hidden=true;$('list').hidden=true;$('editor').hidden=false;$('title-label').hidden=true;$('title').hidden=true;$('read-title').hidden=false;$('read-title').textContent=result.name;
    $('save').hidden=true;$('publish').hidden=true;$('copy').hidden=false;$('publication-info').hidden=false;$('publication-info').textContent=`@${result.username} · версия ${result.number} · Опубликованный документ`;
    renderSections($('sections'),result.package.sections,false);updateURL({release:id});$('back-list').textContent='← Каталог сообщества';controls();window.scrollTo(0,0);
  }
  $('add-chat').onclick=()=>task(async()=>{
    if(!await flush())return;
    const source=release?{...release.package,title:release.name,source_type:'release',source_id:release.id,revision:release.number}:{...doc,source_type:'private',source_id:doc.id};
    const call=async(path,body)=>{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Architect-Request':'1','X-Architect-Account':account.id},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Не удалось прикрепить документ.');return data;};
    const selected=project||await window.DesignChat.pickProject(call);if(!selected)return;
    if(!await window.DesignChat.attach(call,{project_id:selected},source))return;
    location.href='/architecture.html?project='+encodeURIComponent(selected)+'&chat=1';
  });
  $('title').addEventListener('input',changed);
  $('save').onclick=()=>save();$('create').onclick=()=>task(create);$('mine').onclick=()=>task(()=>list('mine'));$('catalog').onclick=()=>task(()=>list('catalog'));
  $('search-form').onsubmit=e=>{e.preventDefault();task(()=>list('catalog'));};$('back-list').onclick=()=>task(()=>list(release?'catalog':'mine'));
  $('back-schema').onclick=e=>{if(!doc||!dirty)return;e.preventDefault();task(async()=>{if(await flush())location.href=$('back-schema').href;});};
  $('copy').onclick=()=>task(async()=>{const attempt=retryId('copy.'+release.id),r=await api('copy',{id:attempt.id,release_id:release.id});attempt.clear();openEditor(r.document);message('Документ сохранён в «Мои документы».');});
  $('save-separate').onclick=()=>task(async()=>{const attempt=retryId('separate.'+doc.id);const r=await api('create',{id:attempt.id});const oldKey=draftKey();doc=r.document;conflicted=false;blocked=false;dirty=true;updateURL({id:doc.id});cache();try{localStorage.removeItem(oldKey);}catch{}attempt.clear();controls();await save();});
  $('reload-saved').onclick=()=>task(async()=>{if(!confirm('Загрузить сохранённую версию? Несохранённый текст в этой вкладке будет заменён.'))return;const r=await api('get',{id:doc.id});try{localStorage.removeItem(draftKey());}catch{}openEditor(r.document,false);});
  $('publish').textContent='Экспорт JSON';
  $('publish').onclick=()=>task(async()=>{if(!await flush())return;const result=await api('export',{id:doc.id});const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(result.package,null,2)],{type:'application/json'}));link.download=doc.title+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);});
  const upload=document.createElement('input');upload.type='file';upload.accept='.json,application/json';upload.hidden=true;document.body.append(upload);
  const importButton=document.createElement('button');importButton.textContent='Импорт JSON';$('create').after(importButton);importButton.onclick=()=>upload.click();
  upload.onchange=()=>task(async()=>{const file=upload.files[0];upload.value='';if(!file)return;if(file.size>300000)throw Error('Документ слишком большой.');const result=await api('import',{id:crypto.randomUUID(),package:JSON.parse(await file.text())});await open(result.document.id);});
  const closePreview=()=>{if(!$('publish-confirm').disabled)$('publish-dialog').close();};$('preview-close').onclick=closePreview;$('publish-cancel').onclick=closePreview;
  $('publish-dialog').addEventListener('cancel',e=>{if($('publish-confirm').disabled)e.preventDefault();});
  $('publish-confirm').onclick=async()=>{const button=$('publish-confirm');if(button.disabled)return;button.disabled=true;error('','publish-error');try{const r=await api('publish',{id:doc.id,revision:preview.revision,digest:preview.digest});$('publish-dialog').close();await openRelease(r.release_id);message('Документ опубликован в каталоге сообщества.');}catch(e){error(e.message,$('publish-dialog').open?'publish-error':'editor-error');}finally{button.disabled=false;}};
  window.addEventListener('beforeunload',e=>{if(dirty){cache();e.preventDefault();e.returnValue='';}});
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&doc){e.preventDefault();save();}});
  async function start(){const session=await api('session',{},true);account=session.user;$('register').hidden=session.registration_open===false||!session.enabled;if(!account){$('auth').hidden=false;return;}$('account').textContent='На этом компьютере';
    if(query.has('release'))await openRelease(query.get('release'));else if(query.has('id'))await open(query.get('id'));else if(query.has('new'))await create();else await list(query.get('view')==='catalog'?'catalog':'mine');}
  async function login(register){try{await api(register?'register':'login',{username:$('username').value,password:$('password').value},true);$('password').value='';await start();}catch(e){message(e.message);}}
  $('login-form').onsubmit=e=>{e.preventDefault();login(false);};$('register').onclick=()=>{if($('login-form').reportValidity())login(true);};
  start().catch(e=>{message(e.message);if(account){$('list').hidden=false;$('documents').append(node('p','Можно открыть свои документы или создать новый.','muted'));}});
})();


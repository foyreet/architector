'use strict';
window.ModelRegistry = ({api,download,context}) => {
  const el=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  const stamp=v=>new Date(v).toLocaleString();
  function button(parent,title,fn){const b=el('button',title);b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){parent.append(el('p',e.message,'insight-error'));}finally{b.disabled=false;}};parent.append(b);return b;}
  function modal(title,id){const d=el('dialog','','insight-dialog');if(id)d.id=id;const heading=el('div','','dialog-heading'); heading.append(el('h2',title)); button(heading,'Закрыть',()=>d.close()); d.append(heading);document.body.append(d);d.onclose=()=>d.remove();d.showModal();return d;}
  function field(parent,title,tag='input'){const label=el('label',title),input=el(tag);label.append(input);parent.append(label);return input;}
  async function chooseRun(){
    const project_id=context?.()?.meta.id;
    const d=modal('Добавить версию из запуска','model-source-dialog');
    if(!project_id){d.append(el('p','Сначала откройте проект с обученной моделью.'));return;}
    const runs=field(d,'Запуск','select'),models=field(d,'Сохранённая модель','select'),status=el('p');status.setAttribute('role','status');d.append(status);
    let request=0,assets=[];
    const save=button(d,'Продолжить',async()=>{
      const asset=assets[Number(models.value)];if(!asset)return;
      const origin={project_id,run_id:runs.value,node_id:asset.node_id,port:asset.port};d.close();await register(origin);
    });save.disabled=true;
    async function load(){
      const token=++request;save.disabled=true;models.replaceChildren();assets=[];status.textContent='Загрузка моделей…';
      if(!runs.value){status.textContent='В проекте пока нет запусков.';return;}
      try{
        const value=await api('/api/pipelines/assets',{project_id,run_id:runs.value});if(!d.open||token!==request)return;
        assets=value.assets.filter(a=>a.kind==='model_bundle');assets.forEach((a,i)=>models.append(new Option(a.node_name+' · '+a.label,String(i))));
        save.disabled=!assets.length;status.textContent=assets.length?'':'В этом запуске нет сохранённых моделей.';
      }catch(e){if(d.open&&token===request)status.textContent=e.message;}
    }
    runs.onchange=load;
    try{
      const value=await api('/api/pipelines/runs',{project_id});if(!d.open)return;
      value.runs.forEach(r=>runs.append(new Option(stamp(r.created_at)+' · '+r.id.slice(0,8),r.id)));await load();
    }catch(e){if(d.open)status.textContent=e.message;}
  }
  function table(parent,headers,rows){const wrap=el('div','','insight-scroll'),t=el('table','','experiments-table'),head=el('tr');headers.forEach(h=>head.append(el('th',h)));t.append(head);for(const row of rows){const tr=el('tr');row.forEach(v=>tr.append(el('td',String(v??'—'))));t.append(tr);}wrap.append(t);parent.append(wrap);}
  async function register(origin){const d=modal('Сохранить версию модели','register-model-dialog'),state=await api('/api/models/list',{});if(!d.open)return;
    const family=field(d,'Модель','select');family.append(new Option('Новая модель',''));state.families.forEach(f=>family.append(new Option(f.name,f.id)));const name=field(d,'Название новой модели');name.value='Моя модель';
    family.onchange=()=>name.parentElement.hidden=!!family.value;
    button(d,'Сохранить версию',async()=>{const value=await api('/api/models/register',{origin,...(family.value?{family_id:family.value}:{name:name.value})});d.close();await open(value.family.id);});
  }
  async function comparison(family,version){const d=modal('Сравнение версий · '+family.name,'model-compare-dialog'),before=field(d,'Базовая версия','select');family.versions.filter(v=>v.id!==version.id).forEach(v=>before.append(new Option('v'+v.number+' · '+stamp(v.created_at),v.id)));
    const previous=family.versions.filter(v=>v.number<version.number).at(-1);if(previous)before.value=previous.id;const out=el('section');d.append(out);
    const load=async()=>{const value=await api('/api/models/compare',{before:before.value,after:version.id});if(!d.open)return;out.replaceChildren(el('h3','Сравнение с v'+version.number));
      if(!value.same_dataset||!value.same_split)out.append(el('p','Данные или разбиение отличаются. Метрики нельзя считать прямым сравнением качества.','insight-error'));
      table(out,['Метрика','Базовая','Выбранная','Δ'],value.metrics.map(m=>[m.metric,m.before,m.after,m.delta]));out.append(el('h3','Параметры'),el('pre',JSON.stringify(value.settings,null,2)),el('h3','Признаки'),el('pre',JSON.stringify(value.features,null,2)));};before.onchange=()=>load().catch(e=>out.replaceChildren(el('p',e.message)));await load();
  }
  async function createAPI(family,version){const d=modal('API · '+family.name+' · v'+version.number,'model-api-create-dialog');d.append(el('p','API закрепляется за этой версией. Отметка «Лучшая» и новые версии не меняют его поведение.'));
    let gpu=null;if(version.format==='architect.gpu-mlp'){const value=await api('/api/compute/options',{});if(!d.open)return;gpu=field(d,'GPU для предсказаний','select');value.devices.forEach(device=>gpu.append(new Option((device.shared?'Общий · ':'Мой · ')+device.name+(device.online?'':' · офлайн'),device.id)));if(value.selected)gpu.value=value.selected;}
    const output=el('section');button(d,'Создать API этой версии',async()=>{const entry=await api('/api/models/endpoint-create',{version_id:version.id,compute:gpu?{mode:'gpu',device_id:gpu.value}:{mode:'cpu'}});if(!d.open)return;
      const url=location.origin+entry.path;output.replaceChildren(el('h3','API создан'),el('p','Сохраните ключ: он показывается только сейчас.'),el('p',entry.available?'Готов к запросам':entry.reason));
      button(output,'Скачать ключ API',()=>download({url,token:entry.token,version_id:entry.version_id},'model-api-key'));
      button(output,'Скачать пример rows.json',()=>{const a=el('a');const blob=new Blob([JSON.stringify({rows:[Object.fromEntries(version.features.map(f=>[f,0]))]},null,2)],{type:'application/json'});a.href=URL.createObjectURL(blob);a.download='rows.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});
      output.append(el('pre',`curl '${url}' \\\n  -H 'Authorization: Bearer ${entry.token}' \\\n  -H 'Content-Type: application/json' \\\n  --data-binary @rows.json`),el('p','Пример содержит нули. Замените их значениями признаков. До 30 запросов в минуту. Доступность: GET '+url+'/status с тем же Bearer-токеном.'));});d.append(output);
  }
  async function open(focus=null){if(!window.WorkspaceNavigation.leave())return;const d=modal('Модели и API','models-dialog'),content=el('section');d.append(el('p','Версии хранят данные об обучении и защищают файлы модели от очистки.'));
    button(d,'Добавить версию из запуска',async()=>{d.close();await chooseRun();});d.append(content);
    async function refresh(){const [state,apis]=await Promise.all([api('/api/models/list',{}),api('/api/models/endpoints',{})]);if(!d.open)return;content.replaceChildren();
      if(!state.families.length)content.append(el('p','Пока нет сохранённых версий. Добавьте модель из завершённого запуска.'));
      for(const family of state.families){const card=el('section','','insight-card');card.append(el('h3',family.name+' · '+family.versions.length+' версий'));if(family.id===focus)card.setAttribute('data-selected','true');
        for(const v of [...family.versions].reverse()){const best=family.best_version_id===v.id,row=el('article','','model-version'+(best?' is-best':''));row.append(el('h4','v'+v.number+(best?' · ★ Лучшая':'')),el('p',stamp(v.created_at)+' · '+(v.project.name||'Черновик')),el('p','Признаки: '+v.features.join(', ')+' · цель: '+v.target));
          table(row,['Метрика','Значение'],Object.entries(v.metrics));const details=el('details');details.append(el('summary','Параметры, разбиение и среда'),el('pre',JSON.stringify({run_id:v.origin.run_id,dataset_sha256:v.dataset_sha256,settings:v.settings,preparation:v.preparation,split:v.split,versions:v.versions},null,2)));row.append(details);const controls=el('div','','model-controls');row.append(controls);
          if(!best)button(controls,'Отметить лучшей',async()=>{await api('/api/models/best',{family_id:family.id,version_id:v.id});await refresh();});
          if(family.versions.length>1)button(controls,'Сравнить версии',()=>comparison(family,v));
          button(controls,'Создать API',()=>createAPI(family,v));button(controls,'Скачать модель',async()=>download(await api('/api/resources/asset',{artifact:v.artifact}),family.name+'-v'+v.number));card.append(row);}
        content.append(card);}
      content.append(el('h3','API предсказаний'));
      if(!apis.endpoints.length)content.append(el('p','Создайте API у нужной версии модели.'));
      for(const endpoint of apis.endpoints){const card=el('section','','insight-card');card.append(el('h4',(endpoint.family||'Модель')+' · v'+(endpoint.number||'?')),el('code',location.origin+endpoint.path),el('p',endpoint.available?'Готов к запросам':endpoint.reason),el('p','Успешных запросов: '+(endpoint.calls||0)));
        if(endpoint.enabled)button(card,'Отключить API',async()=>{if(!confirm('Отключить этот API и его токен?'))return;await api('/api/models/endpoint-revoke',{id:endpoint.id});await refresh();});
        else button(card,'Удалить подключение',async()=>{await api('/api/models/endpoint-delete',{id:endpoint.id});await refresh();});content.append(card);}
    }
    button(d,'Обновить',refresh);await refresh();
  }
  document.getElementById('model-registry').onclick=()=>open().catch(e=>alert(e.message));
  return {open,register};
};


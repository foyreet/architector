'use strict';
window.LabTools = ({api, compute, context, prepare, contract, secrets, history, refreshRuns, download}) => {
  const $ = id => document.getElementById(id);
  const el = (tag, text = '', cls = '') => { const n = document.createElement(tag); n.textContent = text; n.className = cls; return n; };
  const stamp = v => new Date(v).toLocaleString();
  function modal(title) { const d = el('dialog', '', 'insight-dialog'); const heading=el('div','','dialog-heading'); heading.append(el('h2',title)); button(heading,'Закрыть',()=>d.close()); d.append(heading); document.body.append(d); d.onclose = () => d.remove(); d.showModal(); return d; }
  function button(parent, title, fn) { const b = el('button', title); b.type = 'button'; b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { const p = el('p', e.message, 'insight-error'); p.setAttribute('role','alert'); parent.append(p); } finally { b.disabled = b.available ? !b.available() : false; } }; parent.append(b); return b; }
  function field(parent, title, tag='input', value='') { const l=el('label',title), n=el(tag); n.value=value; l.append(n); parent.append(l); return n; }
  function table(parent, headers, rows) { const scroll=el('div','','insight-scroll'), t=el('table','','experiments-table'), head=el('tr'); headers.forEach(h=>head.append(el('th',h))); t.append(head); for(const values of rows){const tr=el('tr');values.forEach(v=>tr.append(el('td',String(v??'—'))));t.append(tr);} scroll.append(t);parent.append(scroll);return t; }
  function saveText(text,name,type) {const url=URL.createObjectURL(new Blob([text],{type})), a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function csv(rows) {const keys=Object.keys(rows[0]||{});const escape=v=>'"'+String(v??'').replace(/^[=+@\-\t\r]/,m=>"'"+m).replaceAll('"','""')+'"';return '\ufeff'+[keys,...rows.map(r=>keys.map(k=>r[k]))].map(r=>r.map(escape).join(',')).join('\r\n');}
  async function fileText(input) {const file=input.files[0];if(!file)throw new Error('Выберите CSV-файл.');if(file.size>2*1024*1024)throw new Error('CSV должен быть не больше 2 МиБ.');return file.text();}
  function csvFields(parent) {const file=field(parent,'CSV в UTF-8, до 1000 строк и 2 МиБ');file.type='file';file.accept='.csv,text/csv';const separator=field(parent,'Разделитель','select');for(const [v,t]of [[',','Запятая'],[';','Точка с запятой'],['\t','Табуляция']])separator.append(new Option(t,v));return {file,separator};}
  function chart(parent, title, values) {
    parent.append(el('h4',title)); if(!values.length){parent.append(el('p','Нет значений.'));return;}
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),max=Math.max(...values.map(v=>v.count),1);svg.setAttribute('viewBox',`0 0 700 ${values.length*36+25}`);svg.style.width='100%';svg.setAttribute('role','img');svg.setAttribute('aria-label',title);
    const add=(tag,attrs,text='')=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));n.textContent=text;svg.append(n);};add('rect',{width:'100%',height:'100%',fill:'white'});
    values.forEach((v,i)=>{add('text',{x:5,y:24+i*36,fill:'#334155','font-size':13},String(v.label).slice(0,26));add('rect',{x:230,y:9+i*36,width:Math.max(1,v.count/max*390),height:20,fill:'#3763ee',rx:3});add('text',{x:630,y:24+i*36,fill:'#334155','font-size':13},v.count);});const scroll=el('div','','chart-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',title+' · прокрутка графика');scroll.append(svg);parent.append(scroll);
    button(parent,'Скачать график SVG',()=>saveText(new XMLSerializer().serializeToString(svg),'analysis.svg','image/svg+xml'));
  }
  async function analyze(source=null) {
    const d=modal('Визуальный анализ данных');d.id='analysis-dialog';d.append(el('p','Анализ выполняется до обучения. Изменений данных не происходит.'));
    const upload=source?null:csvFields(d), target=field(d,'Целевая колонка для баланса классов (необязательно)','input',source?.target||''), output=el('section');
    button(d,'Проанализировать',async()=>{
      const body=source?{...source,target:target.value}:{csv:await fileText(upload.file),separator:upload.separator.value,target:target.value};
      const value=await api('/api/lab/analyze',body);if(!d.open)return;output.replaceChildren();
      output.append(el('p',`${value.profile.rows} строк · ${value.profile.columns.length} колонок · ${value.profile.duplicates} повторов`),el('p',value.notes));
      button(output,'Скачать отчёт JSON',()=>download(value,'data-analysis'));
      chart(output,'Пропуски по колонкам',value.statistics.map(c=>({label:c.name,count:c.missing})));
      if(value.target)chart(output,'Баланс классов · '+value.target,value.balance);
      if(value.target_classes>30)output.append(el('p','Показаны 30 самых частых классов. Всего: '+value.target_classes));
      const select=field(output,'Распределение признака','select'), area=el('div','','insight-card');output.append(area);
      value.statistics.forEach((c,i)=>select.append(new Option(c.name,i)));
      const draw=()=>{const c=value.statistics[Number(select.value)];area.replaceChildren();if(c.type==='number'){
        area.append(el('p',`Минимум ${c.minimum} · максимум ${c.maximum} · среднее ${c.mean.toPrecision(5)} · медиана ${c.median}`));
        chart(area,'Распределение · '+c.name,c.histogram.map(b=>({label:b.from.toPrecision(3)+'…'+b.to.toPrecision(3),count:b.count})));
        area.append(el('p',`Выбросы по ${c.outliers.rule}: ${c.outliers.count}. Первые строки данных: ${c.outliers.rows.join(', ')||'нет'}.`));
      }else chart(area,'Частые значения · '+c.name,c.categories);};select.onchange=draw;draw();
      if(value.correlation_columns.length){output.append(el('h3','Корреляции Пирсона'));const columns=value.correlation_columns,t=table(output,['',...columns],columns.map(a=>[a,...columns.map(b=>value.correlations.find(c=>c.a===a&&c.b===b)?.value?.toFixed(3)??'—')]));
        [...t.rows].slice(1).forEach(row=>[...row.cells].slice(1).forEach(cell=>{const v=Number(cell.textContent);if(Number.isFinite(v))cell.style.background=v>=0?`rgba(36,150,100,${Math.abs(v)*.3})`:`rgba(220,70,70,${Math.abs(v)*.3})`;}));}
    });d.append(output);
  }
  function predictionResult(parent,value){parent.replaceChildren(el('h3','Предсказания готовы'),el('p',`${value.rows.length} строк · столбец ${value.prediction_column}. Сохранено: ${stamp(value.created_at)}`));
    button(parent,'Скачать предсказания CSV',()=>saveText(csv(value.rows),'predictions.csv','text/csv;charset=utf-8'));button(parent,'Скачать JSON',()=>download(value,'predictions'));
    const columns=Object.keys(value.rows[0]||{});table(parent,columns,value.rows.slice(0,50).map(r=>columns.map(k=>r[k])));if(value.rows.length>50)parent.append(el('p','Первые 50 строк. Полная таблица — в скачиваемом файле.'));
  }
  async function predict(artifact,origin){const d=modal('Предсказания сохранённой моделью');d.id='predict-dialog';const info=await api('/api/lab/model-info',{artifact});if(!d.open)return;
    d.append(el('p','Обязательные числовые колонки: '+info.features.join(', ')),el('p','Целевая колонка не требуется. Дополнительные колонки сохранятся в результате. Повторного обучения нет.'),el('p',info.format==='architect.gpu-mlp'?'Для этой нейросети нужен подключённый GPU компьютера.':'Используется обученный Random Forest на CPU.'));
    const upload=csvFields(d),result=el('section');button(d,'Получить предсказания',async()=>{const value=await api('/api/lab/predict',{artifact,origin,csv:await fileText(upload.file),separator:upload.separator.value});if(d.open)predictionResult(result,value);});d.append(result);
  }
  async function series(){if(!window.WorkspaceNavigation.leave())return;const snapshot=await prepare();if(!snapshot.project_id)throw new Error('Сначала нажмите «Сохранить», чтобы создать проект.');
    await compute.refresh(snapshot);snapshot.compute=compute.selection();
    const d=modal('Серии экспериментов и очередь');d.id='series-dialog';d.append(el('p','До 20 вариантов, последовательно. GPU-блоки выполняются на выбранном компьютере. Каждый вариант получает отдельную запись запуска; исходная схема не меняется.'));
    const choices=[];for(const n of snapshot.diagram.nodes.filter(n=>!n.block.kind.startsWith('subgraph_')))for(const s of contract(n.block.kind)?.settings||[])if(['integer','number'].includes(s.type))choices.push({node_id:n.id,setting:s.id,label:n.name+' · '+s.label,definition:s});
    const form=el('section','','insight-card');d.append(form);const axes=[];
    for(let i=0;i<2;i++){const setting=field(form,'Параметр '+(i+1),'select');setting.append(new Option(i?'Не использовать':'Выберите параметр',''));choices.forEach((c,index)=>setting.append(new Option(c.label,index)));const values=field(form,'Значения через запятую','input',i?'5,10':'50,100,200');axes.push({setting,values});}
    const tree=choices.findIndex(c=>c.setting==='n_estimators'),depth=choices.findIndex(c=>c.setting==='max_depth');if(tree>=0)axes[0].setting.value=tree;if(depth>=0)axes[1].setting.value=depth;
    const saved=context()?.meta.research||{},metric=field(form,'Ключ основной метрики','input',saved.metric||((snapshot.diagram.nodes.find(n=>n.block.kind==='ml_evaluate')?.id||'')+'/accuracy'));
    const metricSelect=field(form,'Основная метрика','select');
    for(const n of snapshot.diagram.nodes)if(n.block.kind==='ml_evaluate')for(const key of ['accuracy','macro_f1'])metricSelect.append(new Option(n.name+' · '+key,n.id+'/'+key));
    metricSelect.append(new Option('Свой ключ отчёта Python','__custom__'));metricSelect.value=[...metricSelect.options].some(o=>o.value===metric.value)?metric.value:'__custom__';metric.parentElement.hidden=metricSelect.value!=='__custom__';
    metricSelect.onchange=()=>{metric.parentElement.hidden=metricSelect.value!=='__custom__';if(metricSelect.value!=='__custom__')metric.value=metricSelect.value;};
    const direction=field(form,'Лучшее значение','select');direction.append(new Option('Больше','max'),new Option('Меньше','min'));direction.value=saved.direction||'max';
    const preview=el('section'),list=el('section');let pending=null,timer=null,generation=0;
    const start=button(form,'Добавить серию в очередь',async()=>{if(!pending)return;const result=await api('/api/series/start',{...pending,secrets:secrets()});pending=null;start.disabled=true;preview.replaceChildren(el('p','Серия поставлена в очередь: '+result.id));await refreshRuns();await poll();});start.disabled=true;start.available=()=>!!pending;
    form.addEventListener('input',()=>{++generation;pending=null;start.disabled=true;});
    button(form,'Проверить варианты',async()=>{const token=++generation;pending=null;start.disabled=true;const parsed=[];
      for(const a of axes)if(a.setting.value!==''){const c=choices[Number(a.setting.value)];let values;try{values=JSON.parse('['+a.values.value+']');}catch{throw new Error('Введите числа через запятую, например 50,100,200.');}parsed.push({node_id:c.node_id,setting:c.setting,values});}
      const body={project_id:snapshot.project_id,revision:snapshot.revision,compute:snapshot.compute,axes:parsed,metric:metric.value,direction:direction.value};const plan=await api('/api/series/preview',body);if(!d.open||token!==generation)return;
      preview.replaceChildren(el('p',`Будет выполнено ${plan.count} полных запусков. Подключённые внешние сервисы могут списывать средства за каждый вариант. Нажмите «Добавить серию в очередь» для запуска.`));table(preview,['Вариант','Параметры'],plan.variants.map((v,i)=>[i+1,v.map(p=>p.node+' / '+p.setting+'='+p.value).join('; ')]));pending={...body,digest:plan.digest,request_id:crypto.randomUUID()};start.disabled=false;
    });form.append(preview);d.append(list);
    const labels={queued:'В очереди',running:'Выполняется',ready:'Готово',error:'Ошибка',cancelled:'Отменён',finished:'Завершена',cancelling:'Отмена оставшихся',interrupted:'Остановлена сервером'};
    const poll=async()=>{clearTimeout(timer);try{const response=await api('/api/series/list',{project_id:snapshot.project_id});if(!d.open)return;list.replaceChildren(el('h3','Очередь этого проекта'));
      if(!response.series.length)list.append(el('p','Серий пока нет.'));for(const record of response.series){const card=el('section','','insight-card');card.append(el('h4',stamp(record.created_at)+' · '+labels[record.status]),el('p',`${record.items.filter(i=>!['queued','running'].includes(i.status)).length} / ${record.items.length} завершено · метрика ${record.research.metric}`));
        const t=table(card,['Параметры','Статус','Метрика','Запуск'],record.items.map(i=>[i.parameters.map(p=>p.node+' / '+p.setting+'='+p.value).join(', '),labels[i.status]||i.status,(i.metric??'—')+(i.run_id===record.best_run_id?' ★ лучший':''),i.run_id.slice(0,8)]));
        record.items.forEach((item,i)=>{if(!['queued','cancelled'].includes(item.status))button(t.rows[i+1].cells[3],'Открыть',async()=>{d.close();await history(item.run_id);});if(item.error)t.rows[i+1].cells[1].append(el('p',item.error));});
        if(['queued','running'].includes(record.status))button(card,'Отменить оставшиеся',async()=>{await api('/api/series/cancel',{id:record.id});await poll();});
        if(record.status==='interrupted')button(card,'Продолжить ожидающие',async()=>{await api('/api/series/resume',{id:record.id,secrets:secrets()});await poll();});
        button(card,'Скачать таблицу JSON',()=>download(record,'experiment-series'));list.append(card);}
    }catch(e){if(d.open)list.replaceChildren(el('p',e.message));}finally{if(d.open)timer=setTimeout(poll,3000);}};
    d.addEventListener('close',()=>clearTimeout(timer));await poll();
  }
  $('experiment-series').onclick=()=>series().catch(e=>alert(e.message));
  return {analyze,predict,series};
};


'use strict';
window.TrainingConsole = ({api, context, diagram, secrets, onResumed}) => {
  const $=id=>document.getElementById(id), el=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  const main=$('compute-target'),confirm=$('compute-confirm');let devices=[],request=0;
  const labels={waiting:'Ожидает',running:'Выполняется',ready:'Готово',error:'Ошибка',cancelled:'Остановлен',paused:'Приостановлен'};
  const describe=()=>{
    const d=devices.find(d=>'gpu:'+d.id===main.value);
    const text=main.value==='cpu'?'':d?
      `${d.shared?'Общий GPU':'Мой GPU'} · ${d.online?'онлайн':'офлайн'} · ${d.busy?'занят':'свободен'} · в очереди ${d.queue_count} · остаток ${Math.floor(d.remaining_seconds/60)} мин${d.reason?' · '+d.reason:''}`:'Выберите доступный GPU в поле вычислений';
    $('compute-confirm-status').textContent=text;
    $('compute-confirm-status').hidden=!text;
  };
  for(const select of [main,confirm])select.onchange=()=>{main.value=confirm.value=select.value;describe();};
  async function refresh(reference=null){
    const token=++request,value=await api('/api/compute/options',reference||{});if(token!==request)return;
    devices=value.devices;
    let choice=main.value;
    for(const select of [main,confirm]){
      select.replaceChildren(new Option('CPU этого компьютера'+(value.cpu_busy?' · занят':''),'cpu'));
      for(const d of devices){const option=new Option((d.shared?'Общий GPU · ':'Мой GPU · ')+d.name+(d.online&&d.allowed?'':' · недоступен'),'gpu:'+d.id);select.append(option);}
      if(choice&&![...select.options].some(o=>o.value===choice))select.append(new Option('GPU не подключён',choice));
      select.value=choice||'cpu';
    }
    describe();
  }
  function selection(){const value=main.value;return value==='cpu'?{mode:'cpu'}:{mode:'gpu',device_id:value.slice(4)};}
  main.addEventListener('focus',()=>refresh({diagram:diagram()}).catch(e=>{main.title=e.message;}));
  refresh().catch(()=>{});
  setInterval(()=>{if(!document.hidden)refresh().catch(()=>{});},10000);

  function plot(parent,values){
    parent.replaceChildren();if(!values.length){parent.append(el('p','Кривая появится после первой эпохи GPU-нейросети. Для Random Forest доступны итоговые метрики.'));return;}
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),width=760,height=260;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('role','img');svg.setAttribute('aria-label','Loss по эпохам');svg.classList.add('loss-chart');
    const add=(tag,attrs,text='')=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);n.textContent=text;svg.append(n);};
    const low=Math.min(...values),high=Math.max(...values),span=Math.max(high-low,0.00001);
    for(let i=0;i<5;i++){const y=20+i*50;add('line',{x1:65,y1:y,x2:740,y2:y,stroke:'#e2e8f0'});add('text',{x:4,y:y+5,fill:'#64748b','font-size':12},(high-i*span/4).toPrecision(4));}
    add('polyline',{points:values.map((v,i)=>`${65+i/Math.max(1,values.length-1)*675},${20+(high-v)/span*200}`).join(' '),fill:'none',stroke:'#3563ef','stroke-width':3});
    add('text',{x:65,y:250,fill:'#64748b','font-size':13},'Эпоха 1');add('text',{x:640,y:250,fill:'#64748b','font-size':13},'Эпоха '+values.length);
    parent.append(svg,el('p','Последний loss: '+values.at(-1).toPrecision(6)));return svg;
  }
  async function open(runId){
    if(!runId)throw new Error('Сначала запустите пайплайн.');
    const projectAtOpen=context()?.meta.id;
    const reference={...(context()?{project_id:context().meta.id}:{}),run_id:runId};
    const d=el('dialog','','insight-dialog');d.id='training-dialog';const heading=el('div','','dialog-heading');heading.append(el('h2','Обучение и выполнение'));
    const close=el('button','Закрыть'),stop=el('button','Остановить запуск'),summary=el('section'),curves=el('section'),events=el('pre');
    const recovery=el('section'),points=el('section'),resume=el('button','Продолжить с сохранённой эпохи'),target=el('select'),resumeError=el('p','','insight-error');
    target.setAttribute('aria-label','GPU для продолжения');recovery.hidden=true;
    recovery.append(el('h3','Продолжение обучения'),el('p','Будет создан новый запуск по сохранённой схеме и данным. Готовые предыдущие шаги используются из истории; оставшиеся шаги выполнятся после обучения. Изменения на полотне сюда не входят. Нужны тот же backend GPU и версия PyTorch.'),target,resume,resumeError);
    let resumeLoaded=false,resuming=false;const newRunId=crypto.randomUUID();
    resume.onclick=async()=>{resuming=true;resume.disabled=true;resumeError.textContent='';try{
      const run=await api('/api/pipelines/resume-training',{...reference,new_run_id:newRunId,compute:{mode:'gpu',device_id:target.value},secrets:secrets()});
      if(context()?.meta.id===projectAtOpen)await onResumed(run);
      d.close();d.remove();if(context()?.meta.id===projectAtOpen)await open(run.id);
    }catch(e){resumeError.textContent=e.message;}finally{resuming=false;resume.disabled=false;}};
    close.onclick=()=>d.close();heading.append(close);d.append(heading,stop,summary,points,recovery,curves,el('h3','Последние события'),events);document.body.append(d);d.showModal();let timer=null;
    stop.onclick=async()=>{stop.disabled=true;try{await api('/api/pipelines/cancel',reference);await poll();}catch(e){summary.append(el('p',e.message,'insight-error'));stop.disabled=false;}};
    async function poll(){clearTimeout(timer);try{
      const data=await api('/api/pipelines/monitor',reference);if(!d.open)return;const r=data.run,active=['waiting','running'].includes(r.status),current=r.order.find(id=>r.nodes[id].status==='running'),gpu=data.gpu[0];
      const elapsed=Math.max(0,Math.floor((new Date(r.finished_at||data.server_time)-new Date(r.created_at))/1000));
      summary.replaceChildren(el('h3',r.name+' · '+(labels[r.status]||r.status)),el('p',`Прошло ${Math.floor(elapsed/60)} мин ${elapsed%60} сек · шаги ${r.order.filter(id=>r.nodes[id].status==='ready').length} / ${r.order.length}`),el('p','Вычисления: '+(r.compute?.name||r.gpu_executor?.name||'CPU этого компьютера')));
      if(current)summary.append(el('p','Текущий этап: '+r.nodes[current].name));
      const position=data.slot.queue_position||gpu?.queue_position;if(position)summary.append(el('p','Место в очереди: '+position));
      if(gpu?.progress.epoch)summary.append(el('p',`Эпоха ${gpu.progress.epoch} / ${gpu.progress.epochs}`));
      if(r.error)summary.append(el('p',r.error,'insight-error'));
      if(r.training_resume)summary.append(el('p','Продолжено после эпохи '+r.training_resume.epoch+' · исходный запуск '+r.training_resume.run_id));
      points.replaceChildren();
      for(const point of data.checkpoints||[])points.append(el('p',`Сохранено на сервере: ${point.name} · эпоха ${point.epoch} / ${point.epochs} · ${new Date(point.saved_at).toLocaleTimeString()}`));
      if(!data.checkpoints?.length&&r.compute?.mode==='gpu')points.append(el('p','Точка сохраняется после первой эпохи, затем каждые 5 эпох и в конце обучения.'));
      recovery.hidden=!data.resume;
      if(data.resume&&!resumeLoaded){
        const options=await api('/api/compute/options',{});if(!d.open)return;
        for(const device of options.devices)target.append(new Option(device.name+(device.online&&device.allowed?'':' · недоступен'),device.id));
        if([...target.options].some(o=>o.value===r.gpu_executor?.id))target.value=r.gpu_executor.id;
        resume.textContent='Продолжить после эпохи '+data.resume.epoch;resumeLoaded=true;
      }
      resume.disabled=resuming||!target.value;
      curves.replaceChildren(el('h3','Loss по эпохам'));
      for(const c of data.curves){curves.append(el('h4',c.name));const area=el('div');curves.append(area);plot(area,c.values);}
      if(gpu?.progress.loss_curve?.length||!data.curves.length){const area=el('div');curves.append(area);plot(area,gpu?.progress.loss_curve||[]);}
      events.textContent=r.events.slice(-12).map(e=>new Date(e.time).toLocaleTimeString()+' · '+e.message).join('\n');stop.disabled=!active||!!r.cancel_requested;
      if(active)timer=setTimeout(poll,1000);
    }catch(e){if(d.open){summary.replaceChildren(el('p',e.message,'insight-error'));timer=setTimeout(poll,3000);}}}
    d.onclose=()=>{clearTimeout(timer);d.remove();};await poll();
  }
  return {refresh,selection,open,plot};
};


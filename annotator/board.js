(() => {
  'use strict';
  const $=id=>document.getElementById(id),svg=$('canvas'),ns='http://www.w3.org/2000/svg';
  const params=new URLSearchParams(location.search),returnProject=params.get('project');
  const validId=s=>/^[a-f0-9-]{36}$/.test(s||'');
  $('back-schema').href='/architecture.html'+(validId(returnProject)?'?project='+encodeURIComponent(returnProject):'');
  let account=null,boardId=params.get('board'),board=null,revision=-1,remote=new Map(),queue=[],undo=[],conflict=null,blocked=false;
  let tool='pen',selected=null,gesture=null,pointsDown=new Set(),camera={x:0,y:0,z:1},syncing=null,connected=false,textAction=null;
  const key=()=>`architect.board.pending.${account.id}.${boardId}`;
  function message(text=''){ $('message').textContent=text;$('message').hidden=!text; }
  async function api(action,body={},community=false){
    const response=await fetch('/api/'+(community?'community/':'boards/')+action,{method:'POST',headers:{'Content-Type':'application/json','X-Architect-Request':'1',...(account?{'X-Architect-Account':account.id}:{})},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok){const e=Error(result.error||'Не удалось выполнить запрос.');e.status=response.status;throw e;}return result;
  }
  function saveQueue(){try{if(queue.length)localStorage.setItem(key(),JSON.stringify(queue));else localStorage.removeItem(key());}catch{message('Браузер не сохранил резервную копию правок. Не закрывайте страницу до отправки на сервер.');}}
  function state(){const map=new Map(remote);for(const op of queue)map.set(op.object_id,{id:op.object_id,version:op.expected,data:op.data});return map;}
  function status(){
    $('sync').textContent=blocked?'Доступ к доске приостановлен':conflict?'Нужно решить конфликт':!connected?'Нет связи · правки ожидают отправки':queue.length?'Сохраняем…':'Все правки сохранены';
    $('undo').disabled=!undo.length||!!queue.length||blocked;const item=state().get(selected);$('delete').disabled=!item?.data||!!queue.length||blocked;
    $('conflict').hidden=!conflict;if(conflict){$('conflict-text').textContent=conflict;$('overwrite').hidden=queue[0]?.undo||!connected||!conflict.includes('объект уже');}
  }
  function element(tag,attrs={},parent=svg){const node=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))node.setAttribute(k,v);parent.append(node);return node;}
  function draw(d,id,preview=false){
    const g=element('g',{'data-id':id||'',stroke:d.color,'stroke-width':d.width,fill:'none','stroke-linecap':'round','stroke-linejoin':'round',...(preview?{opacity:.65,'pointer-events':'none'}:{})});
    if(d.kind==='pen')element('polyline',{points:d.points.map(p=>`${d.x+p[0]},${d.y+p[1]}`).join(' '),'pointer-events':'stroke'},g);
    if(d.kind==='rect')element('rect',{x:d.x,y:d.y,width:d.w,height:d.h,fill:'transparent'},g);
    if(d.kind==='ellipse')element('ellipse',{cx:d.x+d.w/2,cy:d.y+d.h/2,rx:d.w/2,ry:d.h/2,fill:'transparent'},g);
    if(d.kind==='arrow'){element('line',{x1:d.x,y1:d.y,x2:d.x+d.w,y2:d.y+d.h},g);element('polyline',{points:BoardPDF.arrow(d).map(p=>p.join(',')).join(' ')},g);}
    if(d.kind==='text'){const t=element('text',{x:d.x,y:d.y+20,fill:d.color,stroke:'none','font-size':20,'font-family':'sans-serif'},g);BoardPDF.textLines(d.text).forEach((line,i)=>{element('tspan',{x:d.x,y:d.y+20+i*26},t).textContent=line||' ';});}
  }
  function render(){
    const size=svg.getBoundingClientRect();svg.setAttribute('viewBox',`${camera.x} ${camera.y} ${size.width/camera.z||1000} ${size.height/camera.z||600}`);svg.dataset.tool=tool;svg.replaceChildren();
    const map=state();if(gesture?.data&&gesture.id)map.set(gesture.id,{data:gesture.data});for(const [id,item]of map)if(item.data)draw(item.data,id);
    if(gesture?.data&&!gesture.id)draw(gesture.data,null,true);
    const item=map.get(selected);if(item?.data){const b=BoardPDF.bounds(item.data);element('rect',{x:b.x-4,y:b.y-4,width:b.w+8,height:b.h+8,fill:'none',stroke:'#285bef','stroke-width':1/camera.z,'stroke-dasharray':`${5/camera.z} ${3/camera.z}`,'pointer-events':'none'});}
    status();
  }
  function enqueue(id,data,expected,before,isUndo=false){
    if(blocked)return;queue.push({object_id:id,data,expected,op_id:crypto.randomUUID(),before,undo:isUndo});saveQueue();render();sync();
  }
  async function sync(){
    if(syncing||!board||blocked)return syncing;
    syncing=(async()=>{
      try{
        while(queue.length&&!conflict){
          const op=queue[0];let ack;
          try{ack=await api('apply',{board_id:boardId,op_id:op.op_id,object_id:op.object_id,expected:op.expected,data:op.data});}
          catch(e){if(e.status===409&&e.message.includes('объект уже')){conflict=e.message;revision=-1;break;}throw e;}
          remote.set(op.object_id,{id:op.object_id,version:ack.version,data:op.data});queue.shift();saveQueue();
          if(!op.undo)undo.push({object_id:op.object_id,data:op.before,expected:ack.version});
          else {const previous=[...undo].reverse().find(item=>item.object_id===op.object_id);if(previous)previous.expected=ack.version;}
          revision=-1;
        }
        const result=await api('get',{board_id:boardId,since:revision});
        board=result.board;revision=board.revision;if(result.items)remote=new Map(result.items.map(i=>[i.id,i]));
        $('rename').textContent=board.title;$('rename').disabled=board.owner!==account.id;$('share').hidden=true;
        $('people').textContent=result.people.length>1?'Сейчас здесь: '+result.people.join(', '):'На доске только вы';
        connected=true;
      }catch(e){connected=false;if(e.status===401||e.status===403||e.status===404||(e.status===409&&!e.message.includes('объект уже'))){blocked=true;message(e.message+' Перезагрузите страницу после входа в нужный аккаунт.');}
        else if(e.status&&e.status<500){conflict=e.message;message(e.message);}
      }finally{syncing=null;render();}
    })();return syncing;
  }
  async function settle(){await sync();if(queue.length||blocked||!connected){message('Не все правки отправлены на сервер. Дождитесь связи и решите конфликт перед выходом или экспортом.');return false;}return true;}
  async function list(){
    const result=await api('list');$('auth').hidden=true;$('editor').hidden=true;$('list').hidden=false;board=null;boardId=null;
    const url=new URL(location.href);url.searchParams.delete('board');url.hash='';history.replaceState(null,'',url);
    $('boards').replaceChildren();if(!result.boards.length){const p=document.createElement('p');p.textContent='Пока нет досок. Создайте первую или откройте ссылку преподавателя.';$('boards').append(p);}
    for(const b of result.boards){const button=document.createElement('button');button.className='board-row';button.textContent=b.title;const small=document.createElement('small');small.textContent=b.owner===account.id?'Моя доска':'Совместная доска';button.append(small);button.onclick=()=>open(b.id).catch(e=>message(e.message));$('boards').append(button);}
  }
  async function open(id){
    const result=await api('get',{board_id:id});boardId=id;board=result.board;remote=new Map(result.items.map(i=>[i.id,i]));revision=board.revision;queue=[];undo=[];conflict=null;blocked=false;selected=null;camera={x:0,y:0,z:1};connected=true;
    try{const pending=JSON.parse(localStorage.getItem(key())||'[]');if(Array.isArray(pending))queue=pending.filter(p=>validId(p.op_id)&&validId(p.object_id)&&Number.isInteger(p.expected));}catch{message('Не удалось прочитать резервную копию правок.');}
    const url=new URL(location.href);url.searchParams.set('board',id);url.hash='';history.replaceState(null,'',url);
    $('auth').hidden=true;$('list').hidden=true;$('editor').hidden=false;$('rename').textContent=board.title;$('rename').disabled=board.owner!==account.id;$('share').hidden=true;
    render();fit();await sync();svg.focus();
  }
  function textDialog(heading,value,callback,rows=5){textAction=callback;$('text-error').hidden=true;$('text-heading').textContent=heading;$('text-label').textContent=heading;$('text-input').value=value;$('text-input').rows=rows;$('text-dialog').showModal();$('text-input').focus();}
  $('text-form').onsubmit=async e=>{e.preventDefault();const value=$('text-input').value.trim();if(!value)return;const submit=$('text-form').querySelector('[type=submit]');submit.disabled=true;$('text-error').hidden=true;try{await textAction(value);$('text-dialog').close();}catch(err){$('text-error').textContent=err.message;$('text-error').hidden=false;}finally{submit.disabled=false;}};
  $('text-cancel').onclick=()=> $('text-dialog').close();
  $('create').onclick=()=>textDialog('Название доски','Новая доска',async title=>{const result=await api('create',{title});await open(result.id);},2);
  $('rename').onclick=()=>textDialog('Название доски',board.title,async title=>{await api('rename',{board_id:boardId,title});await sync();},2);
  $('back-list').onclick=async()=>{if(await settle())await list().catch(e=>message(e.message));};
  $('back-schema').onclick=async e=>{if(!board)return;e.preventDefault();if(await settle())location.href=$('back-schema').href;};
  $('share').onclick=async()=>{try{const result=await api('share',{board_id:boardId});const url=new URL('/board.html',location.origin);url.searchParams.set('board',boardId);url.hash='invite='+result.token;$('invite-link').value=url;$('copy').textContent='Копировать ссылку';$('share-error').hidden=true;$('share-dialog').showModal();}catch(e){message(e.message);}};
  $('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('invite-link').value);$('copy').textContent='Ссылка скопирована';}catch{$('invite-link').select();$('share-error').textContent='Скопируйте выделенную ссылку.';$('share-error').hidden=false;}};
  $('share-close').onclick=()=> $('share-dialog').close();
  $('revoke').onclick=async()=>{if(!confirm('Закрыть доску для всех приглашённых? Старая ссылка перестанет работать.'))return;try{await api('revoke',{board_id:boardId});$('share-dialog').close();message('Доступ приглашённых закрыт. Можно создать новую ссылку.');await sync();}catch(e){$('share-error').textContent=e.message;$('share-error').hidden=false;}};
  $('pdf').onclick=async()=>{if(gesture){message('Завершите рисунок перед экспортом.');return;}$('pdf').disabled=true;try{if(await settle())await BoardPDF.download([...remote.values()],board.title);}catch(e){message(e.message);}finally{$('pdf').disabled=false;}};
  $('discard').onclick=()=>{queue.shift();conflict=null;saveQueue();message();render();sync();};
  $('overwrite').onclick=async()=>{try{if(!queue.length||queue[0].undo)return;const result=await api('get',{board_id:boardId});remote=new Map(result.items.map(i=>[i.id,i]));const op=queue[0],current=remote.get(op.object_id);op.expected=current?.version||0;op.before=current?.data||null;op.op_id=crypto.randomUUID();conflict=null;saveQueue();message();sync();}catch(e){message(e.message);}};
  function remove(){if($('delete').disabled)return;const item=remote.get(selected);enqueue(selected,null,item.version,item.data);selected=null;}
  function undoOwn(){if($('undo').disabled)return;const op=undo.pop();enqueue(op.object_id,op.data,op.expected,null,true);}
  $('delete').onclick=remove;$('undo').onclick=undoOwn;
  document.querySelectorAll('button[data-tool]').forEach(button=>button.onclick=()=>{tool=button.dataset.tool;gesture=null;document.querySelectorAll('button[data-tool]').forEach(b=>b.setAttribute('aria-pressed',b===button));render();});
  function point(e){const r=svg.getBoundingClientRect();return {x:camera.x+(e.clientX-r.left)/camera.z,y:camera.y+(e.clientY-r.top)/camera.z};}
  svg.onpointerdown=e=>{
    pointsDown.add(e.pointerId);if(pointsDown.size>1){gesture=null;render();return;}if(e.button!==0||blocked)return;svg.setPointerCapture(e.pointerId);svg.focus();const p=point(e),id=e.target.closest('[data-id]')?.dataset.id;
    if(tool==='pan'){gesture={pan:true,start:p,camera:{...camera},client:{x:e.clientX,y:e.clientY}};return;}
    if(tool==='select'){selected=id||null;const item=remote.get(id);if(item?.data&&!queue.some(op=>op.object_id===id))gesture={id,start:p,before:structuredClone(item.data),data:structuredClone(item.data),expected:item.version};render();return;}
    selected=null;if(tool==='text'){textDialog('Текст на доске','',text=>enqueue(crypto.randomUUID(),{kind:'text',x:p.x,y:p.y,color:$('color').value,width:2,text},0,null));return;}
    gesture={start:p,data:{kind:tool,x:p.x,y:p.y,color:$('color').value,width:2,...(tool==='pen'?{points:[[0,0],[.1,.1]]}:{w:0,h:0})}};render();
  };
  svg.onpointermove=e=>{if(!gesture||pointsDown.size>1)return;const p=point(e),g=gesture;if(g.pan){camera.x=g.camera.x-(e.clientX-g.client.x)/camera.z;camera.y=g.camera.y-(e.clientY-g.client.y)/camera.z;}
    else if(g.id){g.data.x=g.before.x+p.x-g.start.x;g.data.y=g.before.y+p.y-g.start.y;}
    else if(g.data.kind==='pen'){g.data.points.push([p.x-g.start.x,p.y-g.start.y]);}
    else {g.data.w=p.x-g.start.x;g.data.h=p.y-g.start.y;if(g.data.kind!=='arrow'){g.data.x=Math.min(p.x,g.start.x);g.data.y=Math.min(p.y,g.start.y);g.data.w=Math.abs(g.data.w);g.data.h=Math.abs(g.data.h);}}
    render();
  };
  svg.onpointerup=e=>{pointsDown.delete(e.pointerId);if(!gesture)return;const g=gesture;gesture=null;if(!g.pan){if(g.id){if(JSON.stringify(g.data)!==JSON.stringify(g.before))enqueue(g.id,g.data,g.expected,g.before);}else if(g.data.kind==='pen'||Math.abs(g.data.w)+Math.abs(g.data.h)>2)enqueue(crypto.randomUUID(),g.data,0,null);}render();};
  svg.onpointercancel=e=>{pointsDown.delete(e.pointerId);gesture=null;render();};
  svg.ondblclick=e=>{if(tool!=='select'||blocked)return;const id=e.target.closest('[data-id]')?.dataset.id,item=remote.get(id);if(item?.data?.kind==='text'&&!queue.length)textDialog('Текст на доске',item.data.text,text=>enqueue(id,{...item.data,text},item.version,item.data));};
  function zoom(factor,center){const r=svg.getBoundingClientRect(),cx=center?.x??r.width/2,cy=center?.y??r.height/2,z=Math.max(.05,Math.min(4,camera.z*factor));camera.x+=cx/camera.z-cx/z;camera.y+=cy/camera.z-cy/z;camera.z=z;render();}
  svg.addEventListener('wheel',e=>{e.preventDefault();if(gesture)return;const r=svg.getBoundingClientRect();zoom(e.deltaY>0?.9:1.1,{x:e.clientX-r.left,y:e.clientY-r.top});},{passive:false});
  function fit(){const bs=[...state().values()].filter(i=>i.data).map(i=>BoardPDF.bounds(i.data));if(!bs.length){camera={x:0,y:0,z:1};render();return;}const x=Math.min(...bs.map(b=>b.x))-40,y=Math.min(...bs.map(b=>b.y))-40,w=Math.max(...bs.map(b=>b.x+b.w))-x+40,h=Math.max(...bs.map(b=>b.y+b.h))-y+40,r=svg.getBoundingClientRect();camera={x,y,z:Math.max(.001,Math.min(1,r.width/w,r.height/h))};render();}
  $('zoom-in').onclick=()=>zoom(1.2);$('zoom-out').onclick=()=>zoom(1/1.2);$('fit').onclick=fit;
  document.addEventListener('keydown',e=>{if(e.target.closest('input,textarea,dialog')||!board)return;if(e.key==='Escape'){gesture=null;selected=null;render();}if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();remove();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undoOwn();}});
  window.addEventListener('beforeunload',e=>{if(queue.length||gesture){e.preventDefault();e.returnValue='';}});
  new ResizeObserver(()=>{if(board)render();}).observe($('surface'));
  window.addEventListener('online',()=>sync());setInterval(()=>{if(board&&!document.hidden)sync();},1000);
  async function start(){const session=await api('session',{},true);account=session.user;$('register').hidden=session.registration_open===false||!session.enabled;if(!account){$('auth').hidden=false;$('list').hidden=true;$('editor').hidden=true;return;}$('account').textContent='На этом компьютере';
    const token=new URLSearchParams(location.hash.slice(1)).get('invite');if(validId(boardId)){await open(boardId);}else await list();}
  async function login(register=false){message();try{await api(register?'register':'login',{username:$('username').value,password:$('password').value},true);$('password').value='';await start();}catch(e){message(e.message);}}
  $('login-form').onsubmit=e=>{e.preventDefault();login();};$('register').onclick=()=>{if($('login-form').reportValidity())login(true);};
  start().catch(e=>{message(e.message);if(account){$('list').hidden=false;$('boards').textContent='Доска недоступна. Можно создать новую или вернуться к схеме.';}});
})();


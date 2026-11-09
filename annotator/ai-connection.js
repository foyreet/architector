window.AIConnection = ({api, changed}) => {
  const el=(tag,text='')=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const dialog=el('dialog');dialog.id='ai-setup';dialog.setAttribute('aria-labelledby','ai-setup-title');
  const heading=el('div');heading.className='dialog-heading';const title=el('h2','Подключить AI');title.id='ai-setup-title';
  const close=el('button','×');close.setAttribute('aria-label','Закрыть настройку AI');close.onclick=()=>dialog.close();heading.append(title,close);
  const note=el('p','Используйте своё подключение. Схема и документы отправляются выбранной модели только при отправке сообщения.');
  const provider=el('select');provider.id='ai-provider';provider.append(new Option('Другая модель · локальная или облачная','compatible'),new Option('Codex · свой аккаунт','codex'));
  const providerLabel=el('label','Способ подключения');providerLabel.append(provider);
  const fields=el('div');
  function field(label,id,type='text'){const l=el('label',label),i=el('input');i.id=id;i.type=type;l.append(i);fields.append(l);return i;}
  const base=field('Адрес API (с /v1)','ai-base-url');base.placeholder='http://localhost:11434/v1';
  const model=field('Название модели','ai-model-name');model.placeholder='Название установленной модели';
  const key=field('API-ключ, если требуется','ai-api-key','password');key.autocomplete='off';
  const hint=el('p','В Docker адрес модели на ноутбуке: http://host.docker.internal:11434/v1. Для редактирования схем модель должна поддерживать вызов инструментов.');hint.className='muted';fields.append(hint);
  const codex=el('p','Для этого варианта нужен Codex CLI в среде запуска Архитектора. Вход выполняется в ваш аккаунт OpenAI.');
  const status=el('p');status.id='ai-setup-status';status.setAttribute('role','status');
  const actions=el('div');actions.className='project-actions';
  const save=el('button','Сохранить подключение');save.className='primary';save.id='ai-save';
  const test=el('button','Сохранить и проверить API');test.id='ai-test';
  const mcp=el('details');const summary=el('summary','Подключить внешний AI через MCP');mcp.append(summary,el('p','Подключите Архитектор к своему AI-клиенту. Общение будет происходить в этом клиенте. MCP даёт доступ к схемам в локальной папке.'));
  const address=el('code',location.origin+'/mcp');address.id='ai-mcp-url';mcp.append(address,el('p','Транспорт: Streamable HTTP. Аккаунт и токен Архитектора не требуются; адрес доступен только на вашем компьютере.'));
  let kept=false,busy=false;
  function render(){fields.hidden=provider.value!=='compatible';codex.hidden=provider.value!=='codex';test.hidden=provider.value!=='compatible';save.textContent=provider.value==='codex'?'Подключить Codex':'Сохранить подключение';}
  provider.onchange=()=>{status.textContent='';render();};
  async function configure(check=false){
    if(busy)return;busy=true;save.disabled=test.disabled=provider.disabled=true;status.textContent=check?'Проверяем API…':'Сохраняем…';
    try{
      await api('/api/codex/configure',{provider:provider.value,base_url:base.value,model:model.value,api_key:key.value,keep_key:kept});
      if(provider.value==='codex'){await api('/api/codex/login',{});dialog.close();}
      else if(check){const result=await api('/api/codex/test',{});status.textContent=result.model_found?'API доступен, модель найдена.':'API доступен, но указанной модели нет в списке. Проверьте название.';}
      else{status.textContent='Подключение сохранено. Можно закрыть настройки и написать сообщение.';}
      kept=provider.value==='compatible'&&(kept||!!key.value);key.value='';key.placeholder=kept?'Ключ сохранён локально':'';
      await changed();
    }catch(e){status.textContent=e.message;}
    finally{busy=false;save.disabled=test.disabled=provider.disabled=false;}
  }
  save.onclick=()=>configure();test.onclick=()=>configure(true);
  actions.append(save,test);dialog.append(heading,note,providerLabel,fields,codex,actions,status,mcp);document.body.append(dialog);render();
  return {open:async()=>{status.textContent='';if(!dialog.open)dialog.showModal();try{const c=await api('/api/codex/config',{});provider.value=c.provider==='codex'?'codex':'compatible';base.value=c.base_url||'';model.value=c.model||'';key.value='';kept=c.has_key;key.placeholder=kept?'Ключ сохранён локально':'';render();}catch(e){status.textContent=e.message;}},isOpen:()=>dialog.open};
};

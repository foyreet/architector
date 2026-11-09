window.AIConnection = ({api, changed}) => {
  const el=(tag,text='')=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const dialog=el('dialog');dialog.id='ai-setup';dialog.setAttribute('aria-labelledby','ai-setup-title');
  const heading=el('div');heading.className='dialog-heading';const title=el('h2','Подключить AI');title.id='ai-setup-title';
  const close=el('button','×');close.setAttribute('aria-label','Закрыть настройку AI');close.onclick=()=>dialog.close();heading.append(title,close);
  const note=el('p','Выберите, откуда AI Chat будет получать ответы. Схема и документы передаются выбранной модели при отправке сообщения.');
  const provider=el('select');provider.id='ai-provider';provider.append(new Option('Другая модель · по адресу API','compatible'),new Option('Аккаунт ChatGPT · через Codex','codex'));
  const providerLabel=el('label','Способ подключения');providerLabel.append(provider);
  const fields=el('div');
  function field(label,id,type='text'){const l=el('label',label),i=el('input');i.id=id;i.type=type;l.append(i);fields.append(l);return i;}
  const base=field('Адрес API (с /v1)','ai-base-url');base.placeholder='http://localhost:11434/v1';
  const model=field('Название модели','ai-model-name');model.placeholder='Название установленной модели';
  const key=field('API-ключ, если требуется','ai-api-key','password');key.autocomplete='off';
  const hint=el('p','Для локальной модели ключ обычно не нужен. Модель должна поддерживать вызов инструментов.');hint.className='muted';fields.append(hint);
  const codex=el('section');codex.id='ai-codex-guide';codex.setAttribute('aria-labelledby','ai-codex-title');
  const codexTitle=el('h3');codexTitle.id='ai-codex-title';const codexText=el('p');codexText.id='ai-codex-state';codexText.setAttribute('role','status');
  const install=el('div');install.id='ai-codex-install';const steps=el('ol');
  const step1=el('li');const instruction=el('p');const command=el('code');command.id='ai-codex-command';
  const copy=el('button','Скопировать команду');copy.type='button';copy.id='ai-codex-copy';
  const help=el('a','Инструкция OpenAI по установке ↗');help.href='https://learn.chatgpt.com/docs/codex/cli';help.target='_blank';help.rel='noopener noreferrer';
  step1.append(instruction,command,copy,help);
  steps.append(step1,el('li','После установки нажмите «Проверить снова».'),el('li','Когда Codex найден, нажмите «Войти через ChatGPT».'));
  const installedHint=el('p','Уже установили, но программа не найдена? Перезапустите Архитектор из нового окна терминала, в котором работает команда codex.');installedHint.className='muted';
  install.append(steps,installedHint);
  const retry=el('button','Проверить снова');retry.id='ai-codex-recheck';retry.type='button';
  codex.append(codexTitle,codexText,install,retry);
  const status=el('p');status.id='ai-setup-status';status.setAttribute('role','status');
  const actions=el('div');actions.className='project-actions';
  const save=el('button','Сохранить подключение');save.className='primary';save.id='ai-save';
  const test=el('button','Сохранить и проверить API');test.id='ai-test';
  const mcp=el('details');const summary=el('summary','Подключить внешний AI через MCP');mcp.append(summary,el('p','Подключите Архитектор к своему AI-клиенту. Общение будет происходить в этом клиенте. MCP даёт доступ к схемам в локальной папке.'));
  const address=el('code',location.origin+'/mcp');address.id='ai-mcp-url';mcp.append(address,el('p','Транспорт: Streamable HTTP. Аккаунт и токен Архитектора не требуются; адрес доступен только на вашем компьютере.'));
  let kept=false,busy=false,checking=false,loading=false,capability=null,load=0;
  function render(){
    const useCodex=provider.value==='codex';fields.hidden=useCodex;codex.hidden=!useCodex;test.hidden=useCodex;
    save.textContent=useCodex?'Войти через ChatGPT':'Сохранить подключение';
    save.disabled=busy || loading || useCodex && (checking || !capability?.available);test.disabled=provider.disabled=busy||loading;retry.disabled=busy||checking;
    for(const input of [base,model,key])input.disabled=busy||loading;
    install.hidden=checking||!capability||capability.available;
    codexTitle.textContent=checking?'Проверяем подключение…':capability?.available?'Можно войти через ChatGPT':'Подготовьте подключение ChatGPT';
    codexText.textContent=checking?'Проверяем наличие программы Codex.':capability?.available?'Codex найден. Нажмите кнопку входа ниже и подтвердите вход на странице OpenAI. Доступ зависит от вашего аккаунта.':capability?'Архитектор пока не находит программу Codex. Она нужна, чтобы связать AI Chat с вашим аккаунтом ChatGPT.':'Не удалось проверить наличие Codex. Нажмите «Проверить снова».';
    if(capability){
      const windows=capability.platform==='win32';
      instruction.textContent=windows?'Установите Codex по инструкции OpenAI для вашей системы.':'Откройте приложение «Терминал» и выполните команду установки Codex:';
      command.textContent=capability.npm_available?'npm install -g @openai/codex@latest':'curl -fsSL https://chatgpt.com/codex/install.sh | sh';
      command.hidden=copy.hidden=windows;installedHint.hidden=false;
    }
  }
  async function check(){
    checking=true;status.textContent='';render();
    try{capability=(await api('/api/codex/config',{})).codex;}
    catch(e){capability=null;status.textContent='Не удалось проверить подключение. '+e.message;}
    finally{checking=false;render();}
  }
  retry.onclick=()=>check();
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(command.textContent);status.textContent='Команда скопирована. Вставьте её в терминал и выполните.';}catch{status.textContent='Не удалось скопировать автоматически. Выделите команду и скопируйте её вручную.';}};
  provider.onchange=()=>{status.textContent='';render();};
  async function configure(checkAPI=false){
    if(busy||save.disabled)return;busy=true;render();status.textContent=checkAPI?'Проверяем API…':provider.value==='codex'?'Открываем вход…':'Сохраняем…';
    try{
      const saved=await api('/api/codex/configure',{provider:provider.value,base_url:base.value,model:model.value,api_key:key.value,keep_key:kept});
      // Configuration is saved before a connection test: clear the key even when that test fails.
      kept=provider.value==='compatible'&&saved.has_key===true;key.value='';key.placeholder=kept?'Ключ сохранён локально':'';
      if(provider.value==='codex'){const result=await api('/api/codex/login',{});if(!result.connected&&!result.login)throw new Error('Вход ещё не готов. Нажмите «Проверить снова».');dialog.close();}
      else if(checkAPI){const result=await api('/api/codex/test',{});status.textContent=result.model_found?'API доступен, модель найдена. Можно написать сообщение.':'API доступен, но указанной модели нет в списке. Проверьте название.';}
      else{status.textContent='Подключение сохранено. Можно закрыть настройки и написать сообщение.';}
      await changed();
    }catch(e){status.textContent=e.message;}
    finally{busy=false;render();}
  }
  save.onclick=()=>configure();test.onclick=()=>configure(true);
  actions.append(save,test);dialog.append(heading,note,providerLabel,fields,codex,actions,status,mcp);document.body.append(dialog);render();
  return {open:async()=>{
    if(dialog.open)return;const request=++load;status.textContent='';capability=null;checking=loading=true;dialog.showModal();render();
    try{const c=await api('/api/codex/config',{});if(request!==load)return;provider.value=c.provider==='codex'?'codex':'compatible';base.value=c.base_url||'';model.value=c.model||'';key.value='';kept=c.has_key;key.placeholder=kept?'Ключ сохранён локально':'';capability=c.codex;}
    catch(e){status.textContent=e.message;}
    finally{if(request===load){checking=loading=false;render();}}
  },isOpen:()=>dialog.open};
};

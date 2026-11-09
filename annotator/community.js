window.Community = ({api, setConnection, openOpenRouter}) => {
  const $=id=>document.getElementById(id), dialog=$('community-dialog'),content=$('community-content');
  $('community-close').onclick=()=>dialog.close();
  $('community-title').textContent='Подключения';
  $('community-nav').hidden=true;$('community-account').hidden=true;
  function open(){
    content.replaceChildren();$('community-error').textContent='';
    const note=document.createElement('p');note.textContent='Необязательные сервисы. Используйте собственные ключи. Без подключений можно работать с локальными CSV и моделями.';content.append(note);
    for(const [kind,name] of [['kaggle','Kaggle'],['huggingface','Hugging Face']]){
      const label=document.createElement('label');label.textContent=name+' · ваш токен';
      const input=document.createElement('input');input.type='password';input.autocomplete='off';label.append(input);
      const button=document.createElement('button');button.textContent='Использовать в этой вкладке';button.onclick=()=>{setConnection(kind,input.value.trim());input.value='';button.textContent='Подключение задано';};content.append(label,button);
    }
    const router=document.createElement('button');router.textContent='Настроить OpenRouter';router.onclick=()=>{dialog.close();openOpenRouter();};content.append(router);
    const ai=document.createElement('button');ai.textContent='AI Chat и MCP';ai.onclick=()=>{dialog.close();$('codex-chat-open').click();};content.append(ai);
    if(!dialog.open)dialog.showModal();
  }
  $('connections').onclick=open;
  return {openAccount:open,refreshProject(){},openBlockRelease(){},addBlockRelease:async()=>false};
};

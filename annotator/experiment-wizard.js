'use strict';
window.ExperimentWizard=({api,beforeCreate,adopt,launch})=>{
  const el=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  const field=(parent,title,input)=>{const label=el('label',title);label.append(input);parent.append(label);return input;};
  const select=(items,value)=>{const n=el('select');for(const [key,text]of items)n.append(new Option(text,key));n.value=value;return n;};
  const table=(parent,headers,rows)=>{const wrap=el('div','','dataset-table'),t=el('table'),head=el('tr');headers.forEach(h=>head.append(el('th',h)));t.append(head);for(const values of rows){const row=el('tr');values.forEach(v=>row.append(el('td',String(v??''))));t.append(row);}wrap.append(t);parent.append(wrap);};
  async function open(){
    const d=el('dialog','','insight-dialog experiment-wizard');d.id='experiment-wizard';
    const heading=el('div','','dialog-heading'),close=el('button','×');close.type='button';close.setAttribute('aria-label','Закрыть мастер');heading.append(el('h2','Первый эксперимент с вашим CSV'),close);
    const steps=el('nav','','wizard-steps');steps.setAttribute('aria-label','Шаги мастера');const content=el('section'),error=el('p','','insight-error'),actions=el('div','','dialog-actions'),back=el('button','Назад'),next=el('button','Далее','primary');error.setAttribute('role','alert');actions.append(back,next);d.append(heading,steps,content,error,actions);document.body.append(d);d.showModal();
    let stage=0,busy=false,created=null,preview=null,view=null,requestId=crypto.randomUUID();
    let csv='',filename='',delimiter='auto',encoding='utf-8';
    const config={task:'classification',name:'',target:'',features:[],missing:'error',duplicates:'drop',test_size:.2,seed:42,hypothesis:''};
    const body=()=>({csv,filename,delimiter,config:{...config,features:[...config.features]}});
    const guard=async action=>{if(busy)return;busy=true;error.textContent='';back.disabled=next.disabled=close.disabled=true;try{await action();}catch(e){if(d.open)error.textContent=e.message;}finally{busy=false;back.disabled=stage===0||!!created;next.disabled=close.disabled=false;}};
    close.onclick=()=>d.close();d.addEventListener('cancel',e=>{if(busy)e.preventDefault();});d.onclose=()=>d.remove();
    function render(){
      error.textContent='';steps.replaceChildren();['1. Данные','2. Задача и признаки','3. Проверка схемы'].forEach((name,i)=>{const n=el('span',name,i===stage?'current':'');if(i===stage)n.setAttribute('aria-current','step');steps.append(n);});
      content.replaceChildren();back.hidden=stage===0||!!created;next.textContent=created?'Запустить пайплайн':stage===0?'Посмотреть данные':stage===1?'Проверить схему':'Создать проект';
      if(stage===0){
        content.append(el('p','Загрузите CSV с заголовками. Мастер соберёт классификацию — предсказание категории по числовым признакам.'));
        const file=field(content,'CSV-файл',el('input'));file.type='file';file.accept='.csv,text/csv';file.id='wizard-file';
        const settings=el('div','','wizard-grid');content.append(settings);
        const enc=field(settings,'Кодировка',select([['utf-8','UTF-8'],['windows-1251','Windows-1251 (старый Excel)']],encoding));enc.id='wizard-encoding';
        const sep=field(settings,'Разделитель',select([['auto','Определить автоматически'],[',','Запятая'],[';','Точка с запятой'],['\t','Табуляция']],delimiter));sep.id='wizard-delimiter';sep.onchange=()=>{delimiter=sep.value;};
        const fileStatus=el('p',filename?'Выбран файл: '+filename:'Выберите файл на компьютере.');content.append(fileStatus);
        async function read(){const chosen=file.files[0];if(!chosen)return;csv='';filename='';fileStatus.textContent='Чтение файла…';const text=new TextDecoder(encoding,{fatal:true}).decode(await chosen.arrayBuffer());csv=text;filename=chosen.name;config.name=chosen.name.replace(/\.csv$/i,'')+' · классификация';fileStatus.textContent='Выбран файл: '+filename;}
        file.onchange=()=>guard(async()=>{csv='';filename='';try{await read();}catch(e){throw new Error(e instanceof TypeError?'Не удалось прочитать текст. Проверьте кодировку файла.':e.message);}});
        enc.onchange=()=>guard(async()=>{encoding=enc.value;if(file.files[0])await read();else if(filename){csv='';filename='';fileStatus.textContent='Выберите файл снова для чтения в новой кодировке.';}});
        content.append(el('p','Файл отправляется в ваш аккаунт для проверки. На диск он сохраняется при создании проекта, отдельно от переносимого описания схемы.'));
      }else if(stage===1){
        content.append(el('p',`${filename} · ${view.profile.rows} строк · ${view.profile.columns.length} колонок`));
        table(content,Object.keys(view.sample[0]),view.sample.map(row=>Object.values(row).map(String)));
        content.append(el('h3','Что предсказываем?'),el('p','Выберите категорию, которую нужно предсказывать, например вид цветка или наличие дефекта.'));
        const target=field(content,'Целевая колонка',select([['','Выберите колонку'],...view.profile.columns.map(c=>[c.name,`${c.name} · ${c.unique} значений`])],config.target));target.id='wizard-target';
        const featureList=el('div','','wizard-features');content.append(el('h3','По каким признакам?'),el('p','Выберите только данные, доступные в момент будущего предсказания. Цель и сведения о результате нельзя использовать как признаки.'),featureList);
        function features(){featureList.replaceChildren();for(const c of view.profile.columns){if(c.name===config.target)continue;const label=el('label'),check=el('input');check.type='checkbox';check.value=c.name;check.checked=config.features.includes(c.name);check.disabled=!c.eligible;check.onchange=()=>{config.features=[...featureList.querySelectorAll('input:checked')].map(n=>n.value);};label.append(check,el('span',`${c.name} · ${c.eligible?(c.invalid_numeric?'смешанный':'число'):'нечисловой / пустой'} · пропусков ${c.missing} · нечисловых ${c.invalid_numeric}`));featureList.append(label);}}
        target.onchange=()=>{config.target=target.value;config.features=view.profile.columns.filter(c=>c.recommended&&c.name!==config.target).map(c=>c.name);features();};features();
        const settings=el('div','','wizard-grid');content.append(settings);
        const missing=field(settings,'Пропуски и некорректные значения',select([['error','Остановить и объяснить ошибку'],['drop','Удалить такие строки']],config.missing));missing.id='wizard-missing';missing.onchange=()=>config.missing=missing.value;
        const dup=field(settings,'Дубли признаков и цели',select([['drop','Удалить перед разделением'],['keep','Сохранить']],config.duplicates));dup.onchange=()=>config.duplicates=dup.value;
        const split=field(settings,'Доля Test для проверки качества',el('input'));split.type='number';split.step='any';split.min=0;split.max=1;split.value=config.test_size;split.id='wizard-test-size';split.onchange=()=>config.test_size=Number(split.value);
        const seed=field(settings,'Seed для повторения эксперимента',el('input'));seed.type='number';seed.min=0;seed.max=4294967295;seed.value=config.seed;seed.oninput=()=>config.seed=Number(seed.value);
        const name=field(content,'Название проекта',el('input'));name.id='wizard-name';name.value=config.name;name.oninput=()=>config.name=name.value;
        const hypothesis=field(content,'Гипотеза (необязательно)',el('textarea'));hypothesis.rows=2;hypothesis.value=config.hypothesis;hypothesis.oninput=()=>config.hypothesis=hypothesis.value;
      }else{
        content.append(el('h3',created?'Проект создан':'Готовая схема'),el('p',preview.compute),el('p',`${preview.preparation.input_rows} строк на входе → ${preview.preparation.rows} после подготовки · Train ${preview.train_rows} · Test ${preview.test_rows}`));
        content.append(el('p','Цель: '+preview.target+' · признаки: '+preview.features.join(', ')));
        for(const message of preview.warnings)content.append(el('p',message,'wizard-warning'));
        table(content,['Класс','Строк после подготовки'],Object.entries(preview.preparation.classes));
        const list=el('ol','','wizard-pipeline');for(const step of preview.steps){const item=el('li');item.append(el('strong',step.name),el('p',step.description));list.append(item);}content.append(list);
        content.append(el('p',created?'Выберите вычисления в меню «⋯» рядом с названием схемы. Нажмите «Запустить пайплайн», чтобы сразу начать обучение. После завершения откройте «Результаты»: там будут метрики и сохранённая модель.':'Будет создан отдельный проект. Обучение запускается после проверки параметров кнопкой «Запустить пайплайн».'));
      }
    }
    back.onclick=()=>{if(busy)return;stage--;render();};
    next.onclick=()=>guard(async()=>{
      if(created){d.close();launch();return;}
      if(stage===0){if(!csv)throw new Error('Сначала выберите CSV-файл.');view=await api('/api/wizard/inspect',body());filename=view.filename;config.target='';config.features=view.profile.columns.filter(c=>c.recommended).map(c=>c.name);stage=1;}
      else if(stage===1){preview=await api('/api/wizard/preview',body());stage=2;}
      else {await beforeCreate();const project=await api('/api/wizard/create',{...body(),digest:preview.digest,request_id:requestId});await adopt(project);created=project;}
      if(d.open)render();
    });render();
  }
  return {open};
};


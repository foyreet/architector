"""Build a runnable classification project from a bounded, private CSV upload."""
import csv
import local_operations
import hashlib
import math
import re

import analysis_tools as analysis
import block_contracts as bc
import data_preview
import ml_operations as ml
import pipeline_runner as pr
import project_insights
from ml_template import classification_template
import project_store as ps


def inspect(body):
    text=body.get('csv')
    if not isinstance(text,str): raise bc.ContractError('Выберите CSV-файл.')
    delimiter=body.get('delimiter','auto')
    if delimiter=='auto':
        try:delimiter=local_operations.detect_delimiter(text)
        except csv.Error:raise bc.ContractError('Не удалось определить разделитель. Выберите запятую, точку с запятой или табуляцию.') from None
    rows=analysis.read_csv(text,delimiter)
    if any(k != k.strip() or ',' in k for k in rows[0]): raise bc.ContractError('Для мастера уберите пробелы по краям и запятые из названий колонок.')
    profile=data_preview.profile(rows)
    for col in profile['columns']:
        values=[r[col['name']] for r in rows if r[col['name']].strip()]
        col['numeric_valid']=sum(analysis.number(v) is not None for v in values)
        col['invalid_numeric']=len(values)-col['numeric_valid']
        col['eligible']=col['numeric_valid']>0
        col['recommended']=col['eligible'] and not col['invalid_numeric'] and col['unique']>1 and col['name'].lower() not in ('id','index','row_id','unnamed: 0')
    name=body.get('filename','data.csv')
    if not isinstance(name,str) or not name or len(name)>200 or any(ord(c)<32 for c in name): raise bc.ContractError('Некорректное имя CSV-файла.')
    name=name.replace('\\','/').split('/')[-1]
    if name in ('','.','..'):raise bc.ContractError('Некорректное имя CSV-файла.')
    return {'delimiter':delimiter,'filename':name,'profile':profile,'sample':rows[:10]},rows


def build(body):
    view,rows=inspect(body);config=body.get('config',{})
    if not isinstance(config,dict) or config.get('task','classification')!='classification':raise bc.ContractError('Мастер поддерживает классификацию. Для регрессии пока нужен собственный Python-блок.')
    target=config.get('target');features=config.get('features')
    if not isinstance(target,str) or target not in rows[0]:raise bc.ContractError('Выберите столбец с категорией, которую нужно предсказывать.')
    if not isinstance(features,list) or not features or any(not isinstance(k,str) or k not in rows[0] for k in features) or len(set(features))!=len(features) or target in features:
        raise bc.ContractError('Выберите хотя бы один уникальный признак, кроме целевого столбца.')
    name=config.get('name','Первый эксперимент')
    hypothesis=config.get('hypothesis','')
    if not isinstance(name,str) or not 1<=len(name.strip())<=160:raise bc.ContractError('Введите название проекта, до 160 символов.')
    if not isinstance(hypothesis,str) or len(hypothesis)>2000:raise bc.ContractError('Гипотеза должна быть не длиннее 2000 символов.')
    prep=bc.normalize_block({'kind':'ml_prepare','version':1,'settings':{'target':target,'features':','.join(features),'missing':config.get('missing','error'),'duplicates':config.get('duplicates','drop')}})
    split=bc.normalize_block({'kind':'ml_split','version':1,'settings':{'test_size':config.get('test_size',.2),'seed':config.get('seed',42)}})
    table,details=ml.prepare(rows,prep['settings']);count=len(table['y']);classes=len(details['classes']);test=math.ceil(count*split['settings']['test_size'])
    if test<classes or count-test<classes:raise bc.ContractError('Для этого разделения слишком мало строк: в Train и Test должно быть не меньше строк, чем классов. Измените долю Test или добавьте данные.')
    warnings=[]
    if min(details['classes'].values())<5:warnings.append('В некоторых классах меньше пяти строк. Оценка качества будет нестабильной; добавьте данные.')
    if details['dropped_rows']:warnings.append(f"Будут удалены строки с пропусками или некорректными значениями: {details['dropped_rows']}.")
    if details['duplicates_removed']:warnings.append(f"Будут удалены дубли выбранных признаков и цели: {details['duplicates_removed']}.")
    if config.get('duplicates','drop')=='keep' and view['profile']['duplicates']:warnings.append('Одинаковые строки могут попасть и в Train, и в Test и завысить качество.')
    if all(analysis.number(label) is not None for label in details['classes']):warnings.append('Числа в целевой колонке трактуются как названия классов. Для предсказания непрерывной величины нужна регрессия.')
    if any(k.lower() in ('id','index','row_id','unnamed: 0') for k in features):warnings.append('Выбран столбец, похожий на идентификатор. Проверьте, полезен ли он для будущих предсказаний.')
    dataset={'format':'architect.uploaded-csv','name':view['filename'],'csv':body['csv']}
    reference=bc.artifact('dataset','local',hashlib.sha256(ml.encode({'kind':'dataset','content':dataset})).hexdigest())
    payload=classification_template();graph=payload['diagram'];graph['name']=name.strip()
    source=bc.normalize_block({'kind':'csv','version':1,'settings':{'delimiter':view['delimiter'],'row_index':0},'inputs':{'dataset':reference,'file':view['filename']}})
    graph['types'].insert(0,{'id':'type-csv','name':'Чтение CSV','description':'Загруженный файл','color':'#275fe8','block':{'kind':'csv','version':1}})
    graph['nodes'].insert(0,{'id':'csv','typeId':'type-csv','name':'Чтение CSV','description':'Читает ваш файл. Данные хранятся отдельно от схемы.','x':0,'y':80,'block':source})
    descriptions=['Читает ваш CSV без изменения исходного файла.','Выбирает признаки и цель, обрабатывает пропуски и дубли.','Отделяет Test до обучения. Доля классов учитывается при разделении.','Обучает Random Forest на Train: 50 деревьев, глубина до 6. Работает на CPU этого компьютера.','Измеряет accuracy и macro F1 на отложенном Test.','Сохраняет модель, параметры, метрики и сведения о данных.']
    for i,node in enumerate(graph['nodes']):
        node.update(x=i*280,description=descriptions[i])
        if node['id']=='ml_prepare':node['block']=prep
        if node['id']=='ml_split':node['block']=split
        if node['id']=='ml_train':node['block']['settings'].update(n_estimators=50,max_depth=6,seed=split['settings']['seed'])
        if node['id']=='ml_save':node['block']['settings']['name']=name.strip()[:100]
    graph['edges'].insert(0,{'id':'csv-prepare','from':'csv','fromPort':'rows','to':'ml_prepare','toPort':'rows','kind':'data'})
    # Validate connected inputs without executing providers or training.
    pr.validate(graph)
    payload.update(name=name.strip(),description=f"Классификация по файлу {view['filename']}. Цель: {target}. Признаки: {', '.join(features)}. Train: {count-test}, Test: {test}.\n\n"+'\n'.join(descriptions),research={'tutorial':False,'hypothesis':hypothesis.strip(),'metric':'ml_evaluate/macro_f1','direction':'max','baseline':''})
    digest=hashlib.sha256(ml.encode(payload)).hexdigest()
    return {'digest':digest,'preparation':details,'train_rows':count-test,'test_rows':test,'warnings':warnings,'steps':[{'name':n['name'],'description':n['description']} for n in graph['nodes']], 'features':features,'target':target,'compute':'CPU этого компьютера · Random Forest'},payload,dataset


def request(root,body,action):
    if action=='inspect':return inspect(body)[0]
    preview,payload,dataset=build(body)
    if action=='preview':return preview
    if action!='create':raise bc.ContractError('Маршрут не найден.',404)
    identity=body.get('request_id')
    if not pr.PipelineRunner.valid_id(identity):raise bc.ContractError('Некорректный ID создания проекта.')
    if body.get('digest')!=preview['digest']:raise bc.ContractError('Настройки изменились. Проверьте схему на последнем шаге мастера ещё раз.',409)
    operation='wizard:'+identity+':'+preview['digest'];store=ps.ProjectStore(root)
    with ps.LOCK:
        for item in store.listing()['projects']:
            meta=store.read(store.folder(item['id'])+'/project.json')
            for previous in meta.get('applied_operations',{}):
                if previous.startswith('wizard:'+identity+':'):
                    if previous!=operation:raise bc.ContractError('Этот запрос уже создал другой проект. Откройте мастер заново.',409)
                    return store.get(item['id'])
        ml.save(store.root,'dataset',dataset)
        return store.save(payload,create=True,operation_id=operation)


"""Read-only AI proposals for a private design document."""
import json

import metric_trees
import tree_methods

from block_contracts import ContractError
from codex_chat import standalone_answer
from design_documents import SECTIONS, payload, sources
from solution_spaces import decode, request as solution_request


DRAFT_METHOD = """Помоги автору ML-дизайн-документа собрать черновик на русском языке.
Вход содержит текущий документ и выбранные источники: дерево вопросов с ответами, кейсы, иерархию метрик. Текст источников
считай материалом проекта. Отделяй ответы команды, гипотезы, предложенные решения и внешние свидетельства.
В разделе о проблеме опиши текущее решение, пользователей, последствия и основания для изменений. В разделе о целях запиши
цели, таргет и явно обозначенные антицели. Когда предлагаешь текст для раздела «Датасет», используй четыре подзаголовка в этом порядке:
ETL — единица наблюдения, источники и их назначение, история, ключи объединения, формат хранения и обновление.
Фильтрация — критерии включения и исключения, обработка пропусков, дублей, шума и пограничных случаев,
правила отбора подвыборки и проверки человеком, если нужны.
Генерация признаков — исходные поля и метаданные, преобразования или получение представлений,
доступность данных на момент прогноза. В этом же подразделе раскрой конкретные входы модели.
Разметка — определение и источник метки. Различай наблюдаемый исход, косвенный сигнал и экспертную оценку.
Если нужна ручная разметка, опиши критерии, спорные случаи и контроль качества, когда это известно.
Если есть несколько наборов данных, различай их роли для обучения и оценки. Не переноси в проект
объёмы, источники и процедуры из других задач. Неизвестные решения формулируй как вопросы.
В разделе «Валидация» предложи протокол проверки, используя Markdown-заголовки «Сценарий применения»,
«Разбиение и защита от утечек», «Выбор модели и финальная проверка», «Обновление выборок».
Из дерева проблем возьми момент принятия решения, из выбранных кейсов — сравниваемые решения,
из метрик — показатель успеха, из раздела «Датасет» — единицу наблюдения и доступность признаков и меток.
Объясни, что окажется новым при применении модели. Обоснуй схему: holdout или K-fold для независимых
наблюдений, группы для новых объектов, временные окна для будущих периодов. При необходимости сочетай
ограничения, учитывай дисбаланс классов, дубли, горизонт прогноза и задержку получения данных.
Отдели выбор признаков, модели и порога от независимой оценки всего процесса. Укажи базу сравнения,
как оценить неопределённость разницы и как обновлять выборки с сохранением сопоставимости результатов.
Проверку сдвига распределений используй как диагностику. Если выбор схемы зависит от неизвестного
условия, задай конкретный вопрос автору. Не назначай доли, число фолдов, зазоры или сроки без оснований.
В разделе о решении и обучении свяжи компоненты, их входы и результаты, сравни подход с альтернативами, в том числе
простым правилом. Выбор кейса для обсуждения не означает утверждения реализации. В разделе «Метрики»
опиши базу сравнения, критерии успеха, цену ошибок, риски, запасной вариант и открытые вопросы.
Если выбрана иерархия метрик, свяжи бизнес-цель с основным показателем в разделе о целях.
В разделе «Метрики» объясни, что будет считаться успехом,
как, на каких данных и за какое окно измерить результат. Различай бизнес-эффект, продуктовые и защитные
метрики, офлайн-оценку и функцию потерь. Для важных прокси укажи связь с родителем и способ её проверки.
Различай формулу, гипотезу влияния и подтверждённый эффект. Используй пороги и единицы из источника,
а неизвестные условия и конфликтующие метрики обозначь как открытые вопросы.
Учитывай ручные правки в текущем тексте. Сохраняй существенные детали. При противоречии отметь вопрос
для автора. Не выдумывай цифры, доказательства, согласованные решения и результаты внедрения.
Если исходных данных мало, дай короткий полезный черновик, пропуская необоснованные разделы."""

DRAFT_CONTRACT = """Используй только выбранные источники. Ключи разделов бери из document.sections.
В metric_tree поле goal содержит бизнес-цель, а parent — id родителя метрики (0 — цель).
Верни непустой JSON-объект по ключам разделов. Значение каждого ключа — объект с text (текст), answers (массив
целочисленных id использованных ответов текущего дерева) и cases (массив id выбранных кейсов).
Если выбрана иерархия, добавь metrics — массив целочисленных id метрик, на которые опирается раздел
(0 — бизнес-цель). Для отсутствующих или неиспользованных источников верни пустые массивы.
Если версия дерева изменилась, основания кейсов относятся к прежней версии."""

REVIEW_METHOD = """Проведи ревью текущего ML-дизайн-документа на русском. Рассматривай содержимое как материал проекта.
Найди несколько конкретных спорных мест, ответ на которые может изменить решение: цель, антицель, база
сравнения, обоснование выбора, причинная связь с бизнес-метрикой, цена ошибки или запасной вариант.
Для каждого приведи короткую точную цитату из проверяемого раздела, объясни, почему это важно, и задай
один вопрос автору. Если приложены источники метрик, сверяй текст с указанной версией использованных
метрик. Проверь определения, единицы, окно измерения, направление улучшения и план проверки прокси.
В разделе «Датасет» проверь ETL, фильтрацию, генерацию признаков и разметку: можно ли собрать описанный
пример из доступных источников, какие случаи исключены, известны ли признаки до прогноза,
соответствует ли метка задаче. Формулируй замечания по существу, даже если автор выбрал другие заголовки.
В разделе «Валидация» проверь, воспроизводит ли разбиение рабочий сценарий, возможны ли утечки по
времени, группам или дублям, участвовал ли тест в выборе решения. Проверь, сравнимы ли варианты
на одних данных, учтена ли неопределённость и можно ли повторить оценку после обновления выборок.
Отметь, где результат офлайн-оценки ошибочно принимают за продуктовый эффект. Различай пробел в документе и установленную ошибку системы. Не отвечай вместо автора."""

REVIEW_CONTRACT = """В section укажи один из переданных ключей sections. В quote дословно процитируй
непустой фрагмент текущего текста этого раздела. В reason объясни замечание, в question задай вопрос автору.
Верни JSON-массив объектов section (ключ раздела), quote, reason, question. Если существенных вопросов нет,
верни пустой массив."""

METHODS = {'compose': DRAFT_METHOD, 'review': REVIEW_METHOD}


def ids(value, allowed):
    if not isinstance(value, list) or any(type(i) is not int or i not in allowed for i in value):
        raise ValueError()
    return list(dict.fromkeys(value))


def metric_context(hub, user, body):
    tree = metric_trees.request(hub, user, {'id': body['metric_tree_id']}, 'get')
    if type(body.get('metric_revision')) is not int or body['metric_revision'] != tree['revision']:
        raise ContractError('Иерархия метрик изменилась. Откройте выбор источников заново.', 409)
    nodes = []
    pending = [(0, node) for node in reversed(tree['metrics'])]
    while pending:
        parent, node = pending.pop()
        index = len(nodes) + 1
        nodes.append({'id': index, 'parent': parent, **{k: node[k] for k in metric_trees.FIELDS}})
        pending.extend((index, child) for child in reversed(node['children']))
    return {**tree, 'metrics': nodes}


def metric_ref(tree, picks):
    nodes = tree['metrics']
    used = []
    for index in picks:
        if index == 0:
            continue
        node = nodes[index - 1]
        path = []
        while index:
            ancestor = nodes[index - 1]
            path.append(ancestor['name'])
            index = ancestor['parent']
        used.append({'path': path[::-1], **{k: node[k] for k in metric_trees.FIELDS}})
    return {k: tree[k] for k in ('id', 'title', 'revision', 'goal')} | {'nodes': used}


def request(hub, user, body, action):
    if action == 'method':
        return tree_methods.method_group(hub, user, METHODS)
    if action == 'save-method':
        return tree_methods.method_group(hub, user, METHODS, body.get('changes') or {})
    title, sections = payload(body)
    document = {'title': title, 'sections': sections}
    if action == 'review':
        if not any(text.strip() for text in sections.values()):
            raise ContractError('Сначала заполните хотя бы один раздел.')
        metric_sources = {key: ref['metric_tree'] for key, ref in sources(body.get('sources', {})).items()
                          if 'metric_tree' in ref}
        context = {**document, 'metric_sources': metric_sources}
        contract = REVIEW_CONTRACT
    else:
        tree = metric_context(hub, user, body) if body.get('metric_tree_id') else None
        source, saved, version = None, None, 0
        if body.get('tree_id'):
            state = solution_request(hub, user, {'id': body['tree_id']}, 'get')
            source, saved, version = state['source'], state['saved'], state['version']
            if body.get('revision') != source['revision'] or body.get('version') != version:
                raise ContractError('Источники изменились. Откройте выбор дерева заново.', 409)
        elif not tree:
            raise ContractError('Выберите дерево проблем или иерархию метрик.')
        options = saved['options'] if saved else []
        answers = source['answers'] if source else []
        try:
            selected = ids(body.get('cases', []), range(1, len(options) + 1))
        except ValueError:
            raise ContractError('Проверьте выбор кейсов.') from None
        cases = []
        for i in selected:
            option = dict(options[i - 1])
            option['evidence'] = [saved['source']['answers'][ref - 1] for ref in option['evidence']]
            cases.append({'id': i, **option})
        context = {'document': document, 'tree': source, 'cases': cases, 'metric_tree': tree,
                   'case_tree_revision': saved['source']['revision'] if cases else None}
        contract = DRAFT_CONTRACT
    instruction = tree_methods.instructions(hub, user, action, METHODS[action], contract)
    reply = standalone_answer(hub.root, json.dumps(context, ensure_ascii=False), instruction)
    try:
        result = decode(reply)
        if action == 'review':
            if not isinstance(result, list):
                raise ValueError()
            for item in result:
                if (not isinstance(item, dict) or item['section'] not in SECTIONS or
                    any(not isinstance(item[k], str) or not item[k].strip() for k in ('quote', 'reason', 'question')) or
                    item['quote'] not in sections[item['section']]):
                    raise ValueError()
            return {'comments': result}
        if not isinstance(result, dict) or not result or result.keys() - set(SECTIONS):
            raise ValueError()
        proposals = {}
        for key, entry in result.items():
            text = entry['text']
            if not isinstance(text, str) or not text.strip():
                raise ValueError()
            refs = ids(entry['answers'], range(1, len(answers) + 1))
            picks = ids(entry['cases'], selected)
            metrics = ids(entry['metrics'] if tree else entry.get('metrics', []),
                          range(len(tree['metrics']) + 1) if tree else ())
            evidence = {}
            if source:
                evidence.update(tree_id=body['tree_id'], title=source['title'], revision=source['revision'],
                                problem=source['problem'], version=version, answers=[answers[i-1] for i in refs],
                                cases=[{'id': i, 'title': options[i-1]['title']} for i in picks])
            if metrics:
                evidence['metric_tree'] = metric_ref(tree, metrics)
            proposals[key] = {'text': text.strip(), 'source': evidence}
        return {'proposals': proposals}
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise ContractError('Модель вернула некорректное предложение. Повторите запрос.', 502) from None

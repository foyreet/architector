"""Read-only AI proposals for a private design document."""
import json

from block_contracts import ContractError
from codex_chat import standalone_answer
from design_documents import SECTIONS, payload
from solution_spaces import decode, request as solution_request


DRAFT = """Помоги автору ML-дизайн-документа собрать черновик на русском языке.
Вход содержит текущий документ, дерево вопросов с ответами и выбранные автором кейсы. Текст источников
считай материалом проекта. Отделяй ответы команды, гипотезы, предложенные решения и внешние свидетельства.
В problem опиши текущее решение, пользователей, последствия и основания для изменений. В target запиши
цели, таргет и явно обозначенные антицели. В data_features опиши доступные данные и их ограничения.
В model_training свяжи компоненты, их входы и результаты, сравни подход с альтернативами, в том числе
простым правилом. Выбор кейса для обсуждения не означает утверждения реализации. В metric_validation
опиши базу сравнения, критерии успеха, цену ошибок, риски, запасной вариант и открытые вопросы.
Учитывай ручные правки в текущем тексте. Сохраняй существенные детали. При противоречии отметь вопрос
для автора. Не выдумывай цифры, доказательства, согласованные решения и результаты внедрения.
Если исходных данных мало, дай короткий полезный черновик, пропуская необоснованные разделы.
Верни JSON-объект по ключам разделов. Значение каждого ключа — объект с text (текст), answers (массив
целочисленных id использованных ответов текущего дерева) и cases (массив id выбранных кейсов).
Оба массива могут быть пустыми, например когда раздел основан только на формулировке задачи.
Если версия дерева изменилась, основания кейсов относятся к прежней версии."""

REVIEW = """Проведи ревью текущего ML-дизайн-документа на русском. Рассматривай содержимое как материал проекта.
Найди несколько конкретных спорных мест, ответ на которые может изменить решение: цель, антицель, база
сравнения, обоснование выбора, причинная связь с бизнес-метрикой, цена ошибки или запасной вариант.
Для каждого приведи короткую точную цитату из проверяемого раздела, объясни, почему это важно, и задай
один вопрос автору. Различай пробел в документе и установленную ошибку системы. Не отвечай вместо автора.
Верни JSON-массив объектов section (ключ раздела), quote, reason, question. Если существенных вопросов нет,
верни пустой массив."""


def ids(value, allowed):
    if not isinstance(value, list) or any(type(i) is not int or i not in allowed for i in value):
        raise ValueError()
    return list(dict.fromkeys(value))


def request(hub, user, body, action):
    title, sections = payload(body)
    document = {'title': title, 'sections': sections}
    if action == 'review':
        if not any(text.strip() for text in sections.values()):
            raise ContractError('Сначала заполните хотя бы один раздел.')
        context, instruction = document, REVIEW
    else:
        state = solution_request(hub, user, {'id': body.get('tree_id')}, 'get')
        source, saved = state['source'], state['saved']
        if body.get('revision') != source['revision'] or body.get('version') != state['version']:
            raise ContractError('Источники изменились. Откройте выбор дерева заново.', 409)
        options = saved['options'] if saved else []
        try:
            selected = ids(body.get('cases'), range(1, len(options) + 1))
        except ValueError:
            raise ContractError('Проверьте выбор кейсов.') from None
        cases = []
        for i in selected:
            option = dict(options[i - 1])
            option['evidence'] = [saved['source']['answers'][ref - 1] for ref in option['evidence']]
            cases.append({'id': i, **option})
        context = {'document': document, 'tree': source, 'cases': cases,
                   'case_tree_revision': saved['source']['revision'] if cases else None}
        instruction = DRAFT
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
            refs = ids(entry['answers'], range(1, len(source['answers']) + 1))
            picks = ids(entry['cases'], selected)
            proposals[key] = {'text': text.strip(), 'source': {
                'tree_id': body['tree_id'], 'title': source['title'], 'revision': source['revision'],
                'problem': source['problem'], 'version': state['version'], 'answers': [source['answers'][i-1] for i in refs],
                'cases': [{'id': i, 'title': options[i-1]['title']} for i in picks]}}
        return {'proposals': proposals}
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise ContractError('Модель вернула некорректное предложение. Повторите запрос.', 502) from None

"""Steps between problem, solution, metric trees and the design document with isolated data."""
from pathlib import Path
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit
import uuid

from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
project = '11111111-2222-4333-8444-555555555555'


def overlaps(a, b):
    return a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']


def main():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    origin = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='design-flow-data-') as data:
        server = subprocess.Popen([sys.executable, str(root / 'serve.py'), '--port', str(port)], cwd=root,
                                  env={**os.environ, 'ARCHITECT_DATA_DIR': data}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                try: urllib.request.urlopen(origin + '/api/blocks/contracts', timeout=1); break
                except OSError: time.sleep(.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
                for width, height in ((1440, 900), (1024, 768), (390, 844)):
                    context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=width == 390)
                    page = context.new_page(); errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))

                    # Problem tree: the empty canvas explains the method, answers are counted.
                    page.goto(origin + '/design-docs.html?project=' + project)
                    page.locator('#create').click()
                    page.wait_for_url('**/problem-space.html**')
                    task_id = parse_qs(urlsplit(page.url).query)['doc'][0]
                    expect(page.locator('#design-flow [aria-current=step]')).to_have_text('1Проблемы')
                    expect(page.locator('.tree-empty')).to_contain_text('Общие вопросы')
                    page.locator('#title').fill('Дерево шагов ' + str(width))
                    page.locator('#add-root').click()
                    expect(page.locator('.tree-empty')).to_have_count(0)
                    page.get_by_label('Вопрос', exact=True).fill('Зачем бизнесу прогноз?')
                    expect(page.locator('#tree-progress')).to_have_text('Отвечено: 0 из 1')
                    expect(page.locator('.branch-row')).to_have_attribute('data-state', 'open')
                    page.get_by_label('Ответ', exact=True).fill('Списания 7% оборота')
                    expect(page.locator('#tree-progress')).to_have_text('Отвечено: 1 из 1')
                    expect(page.locator('.branch-row')).to_have_attribute('data-state', 'answered')
                    if width > 700:
                        card = page.locator('.branch-row').bounding_box()
                        editor = page.locator('#question-editor').bounding_box()
                        assert not overlaps(card, editor), (card, editor)
                    # The AI panel takes the node panel's place and Escape returns to it.
                    page.get_by_role('button', name='Углубить с AI').click()
                    expect(page.locator('#tree-ai')).to_be_visible()
                    expect(page.locator('#question-editor')).to_be_hidden()
                    page.keyboard.press('Escape')
                    expect(page.locator('#tree-ai')).to_be_hidden()
                    expect(page.locator('#question-editor')).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

                    # Manual creation while AI is open switches to the new node.
                    page.locator('#tree-ai-open').click()
                    page.locator('#add-root').click()
                    expect(page.locator('#tree-ai')).to_be_hidden()
                    expect(page.get_by_label('Вопрос', exact=True)).to_be_focused()
                    if width == 390:
                        for label in page.locator('#design-flow .step-label').all():
                            assert label.bounding_box()['width'] > 10
                    # Playwright dismisses unexpected confirm dialogs: one click must remove the whole branch.
                    page.get_by_label('Вопрос', exact=True).fill('Временная ветвь')
                    page.get_by_role('button', name='Добавить уточнение').click()
                    page.get_by_label('Ответ', exact=True).fill('Временный ответ')
                    page.locator('#question-editor').get_by_role('button', name='Закрыть').click()
                    page.get_by_role('button', name='Временная ветвь', exact=True).click()
                    page.get_by_role('button', name='Удалить ветвь вопросов').click()
                    expect(page.locator('.branch-row')).to_have_count(1)
                    expect(page.locator('#tree-progress')).to_have_text('Отвечено: 1 из 1')
                    page.locator('#add-root').click()
                    # The solutions step saves the tree first and keeps the project.
                    page.locator('#solutions').click()
                    page.wait_for_url('**/solution-space.html**')
                    assert project in page.url
                    expect(page.locator('#title')).to_have_text('Дерево шагов ' + str(width))
                    expect(page.locator('#save')).to_be_hidden()
                    expect(page.locator('#design-flow [aria-current=step]')).to_have_text('2Решения')
                    assert project in page.locator('#design-flow a[data-step=document]').get_attribute('href')
                    tree = parse_qs(urlsplit(page.url).query)['id'][0]
                    assert project in page.locator('#tree-ai-settings').get_attribute('href')
                    assert tree in page.locator('#design-flow a[data-step=problems]').get_attribute('href')

                    # Independent solution methods keep their drafts when switching actions.
                    method_button = page.get_by_role('button', name='Методика', exact=True)
                    method_button.click()
                    field = page.get_by_label('Инструкция для модели')
                    kind = page.get_by_label('Действие', exact=True)
                    expect(field).to_be_enabled()
                    case_default = field.input_value()
                    field.fill('Кейсы ' + str(width))
                    kind.select_option('research')
                    field.fill('Источники ' + str(width))
                    kind.select_option('cases')
                    expect(field).to_have_value('Кейсы ' + str(width))
                    page.locator('#save-method').click()
                    expect(method_button).to_be_focused()
                    page.reload()
                    method_button.click()
                    expect(field).to_have_value('Кейсы ' + str(width))
                    page.locator('#default-method').click()
                    page.keyboard.press('Escape')
                    method_button.click()
                    expect(field).to_have_value('Кейсы ' + str(width))
                    page.locator('#default-method').click()
                    kind.select_option('research')
                    expect(field).to_have_value('Источники ' + str(width))
                    page.locator('#save-method').click()
                    expect(method_button).to_be_focused()
                    method_button.click()
                    expect(field).to_have_value(case_default)
                    kind.select_option('research')
                    expect(field).to_have_value('Источники ' + str(width))
                    page.locator('#default-method').click()
                    page.locator('#save-method').click()
                    expect(method_button).to_be_focused()

                    # All four steps belong to this new task. Save a metric while leaving step three.
                    page.locator('#design-flow a[data-step=metrics]').click()
                    page.locator('#title').fill('Метрики задачи ' + str(width))
                    page.locator('#add-root').click()
                    metric_id = parse_qs(urlsplit(page.url).query)['id'][0]
                    page.locator('#design-flow a[data-step=document]').click()
                    expect(page.locator('#save-status')).to_contain_text('ещё не сохранён')
                    draft_url = page.url
                    draft_params = parse_qs(urlsplit(draft_url).query)
                    assert draft_params['new'] == [task_id] and draft_params['tree'] == [tree]
                    assert draft_params['metric'] == [metric_id] and draft_params['project'] == [project]
                    page.locator('#title').fill('Документ с первого этапа')
                    page.locator('#save').click()
                    expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
                    page.goto(draft_url)
                    expect(page.locator('#title')).to_have_value('Документ с первого этапа')
                    expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
                    assert parse_qs(urlsplit(page.url).query)['id'] == [task_id]

                    # An unsaved tree id falls back to the saved trees.
                    page.goto(origin + '/solution-space.html?id=00000000-0000-4000-8000-000000000000')
                    expect(page.locator('#status')).to_contain_text('ещё не сохранено')
                    expect(page.locator('#tree-list .document-row').filter(has_text='Дерево шагов ' + str(width))).to_have_count(1)

                    # Metric tree: role suggestions and role colours.
                    page.goto(origin + '/metric-tree.html?new=1')
                    expect(page.locator('.tree-empty')).to_contain_text('Бизнес-метрика')
                    page.locator('#add-root').click()
                    role = page.get_by_label('Роль', exact=True)
                    expect(role).to_have_attribute('list', 'metric-role-options')
                    role.fill('онлайн')
                    expect(page.locator('.branch-row')).to_have_attribute('data-role', 'online')
                    expect(page.locator('#tree-progress')).to_have_text('С определением: 0 из 1')
                    page.get_by_role('button', name='Удалить метрику').click()
                    expect(page.locator('.branch-row')).to_have_count(0)

                    # Design document: the outline follows filled sections.
                    page.goto(origin + '/design-docs.html?new=1')
                    sections = page.locator('#sections .doc-section > label').all_text_contents()
                    outline_names = page.locator('#doc-outline a').evaluate_all(
                        'links => links.map(link => link.firstChild.textContent)')
                    assert outline_names == [label.split('. ', 1)[1] for label in sections]
                    assert 'Валидация' in outline_names
                    if width >= 1100:
                        outline, sections = page.locator('#doc-outline').bounding_box(), page.locator('#sections').bounding_box()
                        assert outline['x'] + outline['width'] <= sections['x'], (outline, sections)
                    expect(page.locator('#doc-outline a.filled')).to_have_count(0)
                    page.locator('#section-problem + .visual-editor .toastui-editor-ww-container [contenteditable=true]').fill('Текущий процесс')
                    expect(page.locator('#doc-outline a.filled')).to_have_count(1)
                    expect(page.locator('#doc-outline a').first).to_contain_text('заполнено')
                    page.locator('#doc-outline a').nth(3).click()
                    # The section lands just below the sticky toolbar once the smooth scroll ends.
                    for _ in range(40):
                        bar = page.locator('.editor-toolbar').bounding_box()
                        toolbar = bar['y'] + bar['height']
                        top = page.locator('#doc-section-dataset').bounding_box()['y']
                        if toolbar <= top <= toolbar + 40: break
                        page.wait_for_timeout(100)
                    assert toolbar <= top <= toolbar + 40, (toolbar, top)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    def api(endpoint, body):
                        reply = context.request.post(origin + '/api/' + endpoint, data=body, headers={'X-Architect-Request':'1'})
                        assert reply.ok, reply.text()
                        return reply.json()

                    metric = str(uuid.uuid4())
                    api('metric-trees/save', {'id':metric, 'title':'Доход', 'goal':'Рост', 'metrics':[], 'revision':0})
                    case = dict.fromkeys(('title','validation','rationale','approach','tradeoffs','assumptions','business_query','query'), 'Прогноз спроса')
                    api('solution-spaces/save', {'id':tree,'source_revision':1,'version':0,'options':[{**case,'evidence':[1]}]})
                    page.locator('#link-task').click()
                    dialog = page.locator('#design-assist-dialog')
                    dialog.get_by_label('Дерево проблем').select_option(tree)
                    dialog.get_by_role('checkbox', name='Прогноз спроса').check()
                    dialog.get_by_label('Иерархия метрик').select_option(metric)
                    dialog.get_by_role('button', name='Применить связи').click()
                    page.locator('#save').click()
                    expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
                    document_id = parse_qs(urlsplit(page.url).query)['id'][0]
                    links = api('design-documents/get', {'id':document_id})['document']['task_links']
                    assert links == {'tree_id':tree, 'metric_tree_id':metric, 'cases':[1], 'case_version':1}
                    page.reload()
                    page.locator('#compose-doc').click()
                    expect(dialog.get_by_label('Дерево проблем')).to_have_value(tree)
                    expect(dialog.get_by_label('Иерархия метрик')).to_have_value(metric)
                    expect(dialog.get_by_role('checkbox', name='Прогноз спроса')).to_be_checked()
                    requests = []
                    def fake_proposal(route):
                        requests.append(route.request.post_data_json)
                        route.fulfill(json={'proposals':{'target':{'text':'Цель задачи', 'source':{}}}})
                    page.route('**/api/design-documents/compose', fake_proposal)
                    dialog.get_by_role('button', name='Подготовить предложение').click()
                    expect(dialog).to_contain_text('Предпросмотр черновика')
                    assert requests[0]['tree_id'] == tree and requests[0]['metric_tree_id'] == metric
                    assert requests[0]['cases'] == [1]
                    dialog.get_by_role('button', name='Применить выбранные разделы').click()
                    page.locator('#save').click()
                    expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
                    # A different last-opened tree must not change a task in another tab.
                    page.evaluate("localStorage.setItem('architect.problem-space.last', crypto.randomUUID())")
                    for step, identity in [('metrics', metric), ('solutions', tree), ('problems', tree), ('document', document_id)]:
                        page.locator(f'#design-flow [data-step={step}]').click()
                        page.wait_for_url('**/design-docs.html**' if step == 'document' else
                            '**/' + {'metrics':'metric-tree','problems':'problem-space','solutions':'solution-space'}[step] + '.html**')
                        assert parse_qs(urlsplit(page.url).query)['id'] == [identity]
                    # The overview opens the same four stages, with the actual saved counts.
                    page.locator('#back-list').click()
                    saved = page.locator('#documents .task-row').filter(
                        has=page.locator(f'a[href*="{document_id}"]'))
                    expect(saved.locator('.task-step')).to_have_count(4)
                    expect(saved.locator('.task-step').nth(0)).to_contain_text('1 из 2 ответов')
                    expect(saved.locator('.task-step').nth(1)).to_contain_text('1 кейс')
                    expect(saved.locator('.task-step').nth(2)).to_contain_text('0 показателей')
                    expect(saved.locator('.task-step').nth(3)).to_contain_text('2 из 6 разделов')
                    expect(page.locator('#design-flow')).to_be_hidden()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    saved.locator('.task-step').nth(1).click()
                    expect(page.locator('#title')).to_have_text('Дерево шагов ' + str(width))

                    # A standalone metric becomes part of a task only after its document is saved.
                    standalone = str(uuid.uuid4())
                    api('metric-trees/save', {'id':standalone, 'title':'Отдельная метрика', 'goal':'Рост', 'metrics':[], 'revision':0})
                    page.goto(origin + '/design-docs.html?project=' + project)
                    orphan = page.locator('#unlinked .task-row').filter(has_text='Отдельная метрика')
                    orphan.get_by_role('link', name='Документ не создан').click()
                    expect(page.locator('#design-flow a[data-step=metrics]')).to_have_attribute(
                        'href', re.compile(standalone))
                    page.reload()
                    page.locator('#save').click()
                    expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
                    new_id = parse_qs(urlsplit(page.url).query)['id'][0]
                    assert api('design-documents/get', {'id':new_id})['document']['task_links'] == {'metric_tree_id':standalone}
                    page.locator('#back-list').click()
                    expect(orphan).to_have_count(0)
                    assert project in page.locator('#back-schema').get_attribute('href')
                    assert not errors, errors
                    for stage in ['Пространство проблем', 'Иерархия метрик']:
                        page.locator('#open-stage summary').click()
                        page.get_by_role('link', name=stage, exact=True).click()
                        page.locator('#tree-ai-open').click()
                        page.locator('#tree-request').fill('Разберём задачу')
                        edit = page.get_by_role('button', name='Методика', exact=True)
                        edit.click()
                        field = page.get_by_label('Инструкция для модели')
                        expect(field).to_be_enabled()
                        default = field.input_value()
                        assert default and 'JSON' not in default
                        instruction = 'Начни с практического примера'
                        field.fill(instruction)
                        page.locator('#save-method').click()
                        expect(edit).to_be_focused()
                        expect(page.locator('#tree-request')).to_have_value('Разберём задачу')
                        edit.click()
                        expect(field).to_have_value(instruction)
                        page.locator('#default-method').click()
                        expect(field).to_have_value(default)
                        page.keyboard.press('Escape')
                        expect(edit).to_be_focused()
                        edit.click()
                        expect(field).to_have_value(instruction)
                        page.locator('#default-method').click()
                        page.locator('#save-method').click()
                        expect(page.locator('#method-dialog')).to_be_hidden()
                        page.goto(origin + '/design-docs.html?project=' + project)
                    assert not errors, errors
                    print(width, 'PASS design flow', flush=True)
                    context.close()
                browser.close()
        finally:
            server.terminate(); server.wait(timeout=5)


if __name__ == '__main__':
    main()

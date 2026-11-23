"""Explicit document saves and deletion with isolated data on desktop and mobile."""
from pathlib import Path
import json
import os
import sys
import tempfile
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_whiteboard import BoardServer
import serve


def main():
    artifacts = Path(tempfile.mkdtemp(prefix='architector-document-tests-'))
    with patch.object(serve.Handler, 'log_message', lambda *args: None), BoardServer() as server, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 900 if width == 1440 else 844})
            page = context.new_page()
            errors = []
            writes = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: writes.append(request.url) if request.url.endswith(('/design-documents/create', '/design-documents/save')) else None)

            def api(action, body=None):
                response = context.request.post(server.origin + '/api/design-documents/' + action, data=body or {}, headers={'X-Architect-Request': '1'})
                assert response.ok, response.text()
                return response.json()

            def documents():
                return api('list')['documents']

            def dialog(accept):
                page.once('dialog', lambda d: d.accept() if accept else d.dismiss())

            page.goto(server.origin + '/design-docs.html?new=1&mode=problems')
            expect(page.locator('#problem-space')).to_be_visible()
            expect(page.locator('#tree-branches li')).to_have_count(0)
            page.locator('#document-mode').click()
            expect(page.locator('#sections textarea')).to_have_count(5)
            expect(page.locator('#save-status')).to_contain_text('ещё не сохранён')
            assert documents() == [] and not writes
            page.locator('#back-list').click()
            expect(page.locator('#documents')).to_contain_text('пока нет')
            page.locator('#create').click()
            page.locator('#title').fill('Несохранённый документ')
            page.locator('#section-problem').fill('Текст только в черновике')
            dialog(False)
            page.locator('#back-list').click()
            expect(page.locator('#editor')).to_be_visible()
            assert documents() == [] and not writes
            page.locator('#add-chat').click()
            expect(page.locator('#editor-error')).to_contain_text('Сначала нажмите «Сохранить»')
            with page.expect_download() as download:
                page.locator('#publish').click()
            exported = json.loads(Path(download.value.path()).read_text())
            assert exported['sections']['problem'] == 'Текст только в черновике'
            assert documents() == [] and not writes
            # A browser reload restores a reserve copy without creating a saved document.
            dialog(True)
            page.reload()
            expect(page.locator('#section-problem')).to_have_value('Текст только в черновике')
            assert documents() == []
            dialog(True)
            page.locator('#back-list').click()
            expect(page.locator('#list')).to_be_visible()
            page.locator('#create').click()
            expect(page.locator('#section-problem')).to_have_value('')
            title = 'Длинное русское название дизайн-документа для проверки сохранения ' + str(width)
            page.locator('#title').fill(title)
            page.locator('#section-problem').fill('Сохранённая проблема')
            page.locator('#problem-mode').click()
            page.locator('#tree-ai-open').click()
            page.locator('#tree-request').fill('Разобрать задачу')
            result = {'questions': [{'question': 'Кто принимает решение?', 'answer': '', 'children': []}]}
            page.route('**/api/design-documents/suggest-questions', lambda route: route.fulfill(json=result))
            page.locator('#tree-generate').click()
            expect(page.locator('#tree-preview')).to_contain_text('Кто принимает решение?')
            expect(page.locator('#tree-branches li')).to_have_count(0)
            page.locator('#tree-apply').click()
            page.get_by_label('Ответ', exact=True).fill('Руководитель отдела')
            expect(page.locator('#tree-origin')).to_have_text('Сохранённая проблема')
            page.get_by_role('button', name='Добавить уточнение', exact=True).click()
            page.get_by_label('Вопрос', exact=True).fill('Как проверить результат?')
            parent, child = page.locator('.branch-row').all()
            assert child.bounding_box()['x'] >= parent.bounding_box()['x'] + parent.bounding_box()['width']
            page.locator('#tree-fit').click()
            assert page.locator('#tree-viewport').evaluate('e => e.scrollWidth <= e.clientWidth + 1')
            parent.locator('[aria-expanded]').click()
            expect(page.locator('.branch-row')).to_have_count(1)
            parent.locator('[aria-expanded]').click()
            expect(page.locator('.branch-row')).to_have_count(2)
            page.locator('#document-mode').click()
            # Failed first save preserves the editor and does not leave an empty row.
            page.route('**/api/design-documents/create', lambda route: route.fulfill(status=503, json={'error': 'Сохранение недоступно'}))
            page.locator('#save').click()
            expect(page.locator('#editor-error')).to_have_text('Сохранение недоступно')
            expect(page.locator('#save')).to_be_enabled()
            assert documents() == []
            page.unroute('**/api/design-documents/create')
            # Rapid clicks cannot create duplicate documents.
            held = []
            page.route('**/api/design-documents/create', lambda route: held.append(route))
            page.locator('#save').evaluate('e => { e.click(); e.click(); }')
            expect(page.locator('#save')).to_be_disabled()
            page.wait_for_timeout(100)
            assert len(held) == 1
            held.pop().continue_()
            expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
            page.unroute('**/api/design-documents/create')
            saved = documents()
            assert len(saved) == 1 and saved[0]['title'] == title
            identity = saved[0]['id']
            assert api('get', {'id': identity})['document']['sections']['problem'] == 'Сохранённая проблема'
            assert api('get', {'id': identity})['document']['problem_tree'][0]['answer'] == 'Руководитель отдела'
            page.reload()
            page.locator('#problem-mode').click()
            page.get_by_label('Ответ', exact=True).fill('Обновлённый ответ')
            page.locator('#save').click()
            expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
            assert api('get', {'id': identity})['document']['problem_tree'][0]['answer'] == 'Обновлённый ответ'
            page.locator('#document-mode').click()
            page.screenshot(path=str(artifacts / f'editor-{width}.png'))
            page.locator('#section-problem').fill('Несохранённая правка')
            # A failed transition must keep dirty state and allow an explicit save.
            page.route('**/api/design-documents/list', lambda route: route.fulfill(status=503, json={'error': 'Список недоступен'}))
            dialog(True)
            page.locator('#back-list').click()
            expect(page.locator('#editor-error')).to_have_text('Список недоступен')
            expect(page.locator('#save')).to_be_enabled()
            page.unroute('**/api/design-documents/list')
            page.locator('#save').click()
            expect(page.locator('#save-status')).to_have_text('Все изменения сохранены')
            assert api('get', {'id': identity})['document']['sections']['problem'] == 'Несохранённая правка'
            page.locator('#section-problem').fill('Правка для отмены')
            dialog(True)
            page.locator('#back-list').click()
            expect(page.locator('.document-row')).to_have_count(1)
            page.locator('.document-row').click()
            expect(page.locator('#section-problem')).to_have_value('Несохранённая правка')
            page.locator('#back-list').click()
            page.screenshot(path=str(artifacts / f'list-{width}.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            remove = page.get_by_role('button', name='Удалить документ «' + title + '»', exact=True)
            dialog(False)
            remove.click()
            assert len(documents()) == 1
            page.route('**/api/design-documents/delete', lambda route: route.fulfill(status=503, json={'error': 'Удаление недоступно'}))
            dialog(True)
            remove.click()
            expect(page.locator('#message')).to_have_text('Удаление недоступно')
            expect(remove).to_be_enabled()
            assert len(documents()) == 1
            page.unroute('**/api/design-documents/delete')
            remove.focus()
            dialog(True)
            page.keyboard.press('Enter')
            expect(page.locator('#message')).to_have_text('Документ удалён.')
            expect(page.locator('#create')).to_be_focused()
            page.reload()
            expect(page.locator('#documents')).to_contain_text('пока нет')
            assert documents() == [] and not errors, errors
            context.close()
        browser.close()
    print('PASS: explicit saves, discard/cancel, draft recovery, export, failures, duplicate clicks, deletion, keyboard, 1440/390px')
    print('Screenshots:', artifacts)


if __name__ == '__main__':
    main()

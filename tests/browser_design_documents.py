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
            context = browser.new_context(viewport={'width': width, 'height': 900 if width == 1440 else 844}, has_touch=width == 390)
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

            page.goto(server.origin + '/design-docs.html?new=1')
            expect(page.locator('#sections .doc-section > textarea')).to_have_count(6)
            expect(page.locator('#save-status')).to_contain_text('ещё не сохранён')
            expect(page.locator('#sections .doc-section > label').nth(2)).to_have_text('3. Метрики')
            dataset = page.locator('#section-dataset')
            labels = page.locator('#sections .doc-section > label')
            expect(labels.nth(3)).to_have_text('4. Датасет')
            expect(labels.nth(4)).to_have_text('5. Валидация')
            expect(labels.nth(5)).to_have_text('6. Решение, альтернативы и обучение')
            validation = page.get_by_role('textbox', name='5. Валидация')
            add_outline = page.locator('#validation-insert')
            add_outline.click()
            expect(validation.locator('h2')).to_have_text([
                'Сценарий применения', 'Разбиение и защита от утечек',
                'Выбор модели и финальная проверка', 'Обновление выборок'])
            expect(add_outline).to_be_hidden()
            validation.press('ControlOrMeta+a')
            validation.press('Backspace')
            expect(add_outline).to_be_visible()
            problem_editor = page.get_by_role('textbox', name='1. Проблема', exact=False)
            problem_editor.press_sequentially('## Заголовок')
            expect(problem_editor.locator('h2')).to_have_text('Заголовок')
            problem_editor.press('Enter')
            problem_editor.press_sequentially('- Пункт')
            expect(problem_editor.locator('ul li')).to_have_text('Пункт')
            problem_editor.press('ControlOrMeta+a')
            problem_editor.press('Backspace')
            insert = page.locator('#dataset-insert')
            insert.click()
            assert dataset.input_value().replace('## ', '').split() == ['ETL', 'Фильтрация', 'Генерация', 'признаков', 'Разметка']
            expect(insert).to_be_hidden()
            page.locator('#section-dataset + .visual-editor .toastui-editor-ww-container [contenteditable=true]').press('ControlOrMeta+a')
            page.keyboard.press('Backspace')
            expect(insert).to_be_visible()
            assert documents() == [] and not writes
            page.locator('#back-list').click()
            expect(page.locator('#documents')).to_contain_text('пока нет')
            page.locator('#create').click()
            page.locator('#task-name').fill('Тестовая задача')
            page.locator('#submit-task').click()
            expect(page.locator('#design-flow [aria-current=step]')).to_have_text('1Проблемы')
            page.locator('#design-flow a[data-step=document]').click()
            page.locator('#title').fill('Несохранённый документ')
            page.locator('#section-problem + .visual-editor .toastui-editor-ww-container [contenteditable=true]').fill('Текст только в черновике')
            # Saving a method applies to the action across documents and never saves the document.
            edit_method = page.get_by_role('button', name='Методика', exact=True)
            edit_method.click()
            field = page.get_by_label('Инструкция для модели')
            kind = page.get_by_label('Действие', exact=True)
            expect(field).to_be_enabled()
            default_draft = field.input_value()
            field.fill('Сборка для теста')
            kind.select_option('review')
            field.fill('Ревью для теста')
            kind.select_option('compose')
            expect(field).to_have_value('Сборка для теста')
            field.press('ControlOrMeta+s')
            expect(edit_method).to_be_focused()
            assert not writes
            edit_method.click()
            page.locator('#default-method').click()
            kind.select_option('review')
            expect(field).to_have_value('Ревью для теста')
            page.keyboard.press('Escape')
            edit_method.click()
            expect(field).to_have_value('Сборка для теста')
            page.locator('#default-method').click()
            page.locator('#save-method').click()
            expect(edit_method).to_be_focused()
            methods = api('method')
            assert methods['compose']['text'] == default_draft and methods['review']['text'] == 'Ревью для теста'
            api('save-method', {'changes': {'review': {'text': None, 'previous': 'Ревью для теста'}}})
            expect(page.locator('#section-problem')).to_have_value('Текст только в черновике')
            target_editor = page.get_by_role('textbox', name='2. Цели')
            target_section = target_editor.locator('xpath=ancestor::section[1]')
            target_section.get_by_role('button', name='Вставить ссылку').click()
            link_dialog = target_section.locator('.toastui-editor-popup:visible')
            link_dialog.locator('input').nth(0).fill('https://example.org')
            link_dialog.locator('input').nth(1).fill('Источник')
            link_dialog.get_by_role('button', name='Хорошо').click()
            target_section.get_by_role('button', name='Вставить таблицу').click()
            grid = target_section.locator('.toastui-editor-table-selection:visible')
            if width == 390:
                grid.tap(position={'x': 30, 'y': 30})
            else:
                grid.click(position={'x': 30, 'y': 30})
            expect(target_editor.locator('th')).to_have_count(2)
            expect(target_editor.locator('td')).to_have_count(2)
            target_editor.locator('td').first.click()
            page.keyboard.insert_text('Значение в таблице')
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
            expect(target_editor.locator('td').first).to_have_text('Значение в таблице')
            expect(target_editor.locator('a[href="https://example.org"]')).to_have_text('Источник')
            assert documents() == []
            dialog(True)
            page.locator('#back-list').click()
            expect(page.locator('#list')).to_be_visible()
            page.get_by_role('button', name='Удалить задачу «Тестовая задача»').click()
            expect(page.locator('#documents')).to_contain_text('пока нет')
            page.locator('#create').click()
            page.locator('#task-name').fill('Тестовая задача')
            page.locator('#submit-task').click()
            expect(page.locator('#design-flow [aria-current=step]')).to_have_text('1Проблемы')
            page.locator('#design-flow a[data-step=document]').click()
            expect(page.locator('#section-problem')).to_have_value('')
            title = 'Длинное русское название дизайн-документа для проверки сохранения ' + str(width)
            page.locator('#title').fill(title)
            page.locator('#section-problem + .visual-editor .toastui-editor-ww-container [contenteditable=true]').fill('Сохранённая проблема')
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
            page.screenshot(path=str(artifacts / f'editor-{width}.png'))
            page.locator('#section-problem + .visual-editor .toastui-editor-ww-container [contenteditable=true]').fill('Несохранённая правка')
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
            page.locator('#section-problem + .visual-editor .toastui-editor-ww-container [contenteditable=true]').fill('Правка для отмены')
            dialog(True)
            page.locator('#back-list').click()
            expect(page.locator('.document-row')).to_have_count(1)
            page.locator('.document-row').click()
            expect(page.locator('#section-problem')).to_have_value('Несохранённая правка')
            page.locator('#back-list').click()
            page.screenshot(path=str(artifacts / f'list-{width}.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            remove = page.get_by_role('button', name='Удалить документ «' + title + '»', exact=True)
            page.route('**/api/design-documents/delete', lambda route: route.fulfill(status=503, json={'error': 'Удаление недоступно'}))
            remove.click()
            expect(page.locator('#message')).to_have_text('Удаление недоступно')
            expect(remove).to_be_enabled()
            assert len(documents()) == 1
            page.unroute('**/api/design-documents/delete')
            remove.focus()
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

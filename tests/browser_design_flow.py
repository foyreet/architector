"""Steps between problem, solution, metric trees and the design document with isolated data."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

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
                    page.goto(origin + '/problem-space.html?new=1&project=' + project)
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

                    # The solutions step saves the tree first and keeps the project.
                    page.locator('#solutions').click()
                    page.wait_for_url('**/solution-space.html**')
                    assert project in page.url
                    expect(page.locator('#title')).to_have_text('Дерево шагов ' + str(width))
                    expect(page.locator('#save')).to_be_hidden()
                    expect(page.locator('#design-flow [aria-current=step]')).to_have_text('2Решения')
                    assert project in page.locator('#design-flow a[data-step=document]').get_attribute('href')
                    tree = page.url.split('id=')[1].split('&')[0]
                    assert tree in page.locator('#design-flow a[data-step=problems]').get_attribute('href')

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
                    page.once('dialog', lambda d: d.accept())
                    page.get_by_role('button', name='Удалить метрику').click()
                    expect(page.locator('.branch-row')).to_have_count(0)

                    # Design document: the outline follows filled sections.
                    page.goto(origin + '/design-docs.html?new=1')
                    expect(page.locator('#doc-outline a')).to_have_count(5)
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
                    print(width, 'PASS design flow', flush=True)
                    context.close()
                browser.close()
        finally:
            server.terminate(); server.wait(timeout=5)


if __name__ == '__main__':
    main()

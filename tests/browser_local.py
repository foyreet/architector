from pathlib import Path
import os,sys,tempfile,subprocess,time,urllib.request,socket
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[1]
artifacts=Path(tempfile.mkdtemp(prefix='architector-browser-'))
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close();origin=f'http://127.0.0.1:{port}'
with tempfile.TemporaryDirectory(prefix='local-ux-data-') as data:
 process=subprocess.Popen([sys.executable,str(root/'serve.py'),'--port',str(port)],cwd=root,env={**os.environ,'ARCHITECT_DATA_DIR':data},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(80):
   try:urllib.request.urlopen(origin+'/api/blocks/contracts',timeout=1);break
   except OSError:time.sleep(.1)
  with sync_playwright() as pw:
   b=pw.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
   for width,height in ((1440,900),(1024,768)):
    c=b.new_context(viewport={'width':width,'height':height});p=c.new_page();errs=[];external=[];p.on('pageerror',lambda e:errs.append(str(e)));p.on('request',lambda r:external.append(r.url) if not r.url.startswith(origin) else None)
    p.goto(origin+'/architecture.html');expect(p.locator('#learning')).to_be_enabled();p.wait_for_timeout(500)
    p.locator('#codex-chat-open').click();p.wait_for_timeout(500)
    if not p.locator('#ai-setup').is_visible():p.locator('#codex-connect').click()
    expect(p.locator('#ai-setup')).to_be_visible();expect(p.locator('#ai-test')).to_have_text('Сохранить и проверить API');assert not p.get_by_text('Личный аккаунт Codex · действуют лимиты вашего тарифа').count();p.screenshot(path=f'{artifacts}/local-review-ai-{width}.png')
    p.locator('#ai-base-url').fill('http://127.0.0.1:1/'+'long-endpoint-name-'*15+'/v1');p.locator('#ai-model-name').fill('local-review-model');p.locator('#ai-test').click();expect(p.locator('#ai-setup-status')).not_to_have_text('Проверяем API…');p.wait_for_timeout(1000);p.screenshot(path=f'{artifacts}/local-review-ai-error-{width}.png');print(width,'API status',p.locator('#ai-setup-status').inner_text(),flush=True)
    assert p.locator('#ai-base-url').input_value().endswith('/v1');assert not p.locator('#ai-api-key').input_value();assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
    p.get_by_label('Закрыть настройку AI').click();p.locator('#learning').click();expect(p.locator('#learning-dialog')).to_be_visible();p.screenshot(path=f'{artifacts}/local-review-learning-{width}.png');print(width,'learning topics',p.locator('#learn-nav').inner_text(),flush=True);p.keyboard.press('Escape')
    p.locator('#diagram-name').fill('Локальная схема UX '+str(width));p.locator('#save').click();p.wait_for_timeout(400);p.reload();expect(p.locator('#diagram-name')).to_have_value('Локальная схема UX '+str(width))
    p.locator('#design-document-create').click();p.wait_for_url('**/design-docs.html**');expect(p.locator('#sections textarea')).to_have_count(5);p.locator('#title').fill('Локальный дизайн UX '+str(width));p.locator('#section-problem').fill('Проверка локального сохранения');p.locator('#save').click();expect(p.locator('#save')).to_be_disabled();p.screenshot(path=f'{artifacts}/local-review-document-{width}.png');print(width,'document buttons',p.locator('button:visible').all_text_contents(),flush=True)
    with p.expect_download() as download:p.locator('#publish').click()
    export=download.value;export.save_as(f'{artifacts}/local-review-document-{width}.json');p.locator('#back-list').click();p.locator('input[type=file]').set_input_files(f'{artifacts}/local-review-document-{width}.json');expect(p.locator('#section-problem')).to_have_value('Проверка локального сохранения')
    assert not errs,errs;assert not external,external;print(width,'PASS save/reload, document, no pageerrors/no external requests',flush=True);c.close()
   b.close()
 finally:process.terminate();process.wait(timeout=5)

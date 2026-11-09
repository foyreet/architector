"""Guided Codex setup with missing/available CLI, no real login or paid model."""
from pathlib import Path
import os,sys,tempfile,subprocess,time,urllib.request,socket,json
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[1]
artifacts=Path(tempfile.mkdtemp(prefix='ai-setup-review-'))
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close();origin=f'http://127.0.0.1:{port}'
with tempfile.TemporaryDirectory(prefix='ai-setup-data-') as data:
 process=subprocess.Popen([sys.executable,str(root/'serve.py'),'--port',str(port)],cwd=root,env={**os.environ,'ARCHITECT_DATA_DIR':data,'ARCHITECT_CODEX_BIN':'missing-codex-for-test'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(80):
   try:urllib.request.urlopen(origin+'/api/blocks/contracts',timeout=1);break
   except OSError:time.sleep(.1)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
   for width,height in ((1440,900),(1024,768),(390,844)):
    context=browser.new_context(**(pw.devices['iPhone 13'] if width<600 else {'viewport':{'width':width,'height':height}}),permissions=['clipboard-read','clipboard-write'])
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(origin);expect(page.locator('#learning')).to_be_enabled()
    page.request.post(origin+'/api/codex/configure',data={'provider':'compatible','base_url':'http://localhost:11434/v1','model':'local'},headers={'X-Architect-Request':'1'})
    if width<600:page.locator('#mobile-menu').click()
    page.locator('#codex-chat-open').click();page.locator('#codex-connect').click()
    page.locator('#ai-base-url').fill('http://localhost:11435/v1');page.locator('#ai-model-name').fill('unsaved-model')
    page.locator('#ai-provider').select_option('codex');expect(page.locator('#ai-codex-install')).to_be_visible();expect(page.locator('#ai-save')).to_be_disabled()
    page.locator('#ai-codex-recheck').click();expect(page.locator('#ai-codex-recheck')).to_be_enabled();expect(page.locator('#ai-save')).to_be_disabled()
    page.locator('#ai-codex-copy').click();expect(page.locator('#ai-setup-status')).to_contain_text('Команда скопирована')
    page.screenshot(path=str(artifacts/f'missing-{width}.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    response=page.request.post(origin+'/api/codex/config',data={},headers={'X-Architect-Request':'1'}).json()
    assert response['provider']=='compatible'
    page.locator('#ai-provider').select_option('compatible');expect(page.locator('#ai-base-url')).to_have_value('http://localhost:11435/v1');expect(page.locator('#ai-model-name')).to_have_value('unsaved-model')
    page.locator('#ai-provider').select_option('codex')
    page.route('**/api/codex/config',lambda r:r.fulfill(json=response));page.locator('#ai-codex-recheck').click();expect(page.locator('#ai-save')).to_be_disabled()
    response['codex']['available']=True;page.locator('#ai-codex-recheck').click();expect(page.locator('#ai-save')).to_be_enabled();expect(page.locator('#ai-codex-install')).not_to_be_visible()
    page.screenshot(path=str(artifacts/f'ready-{width}.png'))
    page.route('**/api/codex/configure',lambda r:r.fulfill(json={'provider':'codex'}))
    page.route('**/api/codex/login',lambda r:r.fulfill(status=503,json={'error':'Тест: вход временно недоступен'}))
    page.locator('#ai-save').click();expect(page.locator('#ai-setup')).to_be_visible();expect(page.locator('#ai-setup-status')).to_contain_text('вход временно недоступен')
    page.unroute('**/api/codex/login');page.route('**/api/codex/login',lambda r:r.fulfill(json={'connected':False,'login':{'url':'https://auth.openai.com/codex/device','code':'TEST','expires_at':time.time()+60}}))
    page.locator('#ai-save').click();expect(page.locator('#ai-setup')).not_to_be_visible()
    assert not errors,errors
    context.close();print('PASS guided setup',width)
   browser.close()
 finally:process.terminate();process.wait(timeout=5)
print('Screenshots:',artifacts)

"""Create an independent blank schema without losing the previous project."""
from pathlib import Path
import os,sys,tempfile,threading,json
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import serve


def main():
    with tempfile.TemporaryDirectory() as folder,patch('project_store.ROOT',Path(folder)),patch.object(serve.Handler,'log_message',lambda *args:None):
        server=serve.ThreadingHTTPServer(('127.0.0.1',0),serve.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
                for width in (1440,390):
                    options={'viewport':{'width':width,'height':1000 if width==1440 else 844}}
                    if width==390:options.update(is_mobile=True,has_touch=True,user_agent=p.devices['iPhone 13']['user_agent'])
                    page=browser.new_page(**options);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin);expect(page.locator('#learning')).to_be_enabled()
                    expect(page.locator('#welcome')).not_to_be_visible()
                    if page.locator('#phone-intro').is_visible():page.locator('#phone-intro-skip').click()
                    def api(path,body=None):
                        response=page.request.post(origin+path,data=body or {},headers={'X-Architect-Request':'1'});assert response.ok,response.text();return response.json()
                    def identity():return page.evaluate("new URL(location.href).searchParams.get('project')")
                    def create():
                        if width==390:page.locator('#mobile-menu').click()
                        button=page.locator('#new-diagram');expect(button).to_be_visible()
                        assert button.evaluate("e=>!!(e.compareDocumentPosition(document.getElementById('codex-chat-open')) & Node.DOCUMENT_POSITION_FOLLOWING)")
                        if width==1440:button.focus();page.keyboard.press('Enter')
                        else:button.tap()
                    page.locator('#library-toggle').click();page.locator('#block-search').fill('Python');page.locator('#add-python-block').click()
                    page.locator('#diagram-name').fill('Работа до создания '+str(width));page.locator('#diagram-name').press('Tab')
                    # First-save failure preserves the unsaved graph.
                    page.route('**/api/projects/create',lambda r:r.fulfill(status=503,json={'error':'Сеть недоступна'}))
                    create();expect(page.locator('#toast')).to_contain_text('Не удалось сохранить проект')
                    expect(page.locator('.node')).to_have_count(1);assert identity() is None
                    page.unroute('**/api/projects/create')
                    create();expect(page.locator('.node')).to_have_count(0);expect(page.locator('#diagram-name')).to_have_value('Новая схема')
                    expect(page.locator('#welcome')).not_to_be_visible()
                    new_id=identity();assert new_id
                    projects=api('/api/projects/list')['projects']
                    previous=next(i for i in projects if i['name']=='Работа до создания '+str(width))
                    old=api('/api/projects/get',{'project_id':previous['id']})
                    assert len(old['diagram']['nodes'])==1 and previous['id']!=new_id
                    new=api('/api/projects/get',{'project_id':new_id})
                    assert new['diagram']['nodes']==[] and new['diagram']['types']==[] and new['diagram']['definitions']==[]
                    expect(page.locator('#project-menu')).not_to_be_visible()
                    if width==390:expect(page.locator('#mobile-nav-dialog')).not_to_be_visible();expect(page.locator('#viewport')).to_be_focused()
                    else:expect(page.locator('#diagram-name')).to_be_focused()
                    page.locator('#diagram-name').fill('Независимая схема '+str(width));page.locator('#save').click();expect(page.locator('#save')).to_be_enabled()
                    assert identity()==new_id
                    assert api('/api/projects/get',{'project_id':previous['id']})['diagram']==old['diagram']
                    # Save failure in an existing project also prevents a switch.
                    page.route('**/api/projects/save',lambda r:r.fulfill(status=503,json={'error':'Сохранение недоступно'}))
                    page.locator('#diagram-name').fill('Правки сохранятся '+str(width));create()
                    expect(page.locator('#toast')).to_contain_text('Не удалось создать схему');assert identity()==new_id
                    expect(page.locator('#diagram-name')).to_have_value('Правки сохранятся '+str(width))
                    page.unroute('**/api/projects/save');page.locator('#save').click();expect(page.locator('#save')).to_be_enabled()
                    # Repeated clicks while creation is pending send one request.
                    held=[];page.route('**/api/projects/create',lambda r:held.append(r))
                    if width==390:page.locator('#mobile-menu').click()
                    page.locator('#new-diagram').evaluate('e=>{e.click();e.click()}')
                    expect(page.locator('#new-diagram')).to_be_disabled();page.wait_for_timeout(150);assert len(held)==1
                    held.pop().continue_();page.unroute('**/api/projects/create')
                    expect(page.locator('#diagram-name')).to_have_value('Новая схема');expect(page.locator('#new-diagram')).to_be_enabled();assert identity()!=new_id
                    page.reload();expect(page.locator('#learning')).to_be_enabled()
                    expect(page.locator('#welcome')).not_to_be_visible()
                    page.locator('#library-toggle').click();page.locator('#block-search').fill('Python');page.locator('#add-python-block').click()
                    expect(page.locator('.node')).to_have_count(1)
                    page.locator('#viewport').focus();page.keyboard.press('Delete')
                    expect(page.locator('.node')).to_have_count(0);expect(page.locator('#welcome')).not_to_be_visible()
                    page.screenshot(path=f'/tmp/blank-canvas-{width}.png')
                    page.locator('#viewport').focus();page.wait_for_timeout(100)
                    if width==390:page.locator('#mobile-menu').click()
                    page.screenshot(path=f'/tmp/create-schema-preview-{width}.png')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    assert not errors,errors;page.close()
                browser.close()
            print('PASS: sidebar placement, blank independent project, previous work saved, failure recovery, duplicate-click protection,1440/mobile390')
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()


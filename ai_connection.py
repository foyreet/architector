"""User-selected AI endpoints. No default provider, shared credentials or automatic requests."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
import block_contracts as bc
import project_store as ps

def config(root):
    try: return ps.ProjectStore(root).read('workspace/ai/connection.json')
    except bc.ContractError as e:
        if e.status == 404: return {'provider': 'none'}
        raise

def public(value):
    return {k: value.get(k, '') for k in ('provider', 'base_url', 'model')} | {'has_key': bool(value.get('api_key'))}

def save(root, body):
    provider = body.get('provider')
    if provider not in ('none', 'codex', 'compatible'): raise bc.ContractError('Выберите способ подключения AI.')
    value = {'provider': provider}
    if provider == 'compatible':
        base, model, key = body.get('base_url', ''), body.get('model', ''), body.get('api_key', '')
        if not all(isinstance(v, str) for v in (base, model, key)): raise bc.ContractError('Некорректные настройки модели.')
        base, model = base.strip().rstrip('/'), model.strip()
        u = urlsplit(base)
        if (not u.hostname or u.username or u.password or u.query or u.fragment or
            any(c.isspace() for c in base) or u.scheme not in ('http', 'https') or
            u.scheme == 'http' and u.hostname not in ('localhost', '127.0.0.1', '::1')):
            raise bc.ContractError('Укажите HTTPS-адрес API или HTTP-адрес локальной модели. Например: http://localhost:11434/v1')
        if not model or '\n' in key or '\r' in key: raise bc.ContractError('Проверьте название модели и ключ.')
        old = config(root)
        if body.get('keep_key') is True and old.get('base_url') == base and not key: key=old.get('api_key','')
        value.update(base_url=base, model=model, api_key=key)
    store=ps.ProjectStore(root)
    store.write('workspace/ai/connection.json',value)
    os.chmod(store.path('workspace/ai/connection.json'),0o600)
    return public(value)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

class Compatible:
    def __init__(self, value): self.value=value
    def status(self):
        return {'available': True, 'connected': True, 'provider': 'compatible', 'label': self.value['model'], 'endpoint': self.value['base_url'], 'login': None}
    def models(self):
        return [{'id': self.value['model'], 'name': self.value['model'], 'default': True, 'efforts': [], 'default_effort': None}]
    def http(self, route, payload=None, timeout=90):
        headers={'Accept':'application/json'}
        if self.value.get('api_key'): headers['Authorization']='Bearer '+self.value['api_key']
        raw=None
        if payload is not None:
            raw=json.dumps(payload,ensure_ascii=False).encode(); headers['Content-Type']='application/json'
        try:
            with build_opener(NoRedirect()).open(Request(self.value['base_url']+'/'+route,data=raw,headers=headers),timeout=timeout) as r:
                data=r.read()
                result=json.loads(data)
                if not isinstance(result,dict): raise ValueError()
                return result
        except HTTPError as e:
            raise bc.ContractError(f'API модели вернул HTTP {e.code}. Проверьте адрес, модель, ключ и поддержку вызова инструментов. Автоматического повтора нет.',502) from None
        except (URLError,TimeoutError,OSError):
            raise bc.ContractError('Не удалось связаться с API модели. Проверьте адрес и запущена ли локальная модель.',502) from None
        except (ValueError,UnicodeError): raise bc.ContractError('API вернул некорректный JSON.',502) from None
    def answer(self,prompt,draft=None,model=None,effort=None,documents=None):
        import codex_edits, codex_documents
        from codex_chat import INSTRUCTIONS
        definitions=(codex_edits.TOOLS if draft else [])+(codex_documents.TOOLS if documents else [])
        allowed={t['name'] for t in definitions}
        tool_defs=[{'type':'function','function':{'name':t['name'],'description':t['description'],'parameters':t['inputSchema']}} for t in definitions]
        messages=[{'role':'system','content':INSTRUCTIONS},{'role':'user','content':prompt}]
        while True:
            payload={'model':self.value['model'],'messages':messages,'stream':False}
            if tool_defs: payload['tools']=tool_defs
            result=self.http('chat/completions',payload,timeout=None)
            try:
                choice=result['choices'][0]; reply=choice['message']; calls=reply.get('tool_calls') or []
                if not isinstance(reply,dict) or not isinstance(calls,list): raise ValueError()
                text=reply.get('content') or ''
                if not isinstance(text,str): raise ValueError()
                if not calls:
                    if choice.get('finish_reason')=='length': raise bc.ContractError('Модель достигла лимита ответа. Сократите запрос; автоматического повтора нет.',502)
                    if text.strip(): return text
                    raise ValueError()
                messages.append({'role':'assistant','content':text or None,'tool_calls':calls})
                for call in calls:
                    name=call['function']['name']; identity=call['id']
                    if not isinstance(identity,str) or not isinstance(name,str): raise ValueError()
                    try:
                        if name not in allowed: raise bc.ContractError('Инструмент недоступен.')
                        args=json.loads(call['function']['arguments'])
                        handler=documents if name in codex_documents.INDEX else draft
                        output=handler.call(name,args)
                    except (bc.ContractError,ValueError,TypeError,KeyError) as e:
                        output={'error':str(e) if isinstance(e,bc.ContractError) else 'Некорректные аргументы инструмента.'}
                    messages.append({'role':'tool','tool_call_id':identity,'content':json.dumps(output,ensure_ascii=False)})
            except (KeyError,IndexError,TypeError,ValueError): raise bc.ContractError('API не вернул совместимый ответ модели.',502) from None

"""Inspect connected data without running providers, training or user code."""
from copy import deepcopy
from collections import Counter
import math

import block_contracts as bc
import local_operations
import ml_operations as ml
import subgraphs


class Resolver:
    def __init__(self, body, kaggle, history=None):
        self.graph, self.registry = subgraphs.normalize(body.get('diagram'))
        self.nodes = {n['id']: n for n in self.graph['nodes']}
        self.kaggle, self.history, self.run_id = kaggle, history, body.get('run_id')
        self.cache, self.visiting = {}, set()
        self.sources = []

    def inputs(self, node_id):
        if node_id not in self.nodes: ml.error('Блок не найден.')
        if node_id in self.visiting: ml.error('Обнаружен цикл в цепочке просмотра.')
        self.visiting.add(node_id)
        try:
            block = deepcopy(self.nodes[node_id]['block'])
            for edge in self.graph['edges']:
                if edge['kind'] == 'data' and edge['to'] == node_id:
                    values = self.outputs(edge['from'])
                    if edge['fromPort'] not in values: ml.error('Выход источника ещё не получен.')
                    block['inputs'][edge['toPort']] = values[edge['fromPort']]
            return bc.normalize_block(block, required=True)
        finally: self.visiting.remove(node_id)

    def same_source(self, node_id, saved, visiting=None):
        visiting = set() if visiting is None else visiting
        if node_id in visiting: return False
        visiting.add(node_id)
        current = self.nodes.get(node_id)
        old = next((n for n in saved['nodes'] if n['id'] == node_id), None)
        if not current or not old or current['block'] != old['block']: return False
        def links(graph):
            return sorted((e['from'],e['fromPort'],e['toPort']) for e in graph['edges'] if e['kind']=='data' and e['to']==node_id)
        if links(self.graph) != links(saved): return False
        return all(self.same_source(source, saved, visiting.copy()) for source, _, _ in links(self.graph))

    def outputs(self, node_id):
        if node_id in self.cache: return self.cache[node_id]
        node = self.nodes[node_id]; kind = node['block']['kind']
        if kind in ('kaggle','csv','ml_prepare'):
            block = self.inputs(node_id)
            if kind == 'kaggle':
                info = self.kaggle.request({'dataset':block['inputs']['source']}, 'files')
                if info.get('status') != 'ready': ml.error('Сначала скачайте датасет в блоке Kaggle.')
                outputs = {'dataset':info['artifact']}
            elif kind == 'csv':
                result = local_operations.read_csv(block,self.kaggle); outputs=result['outputs']
                self.sources.append({'node':node['name'],**result['details']})
            else: outputs = ml.execute(block,self.kaggle.ROOT)['outputs']
        elif self.history and self.run_id:
            record = self.history('run', {'run_id':self.run_id})
            saved = record.get('source_diagram') or record['diagram']
            # Compare this source and all ancestors, not unrelated downstream edits.
            if not self.same_source(node_id,saved): ml.error('Источник изменён после запуска. Выполните схему заново, чтобы увидеть актуальные данные.')
            def leaf(current, port, path=()):
                if current['block']['kind'] in bc.CONTRACTS:
                    return ('n_' + subgraphs.digest([*path, current['id']])[:32] if path else current['id'], port)
                definition = self.registry.definitions[current['block']['kind']]
                target = next(p['target'] for p in definition['outputs'] if p['id'] == port)
                inner = next(n for n in definition['graph']['nodes'] if n['id'] == target['node'])
                return leaf(inner, target['port'], (*path, current['id']))
            outputs = {}; steps = {}
            for port in self.registry.get(kind)['outputs']:
                leaf_id, leaf_port = leaf(node, port['id'])
                if leaf_id not in steps: steps[leaf_id] = self.history('step', {'run_id':self.run_id,'node_id':leaf_id})
                step = steps[leaf_id]
                if step.get('status') != 'ready': ml.error('Источник не завершён. Выполните схему до просмотра его результата.')
                outputs[port['id']] = step['outputs'][leaf_port]
            self.sources.append({'node':node['name'],'run_id':self.run_id,'finished_at':record.get('finished_at')})
        else:
            ml.error('Для этого источника сначала выполните пайплайн и выберите запуск в истории. Просмотр не запускает код или обучение автоматически.')
        self.cache[node_id] = outputs
        return outputs


def profile(rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    stats = []
    for key in columns:
        values = [row.get(key) for row in rows]
        present = [v for v in values if v is not None and (not isinstance(v,str) or v.strip())]
        numbers = []
        for value in present:
            try:
                number=float(value)
                if math.isfinite(number): numbers.append(number)
            except (ValueError,TypeError,OverflowError): pass
        counts = Counter(str(v) for v in present)
        stats.append({'name':key,'type':'number' if present and len(numbers)==len(present) else 'text',
                      'missing':len(values)-len(present),'numeric':len(numbers),'unique':len(counts),
                      'minimum':min(numbers) if numbers else None,'maximum':max(numbers) if numbers else None,
                      'common':[{'value':v[:200],'count':n} for v,n in counts.most_common(5)]})
    return {'rows':len(rows),'columns':stats,'duplicates':len(rows)-len({ml.encode(row) for row in rows})}


def preview(body,kaggle,history=None):
    page=body.get('page',0)
    if type(page) is not int or page<0: ml.error('Некорректная страница.')
    resolver=Resolver(body,kaggle,history); node=resolver.nodes.get(body.get('node_id'))
    if not node: ml.error('Выберите блок данных.')
    kind=node['block']['kind']
    if kind=='csv': rows=resolver.outputs(node['id'])['rows']; block=None
    else:
        block=resolver.inputs(node['id']);rows=block['inputs'].get('rows')
        if rows is None: ml.error('У блока нет входа со строками таблицы.')
    bc.validate_value(rows,{'type':'rows'})
    result={'profile':profile(rows),'rows':rows[page*50:(page+1)*50],'page':page,'page_size':50,'sources':resolver.sources}
    if kind=='ml_prepare':
        try:
            prepared,details=ml.prepare(rows,block['settings'])
            after=[dict(zip(prepared['features'],x),**{prepared['target']:y}) for x,y in zip(prepared['X'],prepared['y'])]
            result['prepared']={'profile':profile(after),'rows':after[page*50:(page+1)*50],'details':details}
        except bc.ContractError as exc: result['preparation_error']=str(exc)
    return result


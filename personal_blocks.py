"""Account-owned blocks, registered only by an explicit creation action.

Project imports and legacy diagrams never imply authorship. The caller supplies
the authenticated account's storage root, not an owner ID from the request.
"""
from copy import deepcopy

import block_contracts as bc
import subgraphs
from project_store import ProjectStore, now

FILE = 'personal-blocks/catalog.json'


def listing(root):
    store = ProjectStore(root)
    if not store.path(FILE).exists():
        return {'blocks': []}
    return {'blocks': store.read(FILE)['blocks']}


def create(root, body):
    graph, registry = subgraphs.normalize(body.get('diagram'))
    block_type = next((t for t in graph['types'] if t['id'] == body.get('type_id')), None)
    if block_type is None:
        raise bc.ContractError('Выберите созданный блок.')
    # Retain only definitions reachable from this type, never unrelated nodes.
    needed = set()

    def visit(kind):
        if kind in needed or kind not in registry.definitions:
            return
        needed.add(kind)
        definition = registry.definitions[kind]
        for item in definition['graph']['types'] + definition['graph']['nodes']:
            visit(item['block']['kind'])

    visit(block_type['block']['kind'])
    block_type = deepcopy(block_type)
    block_type['id'] = 'personal_type'
    snapshot = {'type': block_type, 'definitions': [registry.definitions[k] for k in sorted(needed)]}
    key = subgraphs.digest(snapshot)
    entry = dict(snapshot, id=key, created_at=now(), origin_name=graph['name'])
    store = ProjectStore(root)
    with store.locked():
        blocks = listing(root)['blocks']
        existing = next((b for b in blocks if b['id'] == key), None)
        if existing:
            return {'block': existing}
        blocks.insert(0, entry)
        store.write(FILE, {'version': 1, 'blocks': blocks})
    return {'block': entry}


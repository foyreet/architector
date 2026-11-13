"""Read-only inventory of reusable datasets in the current account's storage."""
import csv
import local_operations
import hashlib
import json
import re
import zipfile
from pathlib import Path
import block_contracts as bc
import kaggle_data as kg
import ml_operations as ml
import project_store as ps


def listing(root):
    store = ps.ProjectStore(root)
    items, scanned, truncated = [], 0, False
    folder = store.path('workspace/ml-artifacts')
    if folder.exists():
        for path in sorted(folder.glob('*.json')):
            if path.is_symlink() or not re.fullmatch(r'[a-f0-9]{64}\.json', path.name): continue
            scanned += 1
            if scanned > 2000 or len(items) >= 200:
                truncated = True; break
            try:
                raw = path.read_bytes()
                value = json.loads(raw)
                if value.get('kind') != 'dataset' or hashlib.sha256(raw).hexdigest() != path.stem: continue
                data = value.get('content', {})
                if data.get('format') != 'architect.uploaded-csv' or not isinstance(data.get('csv'), str) or not isinstance(data.get('name'), str): continue
                try: delimiter = local_operations.detect_delimiter(data['csv'])
                except csv.Error: delimiter = ','
                items.append({'name': data['name'], 'category': 'Загруженные CSV', 'artifact': bc.artifact('dataset', 'local', path.stem),
                              'files': [data['name']], 'delimiter': delimiter, 'modified': path.stat().st_mtime})
            except (OSError, ValueError): continue
    folder = store.path('workspace/datasets')
    if folder.exists():
        for path in sorted(folder.glob('*/*/*/dataset.zip')):
            scanned += 1
            if scanned > 2000 or len(items) >= 200: truncated = True; break
            owner, name, version, _ = path.relative_to(folder).parts
            source = owner + '/' + name + (('/versions/' + version) if version != 'latest' else '')
            try:
                source = kg.dataset_handle(source)
                archive = kg.archive_path(source, root=store.root)
                if archive != path or not path.is_file(): continue
                with zipfile.ZipFile(path) as zipped:
                    names = [entry['name'] for entry in kg.archive_members(zipped) if entry['name'].lower().endswith('.csv')]
                items.append({'name': source, 'category': 'Датасеты Kaggle', 'artifact': bc.artifact('dataset', 'kaggle', source),
                              'files': names, 'modified': path.stat().st_mtime})
            except (OSError, ValueError, kg.KaggleError, zipfile.BadZipFile): continue
    items.sort(key=lambda item: item['modified'], reverse=True)
    return {'datasets': items, 'truncated': truncated}


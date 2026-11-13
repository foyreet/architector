"""Fixed CPU worker. Input/output JSON only; never deserialize pickle or user code."""
import json
import sys


def run(data):
    import numpy as np
    import scipy
    import sklearn
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, classification_report
    versions = {'python': sys.version.split()[0], 'scikit-learn': sklearn.__version__, 'numpy': np.__version__, 'scipy': scipy.__version__}
    task = data['task']; table = data.get('table', {})
    if task == 'split':
        from collections import Counter
        from math import ceil
        labels = table['y']
        counts = Counter(labels)
        test_count = ceil(len(labels) * data['settings']['test_size'])
        stratified = min(counts.values()) >= 2 and min(test_count, len(labels) - test_count) >= len(counts)
        train, test = train_test_split(list(range(len(table['y']))), test_size=data['settings']['test_size'],
                                      random_state=data['settings']['seed'], stratify=labels if stratified else None)
        return {'train': train, 'test': test, 'versions': versions}
    if task == 'train':
        model = RandomForestClassifier(
            n_estimators=data['settings']['n_estimators'], max_depth=data['settings']['max_depth'],
            random_state=data['settings']['seed'], n_jobs=-1)
        model.fit(table['X'], table['y'])
        trees = []
        for estimator in model.estimators_:
            tree = estimator.tree_
            trees.append({'left': tree.children_left.tolist(), 'right': tree.children_right.tolist(),
                          'feature': tree.feature.tolist(), 'threshold': tree.threshold.tolist(),
                          'value': tree.value[:, 0, :].tolist()})
        return {'format': 'architect.random-forest', 'version': 1, 'classes': model.classes_.tolist(),
                'trees': trees, 'feature_importances': model.feature_importances_.tolist(), 'versions': versions}
    if task in ('evaluate', 'predict'):
        model = data['model']; classes = model['classes']; predictions = []
        # sklearn decision trees convert prediction inputs to float32.
        for row in np.asarray(table['X'], dtype=np.float32):
            votes = np.zeros(len(classes))
            for tree in model['trees']:
                i = 0
                while tree['left'][i] != -1:
                    i = tree['left'][i] if row[tree['feature'][i]] <= tree['threshold'][i] else tree['right'][i]
                probabilities = np.asarray(tree['value'][i]); votes += probabilities / probabilities.sum()
            predictions.append(classes[int(votes.argmax())])
        if task == 'predict': return {'predictions': predictions, 'versions': versions}
        labels = sorted(set(classes) | set(table['y']))
        return {'accuracy': accuracy_score(table['y'], predictions),
                'macro_f1': f1_score(table['y'], predictions, labels=labels, average='macro', zero_division=0),
                'classes': labels, 'confusion_matrix': confusion_matrix(table['y'], predictions, labels=labels).tolist(),
                'report': classification_report(table['y'], predictions, labels=labels, output_dict=True, zero_division=0),
                'predictions': predictions, 'actual': table['y'], 'versions': versions}
    raise ValueError('Неизвестная операция обучения.')


if __name__ == '__main__':
    try:
        print(json.dumps({'result': run(json.load(sys.stdin))}, ensure_ascii=False, allow_nan=False))
    except ImportError:
        print(json.dumps({'error': 'На сервере не установлены зависимости обучения. Установите requirements-ml.txt.'}))
    except ValueError as error:
        print(json.dumps({'error': 'Проверьте данные и параметры обучения: ' + str(error)[:500]}, ensure_ascii=False))


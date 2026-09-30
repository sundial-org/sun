"""Transactional schema/reference checks for model-proposed playbook deltas."""
import copy


def apply_deltas(rules, next_id, operations, seen):
    if not isinstance(operations, list):
        raise ValueError('operations must be a list')
    candidate = copy.deepcopy(rules)
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError('Each operation must be an object')
        evidence = operation.get('evidence')
        if not isinstance(evidence, list) or not evidence or not all(isinstance(x, str) for x in evidence):
            raise ValueError('Every operation needs a nonempty list of review IDs in evidence')
        unknown = sorted(set(evidence) - seen)
        if unknown:
            raise ValueError('Evidence cites review IDs absent from supplied reviews: ' + ', '.join(unknown))
        action = operation.get('op')
        if action not in ['add', 'replace', 'delete']:
            raise ValueError('op must be add, replace, or delete')
        if action != 'delete' and (not isinstance(operation.get('text'), str) or not operation['text'].strip()):
            raise ValueError('add and replace require nonempty text')
        if action == 'add':
            candidate[next_id] = dict(text=operation['text'], evidence=evidence)
            next_id += 1
        else:
            try:
                ident = int(operation['id'])
            except (KeyError, TypeError, ValueError):
                raise ValueError('replace and delete require an existing integer rule ID') from None
            if ident not in candidate:
                raise ValueError('Unknown existing rule ID: ' + str(ident))
            if action == 'delete':
                del candidate[ident]
            else:
                candidate[ident] = dict(text=operation['text'], evidence=evidence)
    text = '\n'.join(f'{i}. {r["text"]}' for i, r in candidate.items())
    return candidate, next_id, text

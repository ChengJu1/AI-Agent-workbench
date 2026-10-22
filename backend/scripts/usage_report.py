"""Read-only usage summaries. Requires an explicit database path; never loads .env."""
import argparse
import json
from pathlib import Path
import sqlite3


FIELDS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
          'cache_creation_input_tokens', 'model_calls', 'tool_calls', 'duration_ms')


def report(path, group_by='conversation', identifier=None):
    column = {'conversation': 'conversation_id', 'agent': 'agent_id'}[group_by]
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        rows = connection.execute(
            f'SELECT {column}, usage FROM runtime_usage' + (f' WHERE {column}=?' if identifier else '') + ' ORDER BY id',
            (identifier,) if identifier else (),
        ).fetchall()
    groups = {}
    for key, raw in rows:
        usage = json.loads(raw)
        group = groups.setdefault(key, {'turns': 0, 'totals': {field: 0 for field in FIELDS},
                                        'measured_turns': {field: 0 for field in FIELDS},
                                        'first_token_ms': [], 'context_estimates': []})
        group['turns'] += 1
        for field in FIELDS:
            value = usage.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                group['totals'][field] += value
                group['measured_turns'][field] += 1
        if usage.get('first_token_ms') is not None:
            group['first_token_ms'].append(usage['first_token_ms'])
        group['context_estimates'].append(usage.get('context_estimate', {}))
    for group in groups.values():
        times = group.pop('first_token_ms')
        group['average_first_token_ms'] = sum(times) / len(times) if times else None
        group['first_token_measured_turns'] = len(times)
        for field in FIELDS:
            if not group['measured_turns'][field]:
                group['totals'][field] = None
    return groups


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--group-by', choices=['conversation', 'agent'], default='conversation')
    parser.add_argument('--id', help='Limit to a conversation or agent ID')
    arguments = parser.parse_args()
    print(json.dumps(report(arguments.database, arguments.group_by, arguments.id), ensure_ascii=False, indent=2))

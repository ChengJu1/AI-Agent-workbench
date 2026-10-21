"""Today's to-do list, computed from the ledger, approvals and tracking. Rules only: no model is called."""
import json
import time
from datetime import date, datetime, timedelta

OPEN = ('saved', 'preparing')
CLOSED = ('offer', 'rejected', 'withdrawn')
FOLLOW_UP_DAYS = 14


def _day(value):
    try:
        return datetime.strptime(value[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def build_brief(applications, database, today=None):
    today = today or date.today()
    title = lambda item: ' · '.join(part for part in (item['company'], item['position']) if part)
    sections = {key: [] for key in ('due', 'soon', 'events', 'kit', 'follow_up', 'waiting')}
    for item in applications:
        deadline = _day(item['deadline'])
        if deadline and item['stage'] in OPEN:
            if deadline < today:
                sections['due'].append({'ref': item['id'], 'text': title(item), 'detail': f'已过截止 {(today - deadline).days} 天，还没投递'})
            elif deadline == today:
                sections['due'].append({'ref': item['id'], 'text': title(item), 'detail': '今天截止'})
            elif deadline <= today + timedelta(days=3):
                sections['soon'].append({'ref': item['id'], 'text': title(item), 'detail': f'{item["deadline"]} 截止'})
        event = _day(item['next_event_at'])
        if event and today <= event <= today + timedelta(days=1) and item['stage'] not in CLOSED:
            when = '今天' if event == today else '明天'
            sections['events'].append({'ref': item['id'], 'text': title(item), 'detail': f'{when} {item["next_event_at"][11:]} {item["next_event"]}'.replace('  ', ' ')})
        if item['stage'] == 'preparing' and not item.get('has_kit'):
            sections['kit'].append({'ref': item['id'], 'text': title(item), 'detail': '还没有资料包'})
        applied = _day(item['applied_at'])
        if item['stage'] == 'applied' and applied and (today - applied).days >= FOLLOW_UP_DAYS:
            sections['follow_up'].append({'ref': item['id'], 'text': title(item), 'detail': f'投递 {(today - applied).days} 天没有进展，可以查一下状态'})
    with database.connection() as connection:
        pending = [row for row in connection.execute("SELECT params FROM pending_actions WHERE status='pending'").fetchall()
                   if json.loads(row['params']).get('expires_at', float('inf')) > time.time()]
        unread = connection.execute('SELECT COALESCE(SUM(unread),0) FROM tracking_tasks').fetchone()[0]
    if pending:
        sections['waiting'].append({'ref': 'approvals', 'text': f'{len(pending)} 个操作等你确认', 'detail': '在对应对话的确认栏里处理'})
    if unread:
        sections['waiting'].append({'ref': 'tracking', 'text': f'跟踪有 {unread} 条新消息', 'detail': '在「记录与跟踪」里查看'})
    titles = {'due': '今天必须处理', 'soon': '三天内截止', 'events': '今明两天的笔试面试', 'kit': '还没准备资料包',
              'follow_up': '可以跟进', 'waiting': '等你处理'}
    result = [{'id': key, 'title': titles[key], 'items': items} for key, items in sections.items() if items]
    return {'date': today.isoformat(), 'total': sum(len(s['items']) for s in result), 'sections': result}

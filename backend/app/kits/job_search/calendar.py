"""iCalendar export of ledger dates, so the user's own calendar app does the reminding."""
from datetime import datetime, timedelta, timezone

OPEN = ('saved', 'preparing')
CLOSED = ('offer', 'rejected', 'withdrawn')


def escape(text):
    return text.replace('\\', '\\\\').replace(';', '\;').replace(',', '\\,').replace('\n', '\\n')


def fold(line):
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, current = [], ''
    for char in line:
        if len((current + char).encode()) > 75:
            out.append(current)
            current = ' ' + char
        else:
            current += char
    return '\r\n'.join(out + [current])


def build_calendar(applications, now=None):
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//AI Agent Workbench//Application Ledger//ZH', 'CALSCALE:GREGORIAN',
             'X-WR-CALNAME:投递台账']
    for item in applications:
        title = ' · '.join(part for part in (item['company'], item['position']) if part)
        if item['deadline'] and item['stage'] in OPEN:
            day = datetime.strptime(item['deadline'], '%Y-%m-%d')
            lines += ['BEGIN:VEVENT', f'UID:{item["id"]}-deadline@workbench', f'DTSTAMP:{stamp}',
                      f'DTSTART;VALUE=DATE:{day:%Y%m%d}', f'DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}',
                      f'SUMMARY:{escape("投递截止：" + title)}', *([f'URL:{item["url"]}'] if item['url'] else []),
                      'BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{escape("明天截止：" + title)}', 'TRIGGER:-P1D', 'END:VALARM', 'END:VEVENT']
        if item['next_event_at'] and item['stage'] not in CLOSED:
            fmt = '%Y-%m-%d %H:%M' if ' ' in item['next_event_at'] else '%Y-%m-%d'
            start = datetime.strptime(item['next_event_at'], fmt)
            timed = ' ' in item['next_event_at']
            # Floating local time: the calendar shows it at the hour the user typed, wherever they are.
            dates = ([f'DTSTART:{start:%Y%m%dT%H%M%S}', f'DTEND:{start + timedelta(hours=1):%Y%m%dT%H%M%S}'] if timed
                     else [f'DTSTART;VALUE=DATE:{start:%Y%m%d}', f'DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}'])
            lines += ['BEGIN:VEVENT', f'UID:{item["id"]}-event@workbench', f'DTSTAMP:{stamp}', *dates,
                      f'SUMMARY:{escape(item["next_event"] + "：" + title)}', *([f'URL:{item["url"]}'] if item['url'] else []),
                      'BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{escape(item["next_event"] + "：" + title)}',
                      f'TRIGGER:{"-PT1H" if timed else "-P1D"}', 'END:VALARM', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold(line) for line in lines) + '\r\n'

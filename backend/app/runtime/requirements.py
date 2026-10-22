"""Verbatim explicit user constraints, rebuilt from source messages, never summaries."""
import re


# Only unambiguous constraint words; casual 不要/不能/只能/始终 matched ordinary chat ("不要紧", "只能说还行").
MARKER = re.compile(r'硬性要求|必须|务必|不得|禁止|严禁|请勿|切勿|一律|只考虑|只允许|仅限|要求[:：]|\b(?:must|never|do not)\b', re.I)
HEADING = re.compile(r'^\s*(?:#{1,6}\s*)?(?:硬性要求|硬性约束|必须遵守|要求|hard requirements|requirements|constraints)\s*(?:[:：].*)?\s*$', re.I)
# The excerpts are re-sent every turn and never compacted, so they stay bounded.
BUDGET_CHARS = 3000
ITEM_CHARS = 800


def _matches(content):
    block, lines = False, []
    for line in content.splitlines(keepends=True):
        if HEADING.match(line):
            block = True
            lines.append(line)
            continue
        if block and (not line.strip() or re.match(r'^\s*#{1,6}\s', line)):
            block = False
        if block:
            lines.append(line)
        else:
            lines.extend(sentence for sentence in re.split(r'(?<=[。！？])|(?<=[.!?])\s+', line) if MARKER.search(sentence))
    return lines


def explicit_requirements(requests, budget=BUDGET_CHARS):
    """Return (excerpts in chronological order, omitted message count); newest first within the budget."""
    entries = [(request['id'], lines) for request in requests if (lines := _matches(request['content']))]
    kept, seen, used = [], set(), 0
    for position, (message_id, lines) in enumerate(reversed(entries)):
        fresh = []
        for line in lines:
            key = ' '.join(line.split())
            if key and key not in seen:
                seen.add(key)
                fresh.append(line)
        text = ''.join(fresh).strip()
        if not text:
            continue
        if len(text) > ITEM_CHARS:
            text = text[:ITEM_CHARS] + '…'
        if used + len(text) > budget:
            return list(reversed(kept)), len(entries) - position
        kept.append({'message_id': message_id, 'text': text})
        used += len(text)
    return list(reversed(kept)), 0

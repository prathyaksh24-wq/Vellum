"""Evidence-based wording for bounded, account-scoped browser activity."""
import re
from collections import Counter


# These describe words in video titles, not inferred beliefs or motivations.
TITLE_THEMES = {
    'chess':r'\b(?:chess|checkmate|elo|gothamchess|carlsen|endgames?|hikaru)\b',
    'Formula 1':r'\b(?:f1|formula 1|grand prix|gp|verstappen|qualifying)\b',
    'basketball':r'\b(?:nba|basketball|lebron|luka|knicks|spurs|jordan)\b',
    'football':r'\b(?:football|man city|premier league|soccer)\b',
    'AI and technology':r'\b(?:ai|artificial intelligence|programming|engineering|software)\b',
    'music and entertainment':r'\b(?:k-pop|twice|aespa|album|song|music|drama|trailer|premiere)\b',
}


def describe_activity(items: list[dict], result: dict) -> str:
    """Use auditable counts; never imply watch duration or full-account coverage."""
    if not items:
        return ('I found no captured watch-history entries for this account and filter, so I do not have activity to analyze yet. '
            'This does not prove that you watched nothing; the history available to Vellum is partial.')
    channels = Counter(str(item.get('channel') or item.get('channel_title') or '').strip() for item in items)
    channels.pop('', None)
    days = Counter(str(item.get('history_day') or '') for item in items)
    days.pop('', None)
    count = len(items)
    span = (' from ' + min(days) + ' to ' + max(days)) if len(days) > 1 else (' on ' + next(iter(days))) if days else ''
    text = [f'I analyzed {count} captured video/day entries{span} from the account currently signed into Vellum’s Browser.']
    if channels:
        top = channels.most_common(5)
        labels = ', '.join(f'{name} ({n})' for name, n in top)
        text.append(f'The most represented channels are {labels}; I found {len(channels)} distinct channel names in this sample.')
        if top[0][1] > 1:
            name, n = top[0]
            text.append(f'{name} appears in {n} of the {count} entries ({round(n / count * 100)}%), making it a recurring channel in the captured activity.')
    themes = [(label, sum(bool(re.search(pattern, str(item.get('title') or ''), re.I)) for item in items))
        for label, pattern in TITLE_THEMES.items()]
    themes = sorted(((label,n) for label,n in themes if n), key=lambda row:row[1], reverse=True)[:4]
    if themes:
        text.append('The video titles suggest recurring topics: ' + ', '.join(f'{label} ({n} matching entries)' for label,n in themes) +
            '. These are title-based groupings and can overlap.')
    if len(days) > 1:
        day, n = max(days.items(), key=lambda row:(row[1],row[0]))
        text.append(f'The largest captured day in this sample is {day}, with {n} entries. '
            'Different amounts of history may have been captured for each day, so this does not establish an increase or decrease in viewing.')
    coverage = 'I refreshed your browser account and included history saved locally for the same account.' if result.get('coverage') == 'fresh_and_accumulated' else 'I refreshed the recent history page for this answer.'
    total = result.get('total', count)
    if total > count:
        coverage += f' The analysis uses the most recent {count} of {total} captured entries.'
    return '\n\n'.join([' '.join(text), coverage + ' This is partial history. '
        'Entries count distinct video/day observations, not every repeat play. Exact watch times and watch duration are unavailable; '
        'I cannot establish long-term changes in interest from this sample alone.'])

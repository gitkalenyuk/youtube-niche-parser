# -*- coding: utf-8 -*-
"""
scraper.py — ядро парсера ніш YouTube (без API, через публічний веб як в анонімному режимі).

Тільки стандартна бібліотека Python (urllib) — жодних залежностей для встановлення.

Що вміє:
  * пошук youtube.com/results?search_query=<q>&sp=<filter> + витяг ytInitialData;
  * пагінація через внутрішній InnerTube API (continuation) -> налаштовуваний ліміт;
  * звичайні відео (videoRenderer) і Shorts (shortsLockupViewModel);
  * збірка фільтра sp=... програмно з вибраних опцій (дата/тип/тривалість/характеристики/сортування);
  * скрейп кількості підписників каналу (для фільтра "макс. підписників" і колонки).
"""

import urllib.request
import urllib.parse
import json
import re
import base64

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36')


# ---------------------------------------------------------------------------
# HTTP (stdlib)
# ---------------------------------------------------------------------------
def http_get(url, hl='uk'):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept-Language': f'{hl},en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read().decode('utf-8', 'replace')


def http_post_json(url, payload, hl='uk'):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'User-Agent': UA,
        'Content-Type': 'application/json',
        'Accept-Language': f'{hl},en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read().decode('utf-8', 'replace')


# ---------------------------------------------------------------------------
# Збірка фільтра sp= (protobuf)  — підтверджено: build_sp(date=3,typ=1,dur=2)=="EgYIAxABGAI%3D"
# ---------------------------------------------------------------------------
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _field(num, val):  # wiretype 0 (varint)
    return bytes([num << 3]) + _varint(val)


# Номери полів характеристик усередині під-повідомлення фільтра:
FEATURE_FIELDS = {
    'hd': 4, 'subtitles': 5, 'creative_commons': 6, 'is3d': 7,
    'live': 8, 'purchased': 9, 'is4k': 14, 'is360': 15,
    'location': 23, 'hdr': 25, 'vr180': 26,
}
# Дата завантаження: 1=остання година, 2=сьогодні, 3=цього тижня, 4=цього місяця, 5=цього року
# Тип: 1=відео, 2=канал, 3=плейлист, 4=фільм
# Тривалість: 1=короткі(<4хв), 2=довгі(>20хв), 3=середні(4-20хв)
# Сортування: 0=відповідність, 1=рейтинг, 2=дата завантаження, 3=перегляди


def build_sp(sort=0, date=0, typ=0, dur=0, features=None):
    filt = b''
    if date:
        filt += _field(1, date)
    if typ:
        filt += _field(2, typ)
    if dur:
        filt += _field(3, dur)
    for f in (features or []):
        fn = FEATURE_FIELDS.get(f)
        if fn:
            filt += _field(fn, 1)
    msg = b''
    if sort:
        msg += _field(1, sort)
    if filt:
        msg += bytes([(2 << 3) | 2]) + _varint(len(filt)) + filt
    if not msg:
        return ''
    return urllib.parse.quote(base64.b64encode(msg).decode())


# ---------------------------------------------------------------------------
# Парсинг чисел / часу
# ---------------------------------------------------------------------------
_MULT = [
    (re.compile(r'тис|тыс|тисяч', re.I), 1e3),
    (re.compile(r'млрд|мільярд', re.I), 1e9),
    (re.compile(r'млн|мільйон', re.I), 1e6),
    (re.compile(r'\bK\b', re.I), 1e3),
    (re.compile(r'\bM\b', re.I), 1e6),
    (re.compile(r'\bB\b', re.I), 1e9),
]


def parse_count(text):
    """'4 779' -> 4779; '7,22 тис.' -> 7220; '501 млн' -> 501000000; '1.2M' -> 1200000."""
    if not text:
        return None
    t = str(text).replace('\xa0', ' ').replace(' ', ' ')
    mult = 1
    for rx, m in _MULT:
        if rx.search(t):
            mult = m
            break
    if mult != 1:
        num = re.search(r'[\d]+(?:[.,]\d+)?', t)
        if not num:
            return None
        val = float(num.group(0).replace(' ', '').replace(',', '.'))
        return int(round(val * mult))
    digits = re.sub(r'[^\d]', '', t)
    return int(digits) if digits else None


def parse_duration(text):
    """'1:02:38' -> 3758 секунд."""
    if not text:
        return None
    parts = str(text).strip().split(':')
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    sec = 0
    for p in nums:
        sec = sec * 60 + p
    return sec


_AGE_UNITS = [
    (re.compile(r'секунд|сек|second', re.I), 1 / 3600),
    (re.compile(r'хвилин|хв|минут|мин|minute', re.I), 1 / 60),
    (re.compile(r'годин|год|час\b|hour', re.I), 1),
    (re.compile(r'тиж|недел|week', re.I), 168),
    (re.compile(r'міс|мес|month', re.I), 730),
    (re.compile(r'рік|рок|лет|год$|year', re.I), 8760),
    (re.compile(r'дн|день|дні|днів|day', re.I), 24),
]


def parse_age_hours(text):
    if not text:
        return None
    m = re.search(r'\d+', text)
    n = int(m.group(0)) if m else 1
    for rx, h in _AGE_UNITS:
        if rx.search(text):
            return n * h
    return None


def thumb(video_id):
    return f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'


# ---------------------------------------------------------------------------
# Витяг даних зі сторінки
# ---------------------------------------------------------------------------
def extract_initial_data(html):
    m = re.search(r'var ytInitialData = (\{.+?\});</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _abs_url(u):
    if not u:
        return ''
    return u if u.startswith('http') else ('https://www.youtube.com' + u)


def collect_videos(node, out):
    if isinstance(node, dict):
        vr = node.get('videoRenderer')
        if vr and vr.get('videoId'):
            views_text = (
                (vr.get('viewCountText') or {}).get('simpleText')
                or ''.join(r.get('text', '') for r in (vr.get('viewCountText') or {}).get('runs', []))
                or (vr.get('shortViewCountText') or {}).get('simpleText')
                or ''
            )
            owner = (vr.get('ownerText') or {}).get('runs') or (vr.get('longBylineText') or {}).get('runs') or []
            ch_name = owner[0]['text'] if owner else ''
            ch_url = ''
            try:
                ch_url = _abs_url(owner[0]['navigationEndpoint']['commandMetadata']['webCommandMetadata']['url'])
            except Exception:
                pass
            vid = vr['videoId']
            out.append({
                'id': vid,
                'url': f'https://www.youtube.com/watch?v={vid}',
                'kind': 'video',
                'title': ''.join(r.get('text', '') for r in (vr.get('title') or {}).get('runs', [])),
                'channel': ch_name,
                'channelUrl': ch_url,
                'viewsText': views_text,
                'views': parse_count(views_text),
                'publishedText': (vr.get('publishedTimeText') or {}).get('simpleText', ''),
                'ageHours': parse_age_hours((vr.get('publishedTimeText') or {}).get('simpleText', '')),
                'durationText': (vr.get('lengthText') or {}).get('simpleText', ''),
                'durationSec': parse_duration((vr.get('lengthText') or {}).get('simpleText', '')),
                'thumbnail': thumb(vid),
                'subs': None,
            })
        for v in node.values():
            collect_videos(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_videos(v, out)


def collect_shorts(node, out):
    if isinstance(node, dict):
        sm = node.get('shortsLockupViewModel')
        if sm:
            vid = ''
            try:
                vid = sm['onTap']['innertubeCommand']['reelWatchEndpoint']['videoId']
            except Exception:
                eid = sm.get('entityId', '')
                m = re.search(r'([A-Za-z0-9_-]{11})$', eid)
                vid = m.group(1) if m else ''
            acc = sm.get('accessibilityText', '') or ''
            views = None
            title = acc
            mv = re.search(r'([\d][\d.,\s\xa0]*(?:тис[.]?|млн|млрд|мільйон\w*|мільярд\w*|тисяч\w*|K|M|B)?)\s*перегляд', acc, re.I)
            if mv:
                views = parse_count(mv.group(1))
                # назва = усе до початку числа переглядів (без хвостової коми)
                head = acc[:mv.start()].rstrip().rstrip(',').rstrip()
                if head:
                    title = head
            if vid:
                out.append({
                    'id': vid,
                    'url': f'https://www.youtube.com/shorts/{vid}',
                    'kind': 'short',
                    'title': title,
                    'channel': '',
                    'channelUrl': '',
                    'viewsText': (mv.group(0) if mv else ''),
                    'views': views,
                    'publishedText': '',
                    'ageHours': None,
                    'durationText': 'Shorts',
                    'durationSec': None,
                    'thumbnail': thumb(vid),
                    'subs': None,
                })
        for v in node.values():
            collect_shorts(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_shorts(v, out)


def find_continuation(node):
    found = [None]

    def walk(x):
        if found[0] or not isinstance(x, (dict, list)):
            return
        if isinstance(x, dict):
            cir = x.get('continuationItemRenderer')
            if cir:
                try:
                    found[0] = cir['continuationEndpoint']['continuationCommand']['token']
                except Exception:
                    pass
                return
            for v in x.values():
                walk(v)
        else:
            for v in x:
                walk(v)
    walk(node)
    return found[0]


# ---------------------------------------------------------------------------
# Пошук однієї ніші
# ---------------------------------------------------------------------------
def search_niche(query, sp='', max_results=20, mode='video', hl='uk', gl='UA'):
    """Повертає (videos:list, error:str|None)."""
    url = 'https://www.youtube.com/results?search_query=' + urllib.parse.quote(query)
    if sp:
        url += '&sp=' + sp
    try:
        status, body = http_get(url, hl)
    except Exception as e:
        return [], f'Мережа: {e}'
    if status != 200:
        return [], f'HTTP {status}'

    yd = extract_initial_data(body)
    if not yd:
        blocked = bool(re.search(r'consent|captcha|sorry', body, re.I)) and len(body) < 200000
        return [], ('Можливий тимчасовий блок/капча (збільш паузу або зміни IP)'
                    if blocked else 'Не знайдено ytInitialData')

    collector = collect_shorts if mode == 'short' else collect_videos
    items = []
    collector(yd, items)

    api_key = (re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', body) or [None, None])[1]
    cver = (re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"', body)
            or re.search(r'"clientVersion":"([^"]+)"', body) or [None, None])[1]
    token = find_continuation(yd)

    guard = 0
    while token and api_key and cver and len(items) < max_results and guard < 60:
        guard += 1
        try:
            status, raw = http_post_json(
                f'https://www.youtube.com/youtubei/v1/search?key={api_key}',
                {'context': {'client': {'clientName': 'WEB', 'clientVersion': cver, 'hl': hl, 'gl': gl}},
                 'continuation': token},
                hl)
        except Exception:
            break
        if status != 200:
            break
        try:
            j = json.loads(raw)
        except Exception:
            break
        before = len(items)
        collector(j, items)
        token = find_continuation(j)
        if len(items) == before:
            break

    # дедуп
    seen = set()
    uniq = []
    for v in items:
        if v['id'] in seen:
            continue
        seen.add(v['id'])
        uniq.append(v)
    return uniq[:max_results], None


# ---------------------------------------------------------------------------
# Підписники каналу
# ---------------------------------------------------------------------------
_SUBS_PATS = [
    re.compile(r'"metadataParts":\[\{"text":\{"content":"([^"]*?(?:підписник|подписчик|subscriber)[^"]*?)"', re.I),
    re.compile(r'"content":"([0-9][^"]*?(?:підписник|подписчик|subscriber)[^"]*?)"', re.I),
    re.compile(r'"subscriberCountText":\{[^}]*?"simpleText":"([^"]+)"'),
]


def channel_subs(channel_url, hl='uk'):
    """Повертає (subs:int|None, subsText:str)."""
    if not channel_url:
        return None, ''
    try:
        status, body = http_get(channel_url, hl)
    except Exception:
        return None, ''
    if status != 200:
        return None, ''
    for pat in _SUBS_PATS:
        m = pat.search(body)
        if m:
            txt = m.group(1)
            return parse_count(txt), txt
    return None, ''

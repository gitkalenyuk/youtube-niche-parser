# -*- coding: utf-8 -*-
"""
app.py — YouTube Niche Parser Pro V3 (без API, через проксіювання/скрейпінг).

Піднімає локальний сервер (тільки стандартна бібліотека) і відкриває UI у власному
вікні через Chrome/Edge у режимі --app (без вкладок, як десктоп-додаток).

Запуск:  python app.py     (зазвичай через START.bat)
"""

import os
import sys
import json
import time
import threading
import subprocess
import tempfile
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor, as_completed

# службовий вивід у UTF-8 (щоб кирилиця не впала в консолі з cp1252)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# База для ui.html / scraper. У зібраному .app (PyInstaller) ресурси лежать у sys._MEIPASS.
if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import scraper  # noqa: E402

UI_PATH = os.path.join(BASE_DIR, 'ui.html')

# кеш підписників на час життя процесу: channelUrl -> (subs, subsText)
SUBS_CACHE = {}
SUBS_LOCK = threading.Lock()

# «пульс» від вікна: поки сторінка відкрита, вона пінгує сервер.
# Закриваємось ОДРАЗУ тільки коли реально закрили вікно (сигнал /api/bye),
# або якщо пульсу нема дуже довго (IDLE_LIMIT) — резерв на випадок краху/вильоту.
LAST_PING = time.time() + 60   # фора на старт/завантаження сторінки
CLOSED = False                 # True -> вікно закрите, час завершуватись
IDLE_LIMIT = 180               # сек без пульсу до авто-завершення (фон гальмує таймери — тому щедро)


def get_subs(url, hl):
    if not url:
        return None, ''
    with SUBS_LOCK:
        if url in SUBS_CACHE:
            return SUBS_CACHE[url]
    res = scraper.channel_subs(url, hl)
    with SUBS_LOCK:
        SUBS_CACHE[url] = res
    return res


def run_search(payload, emit):
    """Проганяє всі запити, шле події через emit(dict). Блокуюча."""
    queries = [q.strip() for q in (payload.get('queries') or []) if q.strip()]
    mode = 'short' if payload.get('contentType') == 'shorts' else 'video'
    sort = int(payload.get('sort') or 0)
    date = int(payload.get('date') or 0)
    dur = int(payload.get('duration') or 0)
    features = payload.get('features') or []
    max_results = max(1, min(500, int(payload.get('maxResults') or 20)))
    delay_ms = max(0, min(30000, int(payload.get('delayMs') or 4000)))
    min_views = max(0, int(payload.get('minViews') or 0))
    max_subs = int(payload.get('maxSubs') or 0)  # 0 = без обмеження
    threads = max(1, min(8, int(payload.get('threads') or 1)))  # паралельність запитів
    hl, gl = 'uk', 'UA'

    typ = 0 if mode == 'short' else 1  # для shorts тип не фіксуємо (інакше зникає reel-полиця)
    sp = scraper.build_sp(sort=sort, date=date, typ=typ,
                          dur=(0 if mode == 'short' else dur), features=features)

    emit({'type': 'start', 'total': len(queries), 'sp': sp, 'mode': mode, 'threads': threads})

    # обробка одного запиту (виконується у воркер-потоці при threads>1; emit тут НЕ викликаємо)
    def process_one(query):
        try:
            videos, err = scraper.search_niche(query, sp=sp, max_results=max_results,
                                               mode=mode, hl=hl, gl=gl)
        except Exception as e:
            return {'count': 0, 'videos': [], 'error': str(e)}
        if err:
            return {'count': 0, 'videos': [], 'error': err}
        # 1) пост-фільтр по мін. переглядах
        if min_views:
            videos = [v for v in videos if (v.get('views') or 0) >= min_views]
        # 2) підписники (послідовно в межах воркера; глобальний кеш робить повтори безкоштовними)
        if mode != 'short':
            for v in videos:
                u = v.get('channelUrl')
                if u:
                    v['subs'], v['subsText'] = get_subs(u, hl)
            # 3) пост-фільтр по макс. підписниках (невідомих не викидаємо)
            if max_subs > 0:
                videos = [v for v in videos if v.get('subs') is None or v['subs'] <= max_subs]
        for v in videos:
            v['query'] = query
        return {'count': len(videos), 'videos': videos}

    total = len(queries)
    if threads <= 1:
        # послідовно з паузою (найбезпечніше)
        for i, query in enumerate(queries):
            emit({'type': 'progress', 'done': i, 'total': total, 'query': query})
            r = process_one(query)
            emit({'type': 'result', 'index': i, 'query': query, **r})
            if i < total - 1 and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
    else:
        # паралельно; emit тільки з головного потоку (цикл as_completed) -> NDJSON не б'ється
        with ThreadPoolExecutor(max_workers=threads) as ex:
            futs = {ex.submit(process_one, q): (i, q) for i, q in enumerate(queries)}
            done = 0
            for fut in as_completed(futs):
                i, query = futs[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {'count': 0, 'videos': [], 'error': str(e)}
                done += 1
                emit({'type': 'progress', 'done': done, 'total': total, 'query': query})
                emit({'type': 'result', 'index': i, 'query': query, **r})

    emit({'type': 'done'})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # тиша

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            try:
                with open(UI_PATH, 'rb') as f:
                    data = f.read()
            except OSError:
                self.send_error(500, 'ui.html not found')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == '/health':
            self._json({'ok': True, 'name': 'YouTube Niche Parser Pro V3'})
        elif self.path == '/api/ping':
            global LAST_PING
            LAST_PING = time.time()
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
        elif self.path == '/api/bye':
            self._bye()
        else:
            self.send_error(404)

    def _bye(self):
        # вікно реально закрили -> завершуємось одразу
        global CLOSED
        CLOSED = True
        try:
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
        except Exception:
            pass

    def _save(self):
        # Зберігаємо експорт на диск самим сервером — у режимі Chrome --app
        # завантаження через blob/<a download> ненадійне (нема панелі, мовчки гине).
        length = int(self.headers.get('Content-Length') or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            self._json({'error': 'bad json'}, 400)
            return
        content = payload.get('content')
        if not isinstance(content, str):
            self._json({'error': 'no content'}, 400)
            return
        fmt = 'txt' if payload.get('format') == 'txt' else 'csv'
        name = os.path.basename(str(payload.get('filename') or '')) or ('youtube-nishi.' + fmt)
        if not name.lower().endswith('.' + fmt):
            name += '.' + fmt

        target_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        if not os.path.isdir(target_dir):
            target_dir = os.path.expanduser('~')

        base, ext = os.path.splitext(name)
        path = os.path.join(target_dir, name)
        i = 1
        while os.path.exists(path):
            path = os.path.join(target_dir, f'{base} ({i}){ext}')
            i += 1

        # CSV з BOM (utf-8-sig) — щоб Excel коректно читав кирилицю; TXT — звичайний utf-8.
        try:
            with open(path, 'w', encoding=('utf-8-sig' if fmt == 'csv' else 'utf-8'), newline='') as f:
                f.write(content)
        except Exception as e:
            self._json({'error': str(e)}, 500)
            return
        self._json({'ok': True, 'path': path})

    def do_POST(self):
        if self.path == '/api/bye':  # sendBeacon шле POST
            self._bye()
            return
        if self.path == '/api/save':
            self._save()
            return
        if self.path != '/api/search':
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length') or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            self._json({'error': 'bad json'}, 400)
            return

        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        def emit(obj):
            try:
                self.wfile.write((json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise
        try:
            run_search(payload, emit)
        except (BrokenPipeError, ConnectionResetError):
            pass  # вікно закрили посеред пошуку

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------------------------------------------------------------------
# Запуск вікна (Chrome/Edge --app), інакше — браузер за замовчуванням
# ---------------------------------------------------------------------------
def find_browser():
    """Знайти Chrome/Edge для режиму --app (нативне вікно). None -> запасний браузер (вкладка)."""
    env = os.environ.get('CHROME_PATH')
    if env and os.path.exists(env):
        return env

    # macOS
    if sys.platform == 'darwin':
        for p in [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
            '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ]:
            if os.path.exists(p):
                return p
        return None

    # Windows
    if os.name == 'nt':
        # 1) реєстр App Paths — знаходить Chrome/Edge у БУДЬ-ЯКОМУ місці встановлення
        try:
            import winreg
            for exe in ('chrome.exe', 'msedge.exe'):
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        sub = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths' + '\\' + exe
                        with winreg.OpenKey(hive, sub) as k:
                            path = winreg.QueryValue(k, None)
                            if path and os.path.exists(path):
                                return path
                    except OSError:
                        pass
        except Exception:
            pass
        # 2) типові шляхи (резерв) — Edge є на кожному Windows 10/11
        pf = os.environ.get('ProgramFiles', r'C:\Program Files')
        pfx = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
        la = os.environ.get('LOCALAPPDATA', '')
        for p in [
            os.path.join(pf, r'Google\Chrome\Application\chrome.exe'),
            os.path.join(pfx, r'Google\Chrome\Application\chrome.exe'),
            os.path.join(la, r'Google\Chrome\Application\chrome.exe'),
            os.path.join(pfx, r'Microsoft\Edge\Application\msedge.exe'),
            os.path.join(pf, r'Microsoft\Edge\Application\msedge.exe'),
        ]:
            if p and os.path.exists(p):
                return p
        return None

    # Linux
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge'):
        p = shutil.which(name)
        if p:
            return p
    return None


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    port = httpd.server_address[1]
    url = f'http://127.0.0.1:{port}/'
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f'[yt-niche] Сервер: {url}')

    browser = find_browser()
    profile = tempfile.mkdtemp(prefix='ytniche-')
    proc = None
    global LAST_PING
    LAST_PING = time.time() + 60  # фора, поки вікно відкриється і почне пінгувати
    try:
        if browser:
            proc = subprocess.Popen([
                browser,
                f'--app={url}',
                f'--user-data-dir={profile}',
                '--window-size=1320,860',
                '--no-first-run',
                '--no-default-browser-check',
            ])
            print('[yt-niche] Вікно відкрито. Закрий його, щоб завершити.')
        else:
            import webbrowser
            webbrowser.open(url)
            print('[yt-niche] Chrome/Edge не знайдено — відкрив у браузері за замовч.')
            print('[yt-niche] Закрий вкладку або натисни Ctrl+C, щоб завершити.')

        # Живемо, поки вікно відкрите. Закриваємось, коли:
        #   * вікно реально закрили (CLOSED через /api/bye) — одразу;
        #   * пульсу нема довше IDLE_LIMIT (крах/виліт) — резервний запобіжник.
        # Простій (вікно відкрите, але не у фокусі) НЕ закриває: поріг 180с >> гальмування фону.
        last_tick = time.time()
        while not CLOSED:
            time.sleep(2)
            now = time.time()
            if now - last_tick > 30:   # система спала/призупинялась -> не рахуємо за простій
                LAST_PING = now        # даємо вікну шанс знову запінгувати після пробудження
            last_tick = now
            if now - LAST_PING > IDLE_LIMIT:
                break
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        try:
            if proc and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)
        print('[yt-niche] Завершено.')


if __name__ == '__main__':
    main()

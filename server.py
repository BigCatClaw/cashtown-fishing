"""Cash Town fishing log server.

Serves index.html and saves every change to fishing-log.db (SQLite) next to this file.
It also keeps the public website up to date: 10 minutes after the last change it writes
data.json and pushes it to GitHub, where GitHub Pages serves it. That only happens when
this folder is a git repository with a GitHub remote.

Run:  python server.py     (or double-click start.bat)
Options:  --port 8765  --no-browser  --no-publish
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / 'fishing-log.db'
DATA_JSON = HERE / 'data.json'
PUBLISH_DELAY = 10 * 60  # seconds after the last change before the website is updated
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
SETTINGS = ('version', 'categories', 'current', 'currentSince', 'lastBackup', 'seeds')

db_lock = threading.Lock()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS catches (
            id          TEXT PRIMARY KEY,
            t           INTEGER NOT NULL,   -- ms since 1970, keeps catches in order
            caught_at   TEXT,               -- local "YYYY-MM-DD HH:MM" (empty for paper notes)
            weekday     TEXT,
            hour        INTEGER,
            fish        TEXT NOT NULL,
            conditions  TEXT NOT NULL,      -- {"Weather": "ฝนตก", "Lure": "ไส้เดือน", "Water": "น้ำลึก"}
            cond        TEXT NOT NULL,      -- same values keyed by condition id (used by the page)
            from_notes  INTEGER NOT NULL DEFAULT 0,
            note_time   TEXT
        )''')
    conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    return conn


def load_state(conn):
    settings = {k: json.loads(v) for k, v in conn.execute('SELECT key, value FROM settings')}
    if not settings:
        return None
    catches = []
    for id_, t, fish, cond, note, note_time in conn.execute(
            'SELECT id, t, fish, cond, from_notes, note_time FROM catches ORDER BY t'):
        c = {'id': id_, 't': t, 'fish': fish, 'cond': json.loads(cond)}
        if note:
            c['note'] = True
        if note_time:
            c['hm'] = note_time
        catches.append(c)
    return {**settings, 'catches': catches}


def save_state(conn, state):
    if not isinstance(state, dict) or not isinstance(state.get('catches'), list) \
            or not isinstance(state.get('categories'), list):
        raise ValueError('not a fishing log')
    names = {c['id']: c['name'] for c in state['categories']}
    rows = []
    for c in state['catches']:
        cond = c.get('cond') or {}
        note = bool(c.get('note'))
        hm = c.get('hm')
        if note:
            caught_at = weekday = None
            hour = int(hm[:2]) if hm else None
        else:
            d = datetime.fromtimestamp(c['t'] / 1000)
            caught_at, weekday, hour = d.strftime('%Y-%m-%d %H:%M'), WEEKDAYS[d.weekday()], d.hour
        readable = {name: cond[k] for k, name in names.items() if k in cond}  # in condition order
        rows.append((str(c['id']), int(c['t']), caught_at, weekday, hour, str(c['fish']),
                     json.dumps(readable, ensure_ascii=False), json.dumps(cond, ensure_ascii=False),
                     int(note), hm))
    with conn:  # one transaction: the file never holds half a save
        conn.execute('DELETE FROM catches')
        conn.executemany('INSERT INTO catches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
        conn.execute('DELETE FROM settings')
        conn.executemany('INSERT INTO settings VALUES (?, ?)',
                         [(k, json.dumps(state[k], ensure_ascii=False)) for k in SETTINGS if k in state])


# ---------- public website ----------

def public_data(state):
    """The part of the log the public page needs (no ids, current picks or other settings)."""
    keep = ('t', 'fish', 'cond', 'note', 'hm')
    return {
        'version': state.get('version'),
        'categories': state['categories'],
        'catches': [{k: c[k] for k in keep if k in c} for c in state['catches']],
    }


def read_data_json():
    try:
        data = json.loads(DATA_JSON.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    data.pop('updatedAt', None)
    return data


def write_data_json():
    """Write data.json from the database. Returns the catch count, or None if it was already current."""
    with db_lock:
        conn = connect()
        try:
            state = load_state(conn)
        finally:
            conn.close()
    if not state:
        return None
    data = public_data(state)
    if read_data_json() == data:
        return None

    def dump(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    # One catch per line keeps the git history readable.
    text = '{"version":%s,"updatedAt":%d,"categories":%s,"catches":[\n%s\n]}\n' % (
        dump(data['version']), int(time.time() * 1000), dump(data['categories']),
        ',\n'.join(dump(c) for c in data['catches']))
    DATA_JSON.write_text(text, encoding='utf-8')
    return len(data['catches'])


def git(*args, check=True):
    result = subprocess.run(
        ['git', *args], cwd=HERE, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=180, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'},
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if check and result.returncode != 0:
        # git's first "fatal:"/"error:" line says what went wrong (no internet, login expired, ...).
        lines = [ln.strip() for ln in (result.stderr or result.stdout).splitlines() if ln.strip()]
        reason = next((ln.split(':', 1)[1].strip() for ln in lines if ln.startswith(('fatal:', 'error:'))),
                      lines[-1] if lines else 'unknown error')
        raise RuntimeError(f'git {args[0]}: {reason}')
    return result


def pages_url():
    """https://OWNER.github.io/REPO/ worked out from the origin remote."""
    try:
        remote = git('remote', 'get-url', 'origin').stdout.strip()
    except Exception:
        return None
    m = re.search(r'github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$', remote)
    return f'https://{m[1].lower()}.github.io/{m[2]}/' if m else None


class Publisher:
    """Uploads data.json to GitHub a while after the last change, and catches up at start."""

    def __init__(self, enabled):
        self.enabled = enabled
        self.url = pages_url() if enabled else None
        self.lock = threading.Lock()
        self.timer = None
        self.due = None      # when the next upload runs (epoch seconds)
        self.last = None     # when the website last got new data
        self.error = None
        self.running = False

    def status(self):
        def ms(t):
            return int(t * 1000) if t else None
        return {'enabled': self.enabled, 'url': self.url, 'due': ms(self.due), 'last': ms(self.last),
                'error': self.error, 'running': self.running}

    def schedule(self, delay=None):
        if not self.enabled:
            return
        if delay is None:
            delay = PUBLISH_DELAY
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(delay, self.run)
            self.timer.daemon = True
            self.timer.start()
            self.due = time.time() + delay

    def run(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.timer = None
            self.due = None
        try:
            self.upload()
            self.error = None
        except Exception as e:  # no internet, GitHub login expired, ...
            self.error = str(e) or e.__class__.__name__
            print(f'[{time.strftime("%H:%M")}] Website update failed: {self.error}')
        finally:
            with self.lock:
                self.running = False
        if self.error:
            self.schedule()  # try again later

    def upload(self):
        count = write_data_json()
        if count is not None:
            git('add', 'data.json')
            if git('diff', '--cached', '--quiet', '--', 'data.json', check=False).returncode == 1:
                git('commit', '-m', f'Update fishing data ({count} catches)', '--', 'data.json')
        # Also covers an earlier commit whose push failed.
        if git('rev-list', '--count', '@{u}..HEAD').stdout.strip() != '0':
            git('push')
            self.last = time.time()
            print(f'[{time.strftime("%H:%M")}] Website updated: {self.url}')


publisher = Publisher(False)


# ---------- web server ----------

class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        '.html': 'text/html; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def api(self):
        path = self.path.split('?')[0]
        return path if path in ('/api/state', '/api/publish') else None

    def from_this_pc(self):
        # Only answer pages opened as localhost, not some other site pointing a name at us.
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host in ('localhost', '127.0.0.1'):
            return True
        self.send_error(403)
        return False

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Always serve the latest page after an update.
        if not self.api():
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_GET(self):
        api = self.api()
        if not api:
            return super().do_GET()
        if not self.from_this_pc():
            return
        if api == '/api/publish':
            return self.send_json(200, publisher.status())
        with db_lock:
            conn = connect()
            try:
                state = load_state(conn)
            finally:
                conn.close()
        self.send_json(200, state)  # null until the first save

    def do_PUT(self):
        if self.api() != '/api/state':
            return self.send_error(404)
        if not self.from_this_pc():
            return
        try:
            state = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            with db_lock:
                conn = connect()
                try:
                    save_state(conn, state)
                finally:
                    conn.close()
        except (ValueError, KeyError, TypeError) as e:
            return self.send_json(400, {'error': str(e)})
        if publisher.enabled and public_data(state) != read_data_json():
            publisher.schedule()  # restarts the 10-minute wait
        self.send_json(200, {'ok': True, 'catches': len(state['catches']), 'publish': publisher.status()})

    def do_POST(self):
        # "Update website now". A JSON body means other websites can't trigger it without CORS.
        if self.api() != '/api/publish':
            return self.send_error(404)
        if not self.from_this_pc():
            return
        if not (self.headers.get('Content-Type') or '').startswith('application/json'):
            return self.send_error(415)
        publisher.schedule(delay=0)
        self.send_json(200, publisher.status())

    def log_message(self, fmt, *args):
        pass  # keep the console window quiet


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two servers share a port; we want "already running" instead.
    allow_reuse_address = sys.platform != 'win32'


def main():
    global publisher
    args = sys.argv[1:]
    port = int(args[args.index('--port') + 1]) if '--port' in args else 8765
    url = f'http://localhost:{port}/'
    open_browser = '--no-browser' not in args

    connect().close()  # create the database file on first run
    try:
        server = Server(('127.0.0.1', port), Handler)
    except OSError:
        print(f'Port {port} is already in use - the fishing log is probably running already.')
        if open_browser:
            webbrowser.open(url)
        return

    publisher = Publisher((HERE / '.git').exists() and shutil.which('git') is not None
                          and '--no-publish' not in args)
    print(f'Fishing log:  {url}')
    print(f'Saving to:    {DB_PATH}')
    if publisher.enabled:
        print(f'Website:      {publisher.url or "(GitHub)"}  - updates 10 minutes after your last change')
        publisher.schedule(delay=5)  # upload anything left over from last time
    print('Keep this window open while you play. Close it (or press Ctrl+C) to stop.')
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

"""Isolated v2 candidate. No production protocol, shell, SSH, or self-update."""
import hashlib
import hmac
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import urllib.request

REPO = 'kongsonren/aisaleos-handoff-poc'
API_BASE = 'https://api.github.com/repos/' + REPO

def positive(value):
    return type(value) is int and value > 0

def sync_directory(path):
    # Windows has no portable directory fsync; Linux durability is gated separately.
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
FIELDS = set('protocol repository issue_id issue_number issuer_id key_id task_id run_id state execution_authorized scope executor action filename content issued_at expires_at nonce executor_sha256'.split())

class Hold(Exception):
    pass

def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

def digest(payload, key):
    return hmac.new(key, b'mozi-v2-auth\0' + canonical(payload), hashlib.sha256).hexdigest()

def parse(body):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise Hold('duplicate JSON key')
            result[k] = v
        return result
    try:
        return json.loads(body, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise Hold('invalid JSON') from exc

class Daemon:
    def __init__(self, root, keys, *, expected_sha256=None, result_author_id=None):
        if sys.version_info < (3, 12):
            raise Hold('Python 3.12+ required')
        self.code = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
        if expected_sha256 is not None and expected_sha256 != self.code:
            raise Hold('executor measurement mismatch')
        if result_author_id is not None and not positive(result_author_id):
            raise Hold('invalid RESULT principal')
        self.result_author_id = result_author_id
        self.audit_failed = False
        # root must be a dedicated, trusted, private directory; never a legacy state directory.
        self.root = pathlib.Path(root).absolute()
        if self.root.is_symlink() or self.root.is_junction():
            raise Hold('unsafe state root')
        if not self.root.parent.is_dir():
            raise Hold('state parent must exist')
        self.root.mkdir(mode=0o700, exist_ok=True)
        sync_directory(self.root.parent)
        for name in ('ledger.sqlite', 'ledger.sqlite-wal', 'ledger.sqlite-shm'):
            p = self.root / name
            if p.is_symlink() or p.is_junction():
                raise Hold('unsafe ledger')
        self.keys = keys  # key_id -> (trusted numeric GitHub author id, secret bytes)
        self.db = sqlite3.connect(self.root / 'ledger.sqlite', timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs(task TEXT PRIMARY KEY, run TEXT UNIQUE, nonce TEXT UNIQUE, issue INTEGER UNIQUE, fingerprint TEXT, status TEXT, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL, event_hash TEXT NOT NULL)')
        self.db.commit()
        sync_directory(self.root)

    def audit(self, issue, reason, execution_state):
        if self.audit_failed:
            raise Hold('audit unavailable; execution blocked')
        # Never persist input text, exception messages, signatures, tokens or keys.
        try:
            raw = canonical(issue)
        except (ValueError, TypeError, RecursionError):
            raw = b'unserializable-input'
        source = issue if type(issue) is dict else {}
        event = canonical(dict(time_ns=time.time_ns(), repository=REPO,
            api_endpoint=API_BASE, issue_number=source.get('number') if positive(source.get('number')) else None,
            input_sha256=hashlib.sha256(raw).hexdigest(), reason=reason, execution_state=execution_state)).decode()
        try:
            with self.db:
                self.db.execute('INSERT INTO audit(event,event_hash) VALUES(?,?)', (event,hashlib.sha256(event.encode()).hexdigest()))
        except Exception:
            self.audit_failed = True
            raise Hold('audit unavailable; execution blocked') from None

    def validate(self, issue, current):
        if type(issue) is not dict or not positive(issue.get('id')) or not positive(issue.get('number')) or type(issue.get('user')) is not dict or not positive(issue['user'].get('id')) or type(issue.get('title')) is not str:
            raise Hold('malformed metadata')
        if issue.get('number') == 20 or 'pull_request' in issue or issue.get('state') != 'open':
            raise Hold('protected or non-task issue')
        p = parse(issue.get('body'))
        if not isinstance(p, dict) or set(p) != FIELDS | {'auth_digest'}:
            raise Hold('schema/legacy rejected')
        signature = p.pop('auth_digest')
        if p['execution_authorized'] is not True or p['state'] != 'READY':
            raise Hold('authorization/HOLD')
        for k in ('issue_id', 'issue_number', 'issuer_id', 'issued_at', 'expires_at'):
            if type(p[k]) is not int or p[k] <= 0:
                raise Hold('integer required')
        for k in FIELDS - {'issue_id', 'issue_number', 'issuer_id', 'issued_at', 'expires_at', 'execution_authorized'}:
            if type(p[k]) is not str:
                raise Hold('string required')
        trusted = self.keys.get(p['key_id'])
        if not trusted or len(trusted[1]) < 32 or trusted[0] != p['issuer_id'] or issue.get('user', {}).get('id') != trusted[0]:
            raise Hold('untrusted principal/key')
        if p['repository'] != REPO or p['issue_id'] != issue.get('id') or p['issue_number'] != issue.get('number'):
            raise Hold('source binding')
        if p['protocol'] != 'mozi-v2-auth' or p['scope'] != 'simulation-only' or p['executor'] != 'isolated-file-v2' or p['action'] != 'write_read_hash' or p['filename'] != 'test.txt' or p['executor_sha256'] != self.code:
            raise Hold('execution policy')
        if not re.fullmatch(r'SIM-[A-Za-z0-9-]{1,64}', p['task_id']) or not re.fullmatch(r'SIM-[A-Za-z0-9-]{1,64}', p['run_id']) or not re.fullmatch(r'[a-f0-9]{32,64}', p['nonce']):
            raise Hold('simulation identity')
        if issue.get('title') != '[MOZI-V2-SIM] ' + p['task_id'] or len(p['content'].encode()) > 4096:
            raise Hold('title/content policy')
        if not 0 < p['expires_at'] - p['issued_at'] <= 300 or not p['issued_at'] <= current < p['expires_at']:
            raise Hold('expired/future authorization')
        if type(signature) is not str or not hmac.compare_digest(digest(p, trusted[1]), signature):
            raise Hold('signature')
        return p, hashlib.sha256(canonical(p)).hexdigest()

    def consume(self, issue, current=None):
        execution_state = 'NOT_STARTED'
        try:
            p, fingerprint = self.validate(issue, int(time.time()) if current is None else current)
            self.audit(issue, 'AUTHORIZED', execution_state)
            # Atomic reservation is committed BEFORE any file effect. Ambiguous claims never rerun.
            try:
                with self.db:
                    self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (p['task_id'], p['run_id'], p['nonce'], p['issue_id'], fingerprint, 'CLAIMED', None))
            except sqlite3.IntegrityError:
                row = self.db.execute('SELECT fingerprint,status,result FROM jobs WHERE task=?', (p['task_id'],)).fetchone()
                if row and row[0] == fingerprint and row[1] in ('DONE', 'POST_ATTEMPT', 'VERIFIED'):
                    return {'status': 'DUPLICATE', 'result': json.loads(row[2])}
                raise Hold('replay/conflict/ambiguous claim')
            started = time.time()
            execution_state = 'CLAIMED'
            folder = self.root / hashlib.sha256(p['task_id'].encode()).hexdigest()
            folder.mkdir(mode=0o700)  # existing directory fails closed
            sync_directory(self.root)
            target = folder / 'test.txt'
            content = p['content'].encode()
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(target, flags, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            sync_directory(folder)
            actual = target.read_bytes()
            if actual != content:
                raise Hold('readback mismatch')
            result = dict(type='RESULT', status='PASS', scope='simulation-only', task_id=p['task_id'], run_id=p['run_id'], issue_id=p['issue_id'], issue_number=p['issue_number'], payload_sha256=fingerprint, executor_sha256=self.code, path=str(target), bytes=len(actual), sha256=hashlib.sha256(actual).hexdigest(), started_at=started, completed_at=time.time(), pid=os.getpid())
            with self.db:
                self.db.execute('UPDATE jobs SET status=?,result=? WHERE task=?', ('DONE', canonical(result).decode(), p['task_id']))
            return result
        except Exception as exc:
            reason = str(exc) if isinstance(exc, Hold) else 'task processing failure'
            self.audit(issue, reason if isinstance(exc, Hold) else type(exc).__name__, execution_state)
            return {'status': 'HOLD_PENDING_KR', 'reason': reason}

    def publish(self, result, api):
        """Durable at-most-once POST; ambiguity is HOLD, never blind retry."""
        if result.get('status') == 'DUPLICATE':
            result = result['result']
        if result.get('status') != 'PASS':
            return result
        if not positive(self.result_author_id):
            raise Hold('RESULT principal not configured')
        task = result['task_id']
        row = self.db.execute('SELECT status,result FROM jobs WHERE task=?', (task,)).fetchone()
        if not row or json.loads(row[1]) != result:
            raise Hold('result binding')
        if row[0] == 'VERIFIED':
            return {'status': 'ALREADY_VERIFIED'}
        if row[0] != 'DONE':
            return {'status': 'HOLD_PENDING_KR', 'reason': 'POST ambiguous'}
        with self.db:
            changed = self.db.execute('UPDATE jobs SET status=? WHERE task=? AND status=?', ('POST_ATTEMPT', task, 'DONE')).rowcount
        if changed != 1:
            raise Hold('concurrent POST')
        body = '[MOZI-V2-SIM-RESULT]\n' + canonical(result).decode()
        posted = api('POST', '/issues/' + str(result['issue_number']) + '/comments', {'body': body})
        if type(posted) is not dict or not positive(posted.get('id')):
            raise Hold('RESULT POST metadata')
        comment_id = posted['id']
        readback = api('GET', '/issues/comments/' + str(posted['id']))
        def bound(comment):
            return (type(comment) is dict and positive(comment.get('id')) and comment['id'] == comment_id
                and type(comment.get('user')) is dict and positive(comment['user'].get('id'))
                and comment['user']['id'] == self.result_author_id
                and comment.get('issue_url') == API_BASE + '/issues/' + str(result['issue_number'])
                and comment.get('url') == API_BASE + '/issues/comments/' + str(comment_id)
                and comment.get('body') == body)
        if not bound(posted) or not bound(readback):
            raise Hold('RESULT readback')
        with self.db:
            self.db.execute('UPDATE jobs SET status=? WHERE task=?', ('VERIFIED', task))
        return {'status': 'RESULT_VERIFIED', 'comment_id': posted['id']}

def scan(daemon, api):
    for page in range(1, 101):
        issues = api('GET', '/issues?state=open&per_page=100&page=' + str(page))
        if type(issues) is not list:
            raise Hold('global API list failure')
        for issue in issues:
            try:
                if type(issue) is not dict or not positive(issue.get('number')) or type(issue.get('title')) is not str:
                    raise Hold('malformed scan metadata')
                if issue['number'] == 20 or not issue['title'].startswith('[MOZI-V2-SIM] '):
                    continue
                fresh = api('GET', '/issues/' + str(issue['number']))
                if type(fresh) is not dict or fresh.get('number') != issue['number']:
                    raise Hold('refresh source mismatch')
                result = daemon.consume(fresh)
                print(json.dumps(daemon.publish(result, api)), flush=True)
            except Exception:
                daemon.audit(issue, 'SCAN_TASK_FAILURE', 'UNKNOWN')
                print(json.dumps({'status':'HOLD_PENDING_KR','reason':'scan task failure'}), flush=True)
        if len(issues) < 100:
            return
    raise Hold('pagination limit')

class GitHubAPI:
    """Injected only after KR_GATE; token never stored in ledger/results."""
    def __init__(self, token):
        if not token:
            raise Hold('missing GitHub credential')
        self.token = token

    def __call__(self, method, path, data=None):
        if method not in ('GET', 'POST') or not re.fullmatch(r'/issues(?:/[1-9][0-9]*(?:/comments)?|/comments/[1-9][0-9]*|\?state=open&per_page=100&page=[1-9][0-9]*)', path):
            raise Hold('API policy')
        if method == 'POST' and not re.fullmatch(r'/issues/[0-9]+/comments', path):
            raise Hold('write policy')
        if re.match(r'/issues/20(?:/|$|\?)', path):
            raise Hold('protected issue')
        req = urllib.request.Request('https://api.github.com/repos/' + REPO + path,
            method=method, data=None if data is None else canonical(data),
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'mozi-v2-isolated-candidate'})
        # Redirects are rejected so bearer credentials never follow another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise Hold('API redirect rejected')
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
            if response.geturl() != API_BASE + path:
                raise Hold('untrusted API endpoint')
            return json.load(response)

# Deliberately no executable network entrypoint in this non-deployment candidate.
# Cloud lifecycle, secret provisioning and enabling live API writes require KR_GATE.

"""Server-only encrypted Daum settings and authenticated, read-only connection probes.

App passwords are accepted only by authenticated HTTPS account registration,
never returned by an API or logged. The local
fallback key protects file contents, not a fully compromised operating system.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import hmac
import json
import ipaddress
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/mail', tags=['mail'])
logger = logging.getLogger('content_maker.mail')
COOKIE = 'content_maker_mail_session'
SESSION_SECONDS = 30 * 60
RESULT_FRESH_SECONDS = 10 * 60
_sessions: dict[str, dict] = {}
_attempts: dict[str, list[float]] = {}
_state_lock = threading.Lock()
_probe_lock = threading.Lock()


class MailConfigurationError(Exception):
    pass


def mail_dir() -> Path:
    return Path(os.environ.get('CONTENT_MAKER_MAIL_DIR', ROOT / '.local' / 'mail'))


def _private_directory() -> Path:
    folder = mail_dir()
    if folder.is_symlink():
        raise MailConfigurationError('invalid_storage')
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    return folder


@contextmanager
def _vault_file_lock():
    """Serialize CLI/server read-check-write transactions across processes."""
    path = _private_directory() / 'vault.lock'
    if path.is_symlink(): raise MailConfigurationError('invalid_storage')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    os.chmod(path, 0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(descriptor).st_size == 0: os.write(descriptor,b'0')
            os.lseek(descriptor,0,os.SEEK_SET)
            msvcrt.locking(descriptor,msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(descriptor,fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                os.lseek(descriptor,0,os.SEEK_SET)
                msvcrt.locking(descriptor,msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(descriptor,fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _write_private(path: Path, contents: bytes):
    if path.is_symlink():
        raise MailConfigurationError('invalid_storage')
    temp = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
        path.chmod(0o600)
    finally:
        if temp.exists(): temp.unlink()


def _cipher(create=False) -> Fernet:
    try:
        external = os.environ.get('CONTENT_MAKER_ENCRYPTION_KEY')
        if external:
            return Fernet(external.encode('ascii'))
        # Managed platforms generate a high-entropy opaque secret rather than a
        # Fernet-format key. Never use a human password as this master secret.
        generated = os.environ.get('CONTENT_MAKER_ENCRYPTION_SECRET')
        if generated:
            if not 32 <= len(generated) <= 4096: raise ValueError('invalid_master_secret')
            return Fernet(base64.urlsafe_b64encode(hashlib.sha256(generated.encode('utf-8')).digest()))
        key_path = mail_dir() / 'key'
        if key_path.is_symlink(): raise MailConfigurationError('invalid_storage')
        if not key_path.exists():
            if not create: raise MailConfigurationError('missing_key')
            _private_directory()
            _write_private(key_path, Fernet.generate_key())
        key_path.chmod(0o600)
        return Fernet(key_path.read_bytes())
    except (ValueError, UnicodeError, OSError) as exc:
        raise MailConfigurationError('invalid_key') from None


def load_configuration() -> dict | None:
    path = mail_dir() / 'vault.enc'
    if not path.exists(): return None
    try:
        if path.is_symlink(): raise MailConfigurationError('invalid_storage')
        if path.stat().st_size > 65536: raise MailConfigurationError('invalid_storage')
        path.chmod(0o600)
        state = json.loads(_cipher().decrypt(path.read_bytes()))
        if not isinstance(state, dict) or state.get('version') != 1 or state.get('provider') != 'daum':
            raise MailConfigurationError('invalid_storage')
        for key in ('revision', 'username', 'appPassword', 'adminHash', 'folders'):
            if key not in state: raise MailConfigurationError('invalid_storage')
        return state
    except (InvalidToken, ValueError, OSError, KeyError, TypeError):
        raise MailConfigurationError('unreadable_storage') from None


def _save_configuration(state: dict):
    folder = _private_directory()
    payload = json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()
    _write_private(folder / 'vault.enc', _cipher(create=True).encrypt(payload))


def password_hash(password: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return {'salt': base64.b64encode(salt).decode(), 'value': base64.b64encode(value).decode()}


def _password_matches(password: str, record: dict) -> bool:
    try:
        value = password_hash(password, base64.b64decode(record['salt'], validate=True))['value']
        return hmac.compare_digest(value, record['value'])
    except (ValueError, KeyError, TypeError):
        return False


def _validate_mail_account(username: str, app_password: str, folders: list[str]) -> None:
    if not isinstance(username, str) or not username.strip() or len(username) > 254 or any(c in username for c in '\r\n\x00'):
        raise ValueError('접속용 아이디를 확인하세요.')
    if not isinstance(app_password, str) or not app_password or len(app_password) > 1024 or any(c in app_password for c in '\r\n\x00'):
        raise ValueError('앱 비밀번호를 확인하세요.')
    if not isinstance(folders, list) or not 1 <= len(folders) <= 10 or any(not isinstance(f, str) or not f.strip() or len(f)>200 or any(c in f for c in '\r\n\x00') for f in folders):
        raise ValueError('읽기 시험할 폴더 이름을 1~10개 지정하세요.')


def configure_account(username: str, app_password: str, admin_password: str, folders: list[str]) -> None:
    """Interactive CLI configuration; HTTPS account save preserves the admin hash."""
    _validate_mail_account(username, app_password, folders)
    if not isinstance(admin_password, str) or len(admin_password) < 12 or len(admin_password) > 1024:
        raise ValueError('관리자 비밀번호는 12자 이상이어야 합니다.')
    state = {'version':1, 'revision':secrets.token_hex(24), 'provider':'daum',
             'username':username.strip(), 'appPassword':app_password,
             'folders':list(dict.fromkeys(f.strip() for f in folders)),
             'adminHash':password_hash(admin_password), 'lastTest':None}
    with _state_lock, _vault_file_lock():
        _save_configuration(state)
        _sessions.clear()
        _attempts.clear()
    logger.info('mail_configuration_saved')


def _configuration_or_error() -> dict | None:
    try: return load_configuration()
    except MailConfigurationError:
        raise HTTPException(503, '메일 암호화 설정을 읽지 못했습니다. 서버에서 설정과 암호화 키를 확인하세요.') from None


def _transport_guard(request: Request, *, mutation=False):
    # Local HTTP is allowed only with a literal loopback host. A DNS name must use
    # HTTPS; deployment must explicitly configure trusted proxy/host middleware.
    host = request.url.hostname or ''
    loopback_hosts = {'127.0.0.1', 'localhost', '::1'}
    trusted_hosts = loopback_hosts | {h.strip().casefold() for h in os.environ.get('CONTENT_MAKER_TRUSTED_HOSTS', '').split(',') if h.strip()}
    if host.casefold() not in trusted_hosts:
        raise HTTPException(403, '허용된 서버 주소에서 메일 설정을 열어 주세요.')
    if request.url.scheme == 'http':
        try:
            peer = ipaddress.ip_address(request.client.host) if request.client else None
            local_client = bool(peer and peer.is_loopback)
            if peer and not local_client:
                # Explicit addresses/CIDRs support a loopback-bound Docker port
                # forwarded by its bridge gateway. Private networks are NEVER
                # trusted automatically, and forwarded headers are not read.
                for configured in os.environ.get('CONTENT_MAKER_TRUSTED_HTTP_PEERS', '').split(','):
                    if not configured.strip(): continue
                    try:
                        network = ipaddress.ip_network(configured.strip(), strict=False)
                    except ValueError:
                        continue
                    if peer in network:
                        local_client = True
                        break
        except ValueError:
            local_client = False
        if host not in loopback_hosts or not local_client:
            raise HTTPException(403, '메일 설정은 로컬 서버 또는 HTTPS에서만 사용할 수 있습니다.')
    elif request.url.scheme != 'https':
        raise HTTPException(403, '메일 설정은 로컬 서버 또는 HTTPS에서만 사용할 수 있습니다.')
    if mutation:
        origin = request.headers.get('origin')
        try:
            expected = urlsplit(str(request.base_url))
            actual = urlsplit(origin or '')
        except ValueError:
            raise HTTPException(403, '이 서버의 메일 설정 화면에서 진행하세요.') from None
        if not origin or actual.scheme != expected.scheme or actual.netloc != expected.netloc or actual.path not in ('', '/') or actual.query or actual.fragment:
            raise HTTPException(403, '이 서버의 메일 설정 화면에서 진행하세요.')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '교차 사이트 메일 설정 요청은 허용하지 않습니다.')


def _session(request: Request) -> tuple[dict, dict]:
    _transport_guard(request)
    token = request.cookies.get(COOKIE, '')
    key = hashlib.sha256(token.encode()).hexdigest() if token else ''
    with _state_lock:
        session = _sessions.get(key)
        if not session or session['expires'] <= time.monotonic():
            _sessions.pop(key, None)
            raise HTTPException(401, '메일 관리자 로그인이 필요합니다.')
        configuration = _configuration_or_error()
        if not configuration or session['revision'] != configuration['revision']:
            _sessions.pop(key, None)
            raise HTTPException(401, '메일 설정이 변경됐습니다. 다시 로그인하세요.')
    return session, configuration


def _masked_username(username: str) -> str:
    if not username: return '미설정'
    if '@' in username:
        local, domain = username.rsplit('@', 1)
        return local[:1] + '***@' + domain
    return username[:1] + '***'


def _provider_snapshot() -> tuple[bool, dict, str | None]:
    try:
        from app.mail_connector import load_provider, DEFAULT_CONFIG
        server = load_provider('daum')
        path = Path(DEFAULT_CONFIG)
        if path.stat().st_size > 65536: raise ValueError('invalid_config')
        fingerprint = hashlib.sha256(path.read_bytes() + json.dumps(server, sort_keys=True).encode()).hexdigest()
        return True, {'host':server['host'], 'port':server['port'], 'ssl':True}, fingerprint
    except Exception:
        # Includes malformed YAML, missing/unreadable files, and invalid endpoints.
        return False, {'host':'imap.daum.net', 'port':993, 'ssl':True}, None


def public_status(configuration: dict) -> dict:
    provider_valid, visible_server, fingerprint = _provider_snapshot()
    last = configuration.get('lastTest')
    age = None
    if last:
        try:
            timestamp = datetime.fromisoformat(last['checkedAt'].replace('Z','+00:00'))
            if timestamp.tzinfo is None: raise ValueError()
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        except (ValueError, TypeError, KeyError): pass
    fresh = bool(age is not None and 0 <= age < RESULT_FRESH_SECONDS)
    same_settings = bool(provider_valid and last and last.get('providerFingerprint') == fingerprint and last.get('configurationRevision') == configuration['revision'])
    configured = bool(configuration.get('username') and configuration.get('appPassword'))
    connected = bool(configured and last and last.get('ok') is True and last.get('status') == 'connected' and fresh and same_settings)
    safe_last = {key:value for key,value in (last or {}).items() if key not in ('configurationRevision','providerFingerprint')} if last else None
    return {'enabled':True, 'configured':configured, 'provider':'daum',
            'usernameMasked':_masked_username(configuration['username']), 'folders':configuration['folders'],
            'server':visible_server, 'lastTest':safe_last, 'connected':connected,
            'status':'account_required' if not configured else 'configuration_error' if not provider_valid else 'connected' if connected else 'test_failed' if last and fresh and same_settings and not last.get('ok') else 'test_required',
            'testFresh':bool(fresh and same_settings), 'statusExpiresSeconds':RESULT_FRESH_SECONDS,
            'notice':'메일 서버 설정을 확인하세요.' if not provider_valid else '접속 시험만 수행합니다. 메일 본문 수집·폴링·발송은 아직 실행하지 않습니다.'}


def _bootstrap_token() -> str | None:
    value = os.environ.get('CONTENT_MAKER_SETUP_TOKEN', '')
    return value if 32 <= len(value) <= 512 else None


def _https_secret_guard(request: Request):
    _transport_guard(request, mutation=True)
    if request.url.scheme != 'https':
        raise HTTPException(403, '비밀번호 등록은 허용된 HTTPS 서버에서만 가능합니다.')


async def _strict_secret_json(request: Request, keys: set[str], max_bytes=8192) -> dict:
    if request.headers.get('content-type','').split(';',1)[0].strip() != 'application/json':
        raise HTTPException(415, 'JSON 요청만 허용합니다.')
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > max_bytes: raise HTTPException(413, '요청이 너무 큽니다.')
    try:
        value = json.loads(buffer)
        if not isinstance(value, dict) or set(value) != keys: raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(422, '입력 형식을 확인하세요. 비밀번호는 응답에 표시하지 않습니다.') from None


def _setup_attempt(request: Request):
    key = 'setup:' + (request.client.host if request.client else 'unknown')
    now = time.monotonic()
    with _state_lock:
        attempts = [stamp for stamp in _attempts.get(key, []) if now-stamp < 600]
        _attempts[key] = attempts
        if len(attempts) >= 5:
            raise HTTPException(429, '초기 설정 시도가 많습니다. 10분 뒤 다시 시도하세요.')
        attempts.append(now)


@router.get('/setup-status')
def setup_status(request: Request):
    _transport_guard(request)
    # No private account metadata and no ciphertext decryption before login.
    initialized = (mail_dir() / 'vault.enc').exists()
    return {'initialized':initialized, 'setupAvailable':bool(not initialized and _bootstrap_token())}


@router.post('/initialize')
async def initialize(request: Request):
    _https_secret_guard(request)
    _setup_attempt(request)
    value = await _strict_secret_json(request, {'setupToken','adminPassword','confirmPassword'})
    configured_token = _bootstrap_token()
    supplied = value.get('setupToken')
    if not configured_token:
        raise HTTPException(403, '초기 설정은 서버의 안전한 설정 코드가 준비된 경우에만 가능합니다.')
    if not isinstance(supplied,str) or not 1 <= len(supplied) <= 512 or not hmac.compare_digest(supplied.encode(),configured_token.encode()):
        logger.info('mail_initialization_denied')
        raise HTTPException(403, '초기 설정 코드를 확인하세요.')
    password, confirmation = value.get('adminPassword'), value.get('confirmPassword')
    if not isinstance(password,str) or not 12 <= len(password) <= 1024 or not isinstance(confirmation,str) or not hmac.compare_digest(password.encode(),confirmation.encode()):
        raise HTTPException(422, '관리자 비밀번호는 12자 이상이며 확인 입력과 같아야 합니다.')
    if hmac.compare_digest(password.encode(),configured_token.encode()):
        raise HTTPException(422, '관리자 비밀번호는 초기 설정 코드와 다르게 정하세요.')
    record = await run_in_threadpool(password_hash,password)
    state = {'version':1,'revision':secrets.token_hex(24),'provider':'daum',
             'username':'','appPassword':'','folders':[], 'adminHash':record,'lastTest':None}
    try:
        with _state_lock, _vault_file_lock():
            if (mail_dir() / 'vault.enc').exists():
                raise HTTPException(409, '관리자 초기 설정이 이미 완료됐습니다. 로그인하세요.')
            _save_configuration(state)
            _sessions.clear()
    except (MailConfigurationError,OSError):
        raise HTTPException(503, '초기 설정을 안전하게 저장하지 못했습니다. 서버 설정을 확인하세요.') from None
    logger.info('mail_administrator_initialized')
    response = JSONResponse({'ok':True,'initialized':True})
    response.headers['Cache-Control']='no-store'
    return response


@router.post('/account')
async def save_account(request: Request):
    _https_secret_guard(request)
    _, configuration = _session(request)
    value = await _strict_secret_json(request, {'username','appPassword','folders'})
    try:
        _validate_mail_account(value.get('username'),value.get('appPassword'),value.get('folders'))
    except ValueError:
        raise HTTPException(422, '접속용 아이디·앱 비밀번호·지정 폴더를 확인하세요.') from None
    if await run_in_threadpool(_password_matches,value['appPassword'],configuration['adminHash']):
        raise HTTPException(422, '메일 앱 비밀번호와 관리자 비밀번호는 다르게 설정하세요.')
    state = {**configuration,'revision':secrets.token_hex(24),'username':value['username'].strip(),
             'appPassword':value['appPassword'],'folders':list(dict.fromkeys(f.strip() for f in value['folders'])),
             'lastTest':None}
    try:
        with _state_lock, _vault_file_lock():
            latest = _configuration_or_error()
            if not latest or latest['revision'] != configuration['revision']:
                raise HTTPException(409, '다른 곳에서 설정이 변경됐습니다. 다시 로그인하세요.')
            _save_configuration(state)
            _sessions.clear()
    except (MailConfigurationError,OSError):
        raise HTTPException(503, '계정 설정을 안전하게 저장하지 못했습니다. 서버 설정을 확인하세요.') from None
    logger.info('mail_account_saved_https')
    response = JSONResponse({'ok':True,'requireRelogin':True})
    response.delete_cookie(COOKIE,path='/api/mail',httponly=True,samesite='strict',secure=True)
    response.headers['Cache-Control']='no-store'
    return response


@router.post('/login')
async def login(request: Request):
    _transport_guard(request, mutation=True)
    if request.headers.get('content-type','').split(';',1)[0].strip() != 'application/json':
        raise HTTPException(415, 'JSON 요청만 허용합니다.')
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer)>4096: raise HTTPException(413, '요청이 너무 큽니다.')
    try:
        value = json.loads(buffer)
        if not isinstance(value,dict) or set(value) != {'password'} or not isinstance(value['password'],str) or not 1<=len(value['password'])<=1024:
            raise ValueError()
        password = value['password']
    except (ValueError, UnicodeError):
        raise HTTPException(422, '관리자 비밀번호 입력 형식을 확인하세요.') from None
    client = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    with _state_lock:
        attempts = [stamp for stamp in _attempts.get(client,[]) if now-stamp<600]
        _attempts[client] = attempts
        if len(attempts)>=5:
            raise HTTPException(429, '로그인 시도가 많습니다. 10분 뒤 다시 시도하세요.')
        attempts.append(now)
        configuration = _configuration_or_error()
    if not configuration:
        raise HTTPException(503, '서버에서 npm run mail:setup으로 메일 설정을 먼저 준비하세요.')
    matches = await run_in_threadpool(_password_matches, password, configuration['adminHash'])
    if not matches:
        logger.info('mail_login_failed')
        raise HTTPException(401, '관리자 비밀번호를 확인하세요.')
    token = secrets.token_urlsafe(32)
    with _state_lock:
        latest = _configuration_or_error()
        if not latest or latest['revision'] != configuration['revision']:
            raise HTTPException(409, '메일 설정이 변경됐습니다. 다시 로그인하세요.')
        _attempts.pop(client,None)
        _sessions[hashlib.sha256(token.encode()).hexdigest()] = {'revision':configuration['revision'], 'expires':time.monotonic()+SESSION_SECONDS}
    response = JSONResponse({'ok':True, 'expiresIn':SESSION_SECONDS})
    response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,samesite='strict',secure=request.url.scheme=='https',path='/api/mail')
    response.headers['Cache-Control']='no-store'
    logger.info('mail_login_succeeded')
    return response


@router.post('/logout')
def logout(request: Request):
    _transport_guard(request, mutation=True)
    token = request.cookies.get(COOKIE,'')
    with _state_lock: _sessions.pop(hashlib.sha256(token.encode()).hexdigest(),None)
    response = JSONResponse({'ok':True})
    response.delete_cookie(COOKIE,path='/api/mail',httponly=True,samesite='strict',secure=request.url.scheme=='https')
    response.headers['Cache-Control']='no-store'
    return response


@router.get('/status')
def status(request: Request):
    _, configuration = _session(request)
    return public_status(configuration)


@router.post('/test')
async def test_connection(request: Request):
    _transport_guard(request, mutation=True)
    _, configuration = _session(request)
    if not configuration.get('username') or not configuration.get('appPassword'):
        raise HTTPException(409, '다음 메일 계정을 먼저 등록하세요.')
    if request.headers.get('content-type','').split(';',1)[0].strip() != 'application/json':
        raise HTTPException(415, 'JSON 요청만 허용합니다.')
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer)>1024: raise HTTPException(413, '요청이 너무 큽니다.')
    try:
        value = json.loads(buffer)
        if not isinstance(value,dict) or value: raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(422, '접속 시험에는 빈 JSON 객체만 허용합니다. 비밀번호를 보내지 마세요.') from None
    provider_valid, _, provider_fingerprint = _provider_snapshot()
    if not provider_valid:
        raise HTTPException(503, '메일 서버 설정을 확인하세요. 허용된 SSL 서버 설정이 필요합니다.')
    if not _probe_lock.acquire(blocking=False):
        raise HTTPException(409, '다른 접속 시험이 진행 중입니다. 완료 후 다시 시도하세요.')
    try:
        from app.mail_connector import probe_connection
        try:
            result = await run_in_threadpool(probe_connection, 'daum', configuration['username'], configuration['appPassword'], configuration['folders'], timeout=10)
        except Exception:
            # Never include an IMAP exception/server response or credentials.
            result = {'ok':False,'status':'network_error','errorCode':'PROBE_FAILED','userMessage':'접속 시험을 완료하지 못했습니다. 서버 연결과 설정을 확인하세요.','checkedAt':datetime.now(timezone.utc).isoformat(),'folders':[], 'capabilities':{'idleAdvertised':False,'idleTested':False}}
        # Connector returns a deliberately small safe schema. Rebuild it rather
        # than trusting arbitrary fields from a replaced adapter.
        safe = {key:result.get(key) for key in ('ok','status','checkedAt','provider','errorCode','userMessage','folders','capabilities')}
        safe['configurationRevision'] = configuration['revision']
        safe['providerFingerprint'] = provider_fingerprint
        with _state_lock, _vault_file_lock():
            latest = _configuration_or_error()
            if not latest or latest['revision'] != configuration['revision'] or _provider_snapshot()[2] != provider_fingerprint:
                raise HTTPException(409, '시험 도중 메일 설정이 변경됐습니다. 새 설정으로 다시 로그인하세요.')
            latest['lastTest'] = safe
            _save_configuration(latest)
        logger.info('mail_probe_completed')
        return public_status(latest)
    except (MailConfigurationError, OSError):
        raise HTTPException(503, '시험 결과를 안전하게 저장하지 못했습니다. 서버 저장소를 확인하세요.') from None
    finally:
        _probe_lock.release()

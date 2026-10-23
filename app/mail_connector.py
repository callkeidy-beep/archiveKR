"""Read-only IMAP SSL connection probe. Never collects mail bodies or sends mail.

Only sanitized operational statuses leave this module. Authentication credentials
are passed in memory and are neither logged nor included in response objects.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import imaplib
from pathlib import Path
import re
import socket
import ssl
import time
from typing import Callable

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'mail.yaml'
# Explicit supported provider endpoints; future providers require their own review.
ALLOWED_PROVIDERS = {'daum': ('imap.daum.net', 993)}


def encode_folder(value: str) -> str:
    """Encode an IMAP mailbox name using RFC 3501 modified UTF-7."""
    if not isinstance(value, str):
        raise ValueError('invalid_folder')
    output, non_ascii = [], []

    def flush():
        if non_ascii:
            encoded = base64.b64encode(''.join(non_ascii).encode('utf-16-be')).decode('ascii')
            output.append('&' + encoded.rstrip('=').replace('/', ',') + '-')
            non_ascii.clear()

    for character in value:
        if 0x20 <= ord(character) <= 0x7e:
            flush()
            output.append('&-' if character == '&' else character)
        else:
            non_ascii.append(character)
    flush()
    return ''.join(output)


def decode_folder(value: str | bytes) -> str:
    """Decode modified UTF-7; malformed input is rejected rather than guessed."""
    if isinstance(value, bytes):
        value = value.decode('ascii')
    output, position = [], 0
    while position < len(value):
        if value[position] != '&':
            if ord(value[position]) > 127:
                raise ValueError('invalid_modified_utf7')
            output.append(value[position])
            position += 1
            continue
        end = value.find('-', position)
        if end == -1:
            raise ValueError('invalid_modified_utf7')
        encoded = value[position + 1:end]
        if not encoded:
            output.append('&')
        else:
            raw = encoded.replace(',', '/')
            raw += '=' * ((4 - len(raw) % 4) % 4)
            try:
                output.append(base64.b64decode(raw, validate=True).decode('utf-16-be'))
            except (ValueError, UnicodeError) as error:
                raise ValueError('invalid_modified_utf7') from error
        position = end + 1
    return ''.join(output)


def quote_mailbox(name: str) -> str:
    """Quote ASCII modified UTF-7 so quotes/backslashes cannot alter commands."""
    return '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'


def load_provider(provider: str, config_path: str | Path | None = None) -> dict:
    configuration = yaml.safe_load(Path(config_path or DEFAULT_CONFIG).read_text(encoding='utf-8')) or {}
    providers = configuration.get('providers', configuration.get('mail', {}).get('providers', {}))
    if isinstance(providers, list):
        settings = next((value for value in providers if value.get('id') == provider), None)
    elif isinstance(providers, dict):
        settings = providers.get(provider)
    else:
        settings = None
    if not isinstance(settings, dict):
        raise ValueError('provider_not_configured')
    # This probe never accepts a hostname supplied by a browser request.
    host, port = settings.get('host'), settings.get('port', 993)
    if not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', host):
        raise ValueError('invalid_provider')
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError('invalid_provider')
    if settings.get('ssl', True) is not True:
        raise ValueError('ssl_required')
    if ALLOWED_PROVIDERS.get(provider) != (host.lower(), port):
        raise ValueError('provider_endpoint_not_allowed')
    return {'host': host.lower(), 'port': port, 'ssl': True}


def _success(status) -> bool:
    return status.decode('ascii', errors='ignore').upper() == 'OK' if isinstance(status, bytes) else str(status).upper() == 'OK'


def probe_connection(provider: str, username: str, app_password: str, folders: list[str], *,
                     config_path: str | Path | None = None,
                     client_factory: Callable | None = None, timeout: float = 10) -> dict:
    """Authenticate, LIST and EXAMINE configured folders, then report read-only status.

    `client_factory` is dependency injection for offline protocol tests only.
    Network timeouts and authentication/server responses never contain raw errors
    in the returned object. All requested folders must pass to report connected.
    """
    result = {
        'ok': False, 'status': 'network_error',
        'checkedAt': datetime.now(timezone.utc).isoformat(), 'provider': provider,
        'folders': [], 'capabilities': {'idleAdvertised': False, 'idleTested': False},
        'errorCode': None, 'userMessage': '',
    }

    def fail(status, code, message):
        result.update(ok=False, status=status, errorCode=code, userMessage=message)
        return result

    if not isinstance(username, str) or not username.strip() or '\r' in username or '\n' in username:
        return fail('authentication_failed', 'CREDENTIALS_REQUIRED', '접속용 아이디와 앱 비밀번호를 서버에서 설정하세요.')
    if not isinstance(app_password, str) or not app_password or '\r' in app_password or '\n' in app_password:
        return fail('authentication_failed', 'CREDENTIALS_REQUIRED', '접속용 아이디와 앱 비밀번호를 서버에서 설정하세요.')
    if (not isinstance(folders, list) or not 1 <= len(folders) <= 10
            or any(not isinstance(name, str) or not name.strip() or len(name) > 200
                   or any(ord(ch) < 32 or ord(ch) == 127 for ch in name) for name in folders)):
        return fail('folder_error', 'INVALID_FOLDERS', '시험할 폴더를 1~10개 지정하세요. 제어 문자는 사용할 수 없습니다.')
    try:
        settings = load_provider(provider, config_path)
    except (OSError, ValueError, yaml.YAMLError):
        return fail('network_error', 'PROVIDER_CONFIGURATION', '서버의 메일 공급자 SSL 설정을 확인하세요.')

    client, phase = None, 'connect'
    timeout = max(1.0, min(30.0, float(timeout)))
    deadline = time.monotonic() + timeout

    def budget():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        connection_socket = getattr(client, 'sock', None)
        if connection_socket is not None:
            connection_socket.settimeout(remaining)

    try:
        context = ssl.create_default_context()
        factory = client_factory or imaplib.IMAP4_SSL
        client = factory(settings['host'], settings['port'], ssl_context=context, timeout=timeout)
        client.debug = 0  # Never permit IMAP debug output to reveal LOGIN arguments.
        phase = 'login'
        budget()
        status, _ = client.login(username.strip(), app_password)
        if not _success(status):
            return fail('authentication_failed', 'AUTHENTICATION_FAILED', '인증에 실패했습니다. 접속용 아이디·앱 비밀번호·IMAP 사용 설정을 확인하세요.')
        phase = 'capability'
        budget()
        status, capabilities = client.capability()
        tokens = set()
        if _success(status):
            for capability in capabilities or []:
                if isinstance(capability, bytes):
                    tokens.update(capability.upper().split())
                elif isinstance(capability, str):
                    tokens.update(capability.upper().encode('ascii', errors='ignore').split())
        result['capabilities']['idleAdvertised'] = b'IDLE' in tokens
        phase = 'folder'
        any_failure = False
        for name in dict.fromkeys(folders):
            encoded = quote_mailbox(encode_folder(name))
            folder = {'name': name, 'exists': False, 'readOnly': False, 'uidValidity': None, 'messageCount': None}
            result['folders'].append(folder)
            budget()
            list_status, listing = client.list('""', encoded)
            if not _success(list_status) or not any(line for line in listing or []):
                any_failure = True
                folder['errorCode'] = 'FOLDER_NOT_FOUND'
                continue
            budget()
            selected, count = client.select(encoded, readonly=True)
            if not _success(selected):
                any_failure = True
                folder['errorCode'] = 'FOLDER_NOT_READABLE'
                continue
            folder['exists'], folder['readOnly'] = True, True
            budget()
            status, data = client.status(encoded, '(UIDVALIDITY MESSAGES)')
            if not _success(status):
                any_failure = True
                folder['errorCode'] = 'FOLDER_STATUS_FAILED'
                continue
            raw = b' '.join(value for value in data or [] if isinstance(value, bytes))
            validity = re.search(rb'\bUIDVALIDITY\s+(\d+)', raw, re.I)
            messages = re.search(rb'\bMESSAGES\s+(\d+)', raw, re.I)
            if not validity or not messages:
                any_failure = True
                folder['errorCode'] = 'FOLDER_STATUS_INCOMPLETE'
                continue
            folder['uidValidity'] = validity.group(1).decode('ascii')
            folder['messageCount'] = int(messages.group(1))
        if any_failure:
            return fail('folder_error', 'FOLDER_CHECK_FAILED', '일부 지정 폴더를 읽기 전용으로 확인하지 못했습니다. 폴더 이름과 접근 권한을 확인하세요.')
        budget()  # Never report a success that completed after the probe budget.
        result.update(ok=True, status='connected', errorCode=None,
                      userMessage='SSL 인증과 지정 폴더의 읽기 전용 접속 시험에 성공했습니다. 메일 본문은 수집하지 않았습니다.')
        return result
    except ssl.SSLError:
        return fail('tls_error', 'TLS_VERIFICATION_FAILED', 'SSL 인증서를 확인하지 못했습니다. 네트워크와 서버 설정을 확인하세요.')
    except (socket.timeout, TimeoutError):
        return fail('network_error', 'CONNECTION_TIMEOUT', '접속 시험 시간이 초과됐습니다. IMAP 서버 연결과 네트워크의 993 포트 허용 여부를 확인하세요.')
    except (imaplib.IMAP4.abort, OSError):
        return fail('network_error', 'CONNECTION_FAILED', '메일 서버 연결이 중단됐습니다. 네트워크와 IMAP 사용 설정을 확인하세요.')
    except imaplib.IMAP4.error:
        if phase == 'login':
            return fail('authentication_failed', 'AUTHENTICATION_FAILED', '인증에 실패했습니다. 접속용 아이디·앱 비밀번호·IMAP 사용 설정을 확인하세요.')
        if phase == 'folder':
            return fail('folder_error', 'FOLDER_CHECK_FAILED', '지정 폴더를 읽기 전용으로 확인하지 못했습니다. 폴더 이름과 접근 권한을 확인하세요.')
        return fail('network_error', 'PROTOCOL_ERROR', 'IMAP 서버 응답을 확인하지 못했습니다. 서버 설정을 확인하세요.')
    except Exception:
        return fail('network_error', 'CONNECTION_FAILED', '접속 시험에 실패했습니다. 서버 설정과 네트워크 상태를 확인하세요.')
    finally:
        if client is not None:
            try:
                connection_socket = getattr(client, 'sock', None)
                if connection_socket is not None:
                    connection_socket.settimeout(.5)
                client.logout()
            except Exception:
                try:
                    client.shutdown()
                except Exception:
                    pass

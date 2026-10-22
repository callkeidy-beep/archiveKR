"""Explicit hosting configuration; no hosting resources or credentials are created."""
import os
from pathlib import Path
import re

class DeploymentConfigurationError(ValueError):
    pass

def runtime_config():
    hosted = os.environ.get('RENDER', '').lower() == 'true'
    host = os.environ.get('CONTENT_MAKER_HOST', os.environ.get('HOST', '0.0.0.0' if hosted else '127.0.0.1'))
    port_text = os.environ.get('PORT') if hosted else os.environ.get('CONTENT_MAKER_PORT', os.environ.get('PORT', '3100'))
    try:
        port = int(port_text or '3100')
        if not 1 <= port <= 65535: raise ValueError()
    except ValueError:
        raise DeploymentConfigurationError('서버 포트 설정을 확인하세요.') from None
    forwarded = os.environ.get('FORWARDED_ALLOW_IPS', '127.0.0.1')
    if forwarded == '*' and not (hosted and os.environ.get('CONTENT_MAKER_PROXY_ISOLATED') == 'true'):
        raise DeploymentConfigurationError('전체 프록시 신뢰는 직접 접속이 차단된 Render 배포에서만 허용합니다.')
    if hosted:
        external = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').lower()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', external) or not external.endswith('.onrender.com'):
            raise DeploymentConfigurationError('Render의 자동 HTTPS 서버 주소를 확인하세요.')
        secret = os.environ.get('CONTENT_MAKER_ENCRYPTION_SECRET', '')
        if not os.environ.get('CONTENT_MAKER_ENCRYPTION_KEY') and len(secret) < 32:
            raise DeploymentConfigurationError('서버 암호화 비밀 설정이 필요합니다. 값은 출력하지 않습니다.')
        folder = Path(os.environ.get('CONTENT_MAKER_MAIL_DIR', '/data/mail'))
        if not (folder/'vault.enc').exists() and len(os.environ.get('CONTENT_MAKER_SETUP_TOKEN','')) < 32:
            raise DeploymentConfigurationError('최초 관리자 등록용 설정 코드가 필요합니다. 값은 출력하지 않습니다.')
        if forwarded == '*' and os.environ.get('CONTENT_MAKER_PROXY_ISOLATED') != 'true':
            raise DeploymentConfigurationError('외부 직접 접속이 차단된 플랫폼 프록시 설정을 확인하세요.')
        trusted = [x.strip().lower() for x in os.environ.get('CONTENT_MAKER_TRUSTED_HOSTS', '').split(',') if x.strip()]
        if external not in trusted: trusted.append(external)
        os.environ['CONTENT_MAKER_TRUSTED_HOSTS'] = ','.join(trusted)
    return {'host':host,'port':port,'proxy_headers':True,'forwarded_allow_ips':forwarded,'access_log':False,'server_header':False}

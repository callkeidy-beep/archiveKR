"""Interactive, server-local credential setup. Never use CLI password arguments."""
from getpass import getpass
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

from app.mail_service import configure_account, mail_dir, MailConfigurationError


def main():
    load_dotenv(ROOT / '.env', override=False)
    if not sys.stdin.isatty():
        print('메일 설정은 서버 터미널에서 대화식으로 실행하세요. 비밀번호를 명령 인수나 채팅으로 전달하지 마세요.', file=sys.stderr)
        return 2
    print('다음 메일 읽기 전용 접속 시험 설정')
    print('앱 비밀번호만 사용합니다. 일반 로그인 비밀번호를 입력하지 마세요.')
    print('메일 수집·이동·삭제·발송은 실행하지 않습니다.')
    if (mail_dir()/'vault.enc').exists():
        if input('기존 계정 설정을 교체하고 접속 결과·세션을 초기화할까요? [y/N] ').strip().lower()!='y':
            print('설정을 유지했습니다.')
            return 0
    try:
        username = input('다음 화면에 표시된 접속용 아이디: ').strip()
        entered = input('읽기 시험할 폴더 (쉼표로 구분, 기본: 보도자료,제보): ').strip()
        folders = [name.strip() for name in entered.split(',')] if entered else ['보도자료','제보']
        app_password = getpass('다음 앱 비밀번호 (화면에 표시되지 않음): ')
        admin_password = getpass('메일 설정 화면 관리자 비밀번호 (12자 이상, 앱 비밀번호와 다르게): ')
        confirmation = getpass('관리자 비밀번호 확인: ')
        if admin_password != confirmation: raise ValueError('관리자 비밀번호 확인이 일치하지 않습니다.')
        if admin_password == app_password: raise ValueError('관리자 비밀번호와 메일 앱 비밀번호는 다르게 설정하세요.')
        configure_account(username,app_password,admin_password,folders)
    except (ValueError, MailConfigurationError, OSError):
        print('설정을 저장하지 못했습니다. 아이디·폴더·비밀번호 조건과 서버 저장 권한을 확인하세요. 입력값은 출력하지 않습니다.',file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\n설정을 취소했습니다.', file=sys.stderr)
        return 1
    print('암호화 설정을 저장했습니다. 접속 성공을 의미하지 않습니다.')
    if not os.environ.get('CONTENT_MAKER_ENCRYPTION_KEY'):
        print('로컬 전용 키 파일을 사용합니다. 운영 서버에서는 암호화 키를 별도 비밀 저장소에 보관하세요.')
    print('서버의 연결·설정 화면에서 관리자 로그인 후 접속 시험을 실행하세요.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())

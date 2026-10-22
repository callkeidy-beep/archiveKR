"""Prepare the fixed container data mount, then run every command as engine.

A mounted persistent disk can have root ownership even when the image directory
was pre-owned by engine. No application or network handler runs with root rights.
"""
from pathlib import Path
import os
import pwd
import sys

def main():
    if not sys.argv[1:]:
        raise SystemExit('실행할 서버 명령이 필요합니다.')
    if os.geteuid() == 0:
        account = pwd.getpwnam('engine')
        for folder in (Path('/data'),Path('/data/mail')):
            if folder.is_symlink():
                raise SystemExit('데이터 디렉터리 설정을 확인하세요.')
            folder.mkdir(mode=0o700,exist_ok=True)
            os.chown(folder,account.pw_uid,account.pw_gid)
            folder.chmod(0o700)
        os.initgroups(account.pw_name,account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        os.environ['USER']=account.pw_name
    os.execvp(sys.argv[1],sys.argv[1:])

if __name__=='__main__':main()

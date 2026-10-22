# 선택적 오프라인 Docker 의존성

`npm run docker:prepare`가 requirements.lock의 패키지를 HTTPS로 이 폴더에 내려받습니다. wheel은 Git에서 제외됩니다. Docker는 wheel이 있으면 외부 접속 없이 설치하고, 없으면 일반 PyPI 설치를 사용합니다. 비밀번호/환경변수/메일을 빌드에 넣지 않습니다.

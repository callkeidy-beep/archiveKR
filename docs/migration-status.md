# 전환 기록 — 2026-10-22

기존 실행 모듈·자동 게시·이전 디자인·브리지·프롬프트 지시·설치 시작 스크립트를 새 1단계 프로젝트로 교체했다. .env나 실제 메일을 이전하지 않았다. 로컬 폴더/패키지/화면/문서/이미지명은 content-maker-engine/콘텐츠메이커 엔진이다. 이전코드는 Git 복구 태그와 별도 bundle에 보존했다.

GitHub 저장소 이름은 소유자가 content-maker-engine으로 변경했고 API·Git 읽기로 확인했다. origin은 https://github.com/callkeidy-beep/content-maker-engine.git, Pages는 https://callkeidy-beep.github.io/content-maker-engine/ 이다. 이전 이름 변경 API403 문제는 소유자의 직접 변경으로 해결됐다. Actions secrets/variables 조회 권한 제한은 별개이며 비밀/변수 존재 여부를 확인하거나 삭제했다고 주장하지 않는다.

클라우드 설정의 이전 install/start 지침과 저장소 mount, 사용자정의 네트워크목록은 새 프로젝트 기준으로 교체한다. 기존 미연결 비밀 요구항목의 삭제는 제공 도구가 지원하지 않으므로 환경 설정에서 제거해야 한다. 앱은 구형 SNS/공공API 키나 계정 요구항목을 읽지 않는다. 현재 필요한 인증키는 없다.

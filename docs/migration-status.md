# 전환 기록 — 2026-10-22

기존 실행 모듈·자동 게시·이전 디자인·브리지·프롬프트 지시·설치 시작 스크립트를 새 1단계 프로젝트로 교체했다. .env나 실제 메일을 이전하지 않았다. 로컬 폴더/패키지/화면/문서/이미지명은 content-maker-engine/콘텐츠메이커 엔진이다. 이전코드는 Git 복구 태그와 별도 bundle에 보존했다.

GitHub 원격 저장소명 변경 요청은 `Resource not accessible by integration (HTTP403)`으로 거부됐다. Git읽기/푸시와 Pages배포는 허용되지만 저장소 설정 변경과 Actions secrets/variables 조회는 이 인증에서 허용되지 않았다. 따라서 원격주소와 Pages경로는 아직 archiveKR이다. 소유자가 저장소 Settings→General→Repository name을 content-maker-engine으로 바꾸면 새 원격 URL과 Pages경로를 반영해야 한다. API로 비밀/변수 존재 여부를 확인하거나 삭제했다고 주장하지 않는다.

클라우드 설정의 이전 install/start 지침과 저장소 mount, 사용자정의 네트워크목록은 새 프로젝트 기준으로 교체한다. 기존 미연결 비밀 요구항목의 삭제는 제공 도구가 지원하지 않으므로 환경 설정에서 제거해야 한다. 앱은 구형 SNS/공공API 키나 계정 요구항목을 읽지 않는다. 현재 필요한 인증키는 없다.

# 취재·편집 데스크

archiveKR의 로컬 개발용 기사 기획·초안·검토·발행 상태 관리 모듈입니다. 원본 culture-news-archive 사이트는 접근 제한으로 복구하지 못했습니다. 이 모듈은 신규 구현이며 원본 서비스 복제나 인증·클라우드 공유 기능을 주장하지 않습니다.

`handleDesk(request, context)`는 `/api/desk/articles` API를 처리합니다. context는 `read()`와 동기 원자 저장 `update(mutator)`를 제공합니다. 사용자 입력은 데이터로만 저장하며 UI에서는 출력 시 이스케이프해야 합니다.

초안→검토에는 본문, 검토→발행에는 본문·제목·HTTPS 출처 링크가 필요합니다. 수동 작성 기사도 출처 링크가 필요합니다. 발행은 내부 상태 표시이며 외부 사이트 게시가 아닙니다. 발행→초안은 발행 상태를 취소합니다. 발행 기사의 제목·본문 수정은 먼저 초안으로 되돌려야 합니다.

검증: `node --test modules/editorial-desk/server.test.mjs`

# archiveKR 영화 자동 제작·배포

새 MOVIST 기사 또는 편집 데스크 원고를 영속 작업 큐에 넣어 기획 발췌, Instagram 캡션, Threads 문안, PNG 카드를 자동 제작한다. 원문은 덮어쓰지 않는다. 원문 발췌 방식이며 새로운 사실·취재·AI 검증을 수행했다고 표시하지 않는다. 제목만 있는 원고는 `awaiting_content`로 대기하고 본문 등록 이벤트에서 재개한다.

기본 설정은 제작 활성화, MOVIST 공식 목록 5분 탐색이다. 첫 탐색은 현재 목록을 기준선으로 저장하며 과거 기사를 자동 제작·배포하지 않는다. 이후 처음 발견되는 URL만 자동 수집한다. 사용자가 직접 URL을 수집하면 과거 기사도 즉시 제작한다. 기준선·성공 URL은 저장되어 재시작 후에도 유지되며 실패한 신규 URL은 다음 탐색에서 재시도한다. 수집 출처는 `https://movist.com`, `https://www.movist.com`, `https://m.movist.com`만 허용한다. 수집·렌더링은 상위 서버가 주입하는 영화제작실 어댑터가 담당한다. 자동화 데이터는 상위 로컬 저장소의 `automation`, PNG는 `.local/automation/`에 저장한다.

## 외부 게시

외부 채널 자동 배포는 기본 활성화이며 계정이 연결되어야 공식 API를 호출한다. 계정 연결 전에도 제작물은 `ready`, 게시 단계는 `blocked`로 구분한다.

- Threads: `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN` (게시 권한 포함).
- Instagram: `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `ARCHIVEKR_PUBLIC_MEDIA_BASE_URL`. Instagram이 접근할 수 있는 공개 HTTPS PNG 경로가 필요하다. 이 개발 서버는 루프백 전용이므로 공개 배포가 먼저 필요하다.

공식 Threads API 및 Instagram Graph API만 사용하며 브라우저 자동 로그인이나 비공식 게시 우회는 제공하지 않는다. 토큰은 서버 환경변수에만 둔다. API 응답에는 환경변수 존재 여부만 포함한다.

외부 요청 전 `posting` 상태를 영속 저장한다. Instagram 컨테이너는 공식 상태 API에서 `FINISHED`를 확인한 뒤 게시한다. 명확한 HTTP 400/401/403/429 거부는 `blocked`로 표시하고 최소 60초 뒤 재시도한다. 수동 재시도는 이 대기 시간을 초기화한다. 응답 실패 또는 서버 재시작으로 결과가 불명확하면 `ambiguous`로 남기고 자동 재시도하지 않는다. 편집자는 해당 계정에서 게시 여부를 확인해야 한다. 불명확한 게시가 포함된 작업은 재시도를 거부한다. 이미 게시한 채널은 원고가 수정되어도 자동 재게시하지 않으며 수정 제작물은 로컬에서 확인할 수 있다. 계정을 나중에 연결하면 차단된 제작물 배포를 자동 재개한다. 로컬 저장소는 단일 서버 프로세스용이다.

## API

- `GET /api/automation/status`, `/jobs`, `/settings`
- `PATCH /api/automation/settings`: `enabled`, `pollingEnabled`, `sourceUrl`, `pollSeconds`(60~86400), `channels: {instagram, threads}`
- `POST /api/automation/ingest`: `{ "url": "https://www.movist.com/..." }`
- `POST /api/automation/jobs/:id/retry`: `{}`
- `GET /api/automation/jobs/:id/card`: 생성된 PNG

`await engine.stop()`은 새 작업을 막고 연결된 요청을 취소한 뒤 실행 중인 tick 종료를 기다린다. 수집·탐색·카드 어댑터는 두 번째 인수의 `signal`을 전달받아 취소를 지원해야 한다.

검증: `node --test modules/automation/server.test.mjs`.

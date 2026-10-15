# archiveKR 영화 자동 제작·배포

새 MOVIST 기사 또는 편집 데스크 원고를 영속 작업 큐에 넣어 기획 발췌, Instagram 캡션, Threads 문안, PNG 카드를 자동 제작한다. 원문은 덮어쓰지 않는다. 원문 발췌 방식이며 새로운 사실·취재·AI 검증을 수행했다고 표시하지 않는다. 제목만 있는 원고는 `awaiting_content`로 대기하고 본문 등록 이벤트에서 재개한다.

기본 설정은 제작 활성화, MOVIST 공식 목록 5분 탐색이다. 첫 탐색은 현재 목록을 기준선으로 저장하며 과거 기사를 자동 제작·배포하지 않는다. 이후 처음 발견되는 URL만 자동 수집한다. 사용자가 직접 URL을 수집하면 과거 기사도 즉시 제작한다. 기준선·성공 URL은 저장되어 재시작 후에도 유지되며 실패한 신규 URL은 다음 탐색에서 재시도한다. 수집 출처는 `https://movist.com`, `https://www.movist.com`, `https://m.movist.com`만 허용한다. 수집·렌더링은 상위 서버가 주입하는 영화제작실 어댑터가 담당한다. 자동화 데이터는 상위 로컬 저장소의 `automation`, PNG는 `.local/automation/`에 저장한다.

## 외부 게시

제작은 자동으로 진행하되 외부 게시에는 매 제작 버전별 사용자 최종 승인이 필요하다. 계정과 토큰이 있어도 승인 전에는 외부 게시 API를 호출하지 않는다. 제작물은 `ready`, 승인함은 `pending`으로 표시한다. 사용자가 채널과 계정 ID를 확인하여 승인한 채널만 게시한다. 원문·문안·카드·게시 계정이 바뀌면 승인은 만료된다. 기존 제작물과 레거시 작업에 승인을 소급 부여하지 않는다. 이미 발행된 채널은 원문이 바뀌지 않는 한 재시도나 재시작으로 재발행하지 않는다. 발행 후 원문이 바뀌면 이전 버전의 게시 ID·시각을 `publicationHistory`에 보존하고 새 제작 버전에 최종 승인을 요청한다. 새 승인 후 게시하면 기존 SNS 게시글 수정이 아닌 새 게시물이 생성된다.

- Threads: `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN` (게시 권한 포함).
- Instagram: `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `ARCHIVEKR_PUBLIC_MEDIA_BASE_URL`. Instagram이 접근할 수 있는 공개 HTTPS PNG 경로가 필요하다. 이 개발 서버는 루프백 전용이므로 공개 배포가 먼저 필요하다.

공식 Threads API 및 Instagram Graph API만 사용하며 브라우저 자동 로그인이나 비공식 게시 우회는 제공하지 않는다. 토큰은 서버 환경변수에만 둔다. API 응답에는 토큰의 존재 여부와 승인 대상 계정 ID만 포함하고 토큰 값은 포함하지 않는다.

외부 요청 전 `posting` 상태를 영속 저장한다. Instagram 컨테이너는 공식 상태 API에서 `FINISHED`를 확인한 뒤 게시한다. 명확한 HTTP 400/401/403/429 거부는 `blocked`로 표시하고 최소 60초 뒤 재시도한다. 수동 재시도는 이 대기 시간을 초기화한다. 응답 실패 또는 서버 재시작으로 결과가 불명확하면 `ambiguous`로 남기고 자동 재시도하지 않는다. 편집자는 해당 계정에서 게시 여부를 확인해야 한다. 불명확한 게시가 포함된 작업은 재시도를 거부한다. 원고가 수정되면 새 제작물과 승인함을 만들며 새로운 명시적 승인 전에는 재게시하지 않는다. 승인된 계정의 토큰만 나중에 연결하면 유효한 승인에 한해 차단된 배포를 재개한다. 계정 ID가 변경되면 다시 승인해야 한다. 로컬 저장소는 단일 서버 프로세스용이다.

## 역할 판단과 메시지

판단은 LLM 대화가 아닌 명시적 규칙 기반이다. 취재·편집 데스크는 출처·문맥 검토 필요성을 표시하고 제작실에 작업을 요청한다. 제작실은 원문 사진 유무로 사진 카드 또는 텍스트 카드 가능 여부를 답하고 실제 제작 성공/실패를 기록한다. 자동화는 제작 완료 후 사용자에게 최종 승인을 요청한다. 메시지에는 작업 ID·발신/수신 역할·유형·제작 버전·시각·응답 연결이 저장되며 동일 tick으로 중복되지 않는다. 수정 요청은 데스크와 제작실로 전달되며 원문 수정 후 새 제작 버전에 다시 승인이 필요하다. 반려·수정 요청은 재시작과 재시도로 해제되지 않는다. 메시지는 승인을 대체할 수 없으며 결정의 actor는 서버에서 `user`로 지정한다. 현재 단일 로컬 사용자용이며 다중 사용자 운영 인증·권한 체계는 별도 구축해야 한다.

승인은 원문 내용 해시, SNS 문안, PNG 해시에 결합된다. PNG는 버전별 불변 파일로 저장하며 게시 API 요청 직전 및 컨테이너 생성 후 시작 시 캡처한 제작 버전·승인 결정 ID·선택 채널을 다시 검사한다. 새 버전을 승인하거나 같은 버전에 재승인해도 이전 요청의 컨테이너를 게시할 수 없다. 이미 전송된 외부 요청은 취소나 되돌리기를 보장할 수 없어 불명확한 결과를 자동 재시도하지 않는다.

## API

- `GET /api/automation/status`, `/jobs`, `/settings`, `/messages`, `/approvals`
- `POST /api/automation/jobs/:id/decision`: `{decision: "approve" | "reject" | "request_changes", revision, channels: ["instagram", "threads"], targets: {instagram: 계정ID또는null, threads: 계정ID또는null}, note?}`. 채널과 대상은 승인 시 필수이며 최신 버전·대상 불일치나 이미 결정된 승인은 409. 상태 API의 `targets`를 확인한 후 그대로 전달한다.
- `PATCH /api/automation/settings`: `enabled`, `pollingEnabled`, `sourceUrl`, `pollSeconds`(60~86400), `channels: {instagram, threads}`
- `POST /api/automation/ingest`: `{ "url": "https://www.movist.com/..." }`
- `POST /api/automation/jobs/:id/retry`: `{}`
- `GET /api/automation/jobs/:id/card`: 생성된 PNG (`?revision=SHA256`은 해당 버전의 불변 PNG)

`await engine.stop()`은 새 작업을 막고 연결된 요청을 취소한 뒤 실행 중인 tick 종료를 기다린다. 수집·탐색·카드 어댑터는 두 번째 인수의 `signal`을 전달받아 취소를 지원해야 한다.

검증: `node --test modules/automation/server.test.mjs`.

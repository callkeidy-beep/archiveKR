# archiveKR

기회 발견부터 기사 검수·지역뉴스 발행과 영화 카드 제작까지 이어지는 통합 개발 앱입니다. `AGENTS.md`에 상위 통합 에이전트와 네 하위 에이전트의 담당 범위를 기록했습니다. 하위 에이전트는 개발 역할이며 상시 실행되는 AI 프로세스는 아닙니다.

| 기능 | 모듈 | 현재 상태 |
| --- | --- | --- |
| 기회탐색 | modules/opportunity-radar | 원본 소스 재사용, 실제 공고 수집 중계, 기사 기획 인계 |
| 취재·편집 데스크 | modules/editorial-desk | 기획·초안·검수·발행·발행 취소 |
| 지역뉴스 | modules/regional-news | 발행 기사만 조회, 지역 검색, 발췌 브리핑 |
| 영화·카드뉴스 제작실 | modules/movist | 첨부 ZIP 및 디자인 규격 재사용, PNG 제작, 로컬 영상 도구 |

## 설치와 실행

Node.js 24 이상, Python 3.12를 사용합니다. Node의 `--use-env-proxy` 옵션으로 클라우드 프록시를 사용하며 TLS 검증을 유지합니다. npm 외부 의존성은 없고 Python 의존성은 별도 가상환경에 설치합니다.

```bash
cd /workspace/archiveKR
npm run setup
npm run dev
```

통합 서버는 로컬 포트 3100, 영화 제작실은 3102입니다. 통합 포트는 `PORT`로 변경할 수 있습니다. `npm run dev`가 두 서비스를 함께 시작·종료합니다. 이미 격리된 작업 환경이므로 별도 Git worktree는 만들지 않습니다.

검증을 다시 실행하려면:

```bash
npm run build
npm run validate
modules/movist/.venv/bin/python -m unittest discover -s modules/movist -p 'test_*.py'
```

## 실제 수집과 인증

기회레이더 원본: https://github.com/callkeidy-beep/opportunity-radar (기준 커밋 `9b74d67a0f295a08b74450e891eeb925c29eeda1`).

현재는 인증키 없는 공식 API 요청을 기존 운영 서버 `https://opportunity-radar-vert-pi.vercel.app`의 검증된 공개 수집 API로 중계합니다. 원본의 키를 복사한 것이 아니며, 사용자 키·쿠키·쿼리는 중계하지 않습니다. 응답의 `relay`에 출처와 확인 시각을 기록합니다. `ARCHIVEKR_USE_RELAY=0`으로 기존 서버 의존성을 끌 수 있습니다. 독립 수집에는 `DATA_GO_KR_SERVICE_KEY`, `G2B_SERVICE_KEY`, `BIZINFO_SUPPORT_KEY`, `BIZINFO_EVENT_KEY`가 필요합니다. 관세청 통계는 별도 선택 기능이며 `CUSTOMS_SERVICE_KEY`를 사용합니다.

한 번의 실요청에서 K-Startup 첫 페이지 100건, 과기정통부 10건, 문체부 공지 6건·보도자료 10건을 확인했습니다. 나라장터·기업마당은 0건 응답이며 이 수치는 이후 달라질 수 있습니다. 전체 페이지를 수집했다고 주장하지 않습니다. 기존 시연 공고를 실제 공고와 구분하며 원문이 기사로 자동 발행되지 않습니다.

영화 카드 제작은 AI 키 없이 동작합니다. AI 원고 변환은 선택 기능으로 `ANTHROPIC_API_KEY`가 필요합니다. 인증키는 안전한 환경 설정으로 입력하고 파일·브라우저 보관함·GitHub·로그에 넣지 마세요. 첨부 ZIP의 config.env는 제외했습니다. Telegram·음성·외부 게시 기능은 실행하지 않았습니다.

## 저장과 운영 범위

기사 기획·원고·발행 상태는 `.local/data.json`에 원자적으로 저장됩니다. `ARCHIVEKR_DATA_FILE`로 경로를 바꿀 수 있습니다. 기회탐색 평가·메모는 기존 브라우저 localStorage에 남습니다. 영화 보관함은 `modules/movist/data/`, 결과물은 `modules/movist/output/`에 보관합니다. 이 경로들은 Git에서 제외되어 있으므로 운영 이전 시 별도 백업이 필요합니다. 손상된 기사/영화 저장 파일을 빈 데이터로 덮어쓰지 않습니다.

서버는 로컬 개발용입니다. 공용 직원 인증·권한·공유 DB·운영 배포는 아직 연결하지 않았습니다. 로컬 지역뉴스의 발행은 외부 운영 사이트 게시와 별개입니다. 외부 사이트 `https://glocal-times.kkdkr.chatgpt.site`와 `https://culture-news-archive.kkdkr.chatgpt.site`는 프록시 차단을 해결한 뒤 ChatGPT 로그인 필요(401)를 확인했으며 원본 데이터·권한·소스를 이전하지 못했습니다. 이 두 기능은 첨부 운영 흐름을 바탕으로 새로 만들었습니다.

## 확인된 검증

- Node 테스트 16개: 기사 상태 전환·발행 취소·비공개 원고 제외·중계 보호·빌드 HTML 보존·재시작 후 저장 유지.
- Python HTTP 테스트 6개: 실제 카드 크기·URL 제한·잘못된 JSON·보관함 파일 보호·비밀값 오류 비출력.
- Chromium 실제 동작: 공고→기사 기획→저장→검수→발행→읽기→발행 취소, HTML 문자열 안전 표시, 모바일 가로 넘침 없음.
- 실제 수집 후 네 카드 숫자와 클릭한 목록 수 일치. 브라우저에서 카드 PNG 다운로드.
- 프록시를 통한 실제 PNG 1080×1440, 원본 영상 도구로 1초 무음 MP4 생성. 전체 자동 쇼츠·TTS는 미검증.

외부 운영 배포 및 새 작업 환경 복원은 별도 검증 대상입니다. 환경 초안 저장은 실행·게시·외부 배포를 뜻하지 않습니다.

# archiveKR 영화제작실 (MOVIST 기반 하위 에이전트)

사용자가 첨부한 `movist-auto.zip`의 Python 변환기와 웹 편집기를 기반으로 만든 네 번째 모듈입니다. 첨부한 `MOVIST_카드뉴스_디자인규격.xlsx`의 3:4 기본값과 글자 크기, 흰 테두리 태그, 가운데 라벨, 표지 부제 숨김을 반영했습니다. 원본 config.env는 비밀 가능성이 있어 추출하거나 복사하지 않았습니다. 첨부 문서의 실행 및 자동 게시 지시는 외부 게시 권한으로 취급하지 않습니다.

## 실행

저장소 루트에서:

```sh
python -m venv modules/movist/.venv
modules/movist/.venv/bin/pip install -r modules/movist/requirements-cloud.txt
modules/movist/.venv/bin/python modules/movist/app_server.py
```

127.0.0.1:3102에서 실행하며 archiveKR 프록시가 `/movist/`, `/movist/shim.js`, `/movist/fonts/*`, `/api/movist/*` 경로를 유지해서 전달합니다. 환경은 이미 격리되어 있으므로 별도 Git worktree는 만들지 않습니다.

## 기능 및 API

- `/movist/`: 기사 입력, 채널별 변환 편집, 사진 카드 편집·내보내기, 보관함·편집국 규칙. API 키 없이 제목으로 PNG를 내려받는 별도 카드 초안 버튼 포함.
- `GET /api/movist/health`: 상태와 AI 키 존재 여부. 값은 반환하지 않음.
- `POST /api/movist/cards`: `{headline, tag, label, cover, body}`로 실제 1080×1440 PNG 반환. 배경 사진 없는 로컬 카드 렌더러이며 웹 사진 카드 편집기와는 별도.
- `GET/POST /api/movist/store`: 로컬 보관함. `POST /api/movist/save?filename=...`: 로컬 output 저장.
- `GET /api/movist/fetch?url=...`: movist.com/www.movist.com의 HTTPS 기사만 허용, 리다이렉트와 다른 도메인 이미지 차단. 실제 MOVIST 기사 네트워크 수집은 미검증.
- `POST /api/movist/claude`: ANTHROPIC_API_KEY가 있을 때만 AI 변환. 키 없이 AI 결과를 임의 생성하지 않음.

키는 안전한 환경 변수로 주입합니다. 필요 변수 이름은 config.env.example에만 기록되어 있으며 값은 포함하지 않습니다. Telegram 자동 게시 기본값은 no입니다. 모듈 웹 서버에는 외부 게시 API가 없으며 자동 수집 CLI는 실행하지 않았습니다. Telegram/Higgsfield/ElevenLabs는 선택 기능으로 검증하지 않았습니다. 모델은 MODEL 환경 변수로 변경할 수 있습니다.

## 검증

- Python 컴파일, 모듈 페이지·shim·한글 로컬 폰트·health 응답 200.
- 카드 API가 실제 PNG를 만들고 Pillow로 1080×1440 확인.
- http://127.0.0.1 URL의 fetch 400 차단.
- 기존 shorts.py와 검증된 imageio-ffmpeg 7.0.2를 사용해 로컬 사진/자막 1초 무음 MP4 생성·길이 확인. 내레이션/TTS 및 전체 자동 쇼츠 제작은 외부 서비스를 사용하므로 미검증.
- 웹 ZIP 내보내기는 원본의 JSZip CDN 의존성이 남아 있습니다. 단일 PNG 초안은 이 의존성 없이 동작합니다.

서버는 로컬 개발용이며 공개 인터넷 노출 전 인증 및 요청 제한이 필요합니다. fonts/head.ttf, fonts/body.ttf는 첨부 ZIP에 포함된 폰트를 재사용하며 온라인 폰트 호출을 제거했습니다. 글자 지표는 폰트에 따라 달라질 수 있으며 Python 초안 렌더러는 XLSX의 2% 자간 조정을 지원하지 않습니다.

### API 회귀 검증

```sh
modules/movist/.venv/bin/python -m unittest discover -s modules/movist -p test_server.py -v
```

6개 오프라인 테스트가 실제 임시 HTTP 서버에서 PNG 크기, 잘못된 JSON/보관함 키 거절, 정상 저장, 손상된 보관함 보존, AI 예외 비밀값 비노출, HTTPS 기사 주소 허용 범위를 검증합니다. 보관함은 movist_history/movist_rules 문자열만 받으며, 손상 파일은 409 응답으로 보존합니다. API 실패는 외부 서비스 예외본문을 반환하거나 콘솔에 출력하지 않습니다.

### 승인된 카드 디자인과 자동 제작 API

최근 첨부 ZIP의 웹 화면은 왼쪽 큰 로고가 있던 이전판입니다. 현재 스튜디오의 최신 수정과 함께 첨부된 디자인 규격을 유지합니다. 자동 렌더러는 이 규격의 1080×1440, 가운데 MOVIST(26px·자간3px), 흰 테두리 태그, 제목 84/68px·굵기800·줄간격1.3·자간-2%, 안쪽 본문36px, 표지 부제 기본 숨김, 45%부터 아래92% 검정 그라데이션을 적용합니다. 외부 폰트 다운로드 없이 번들 Noto Sans KR을 씁니다. 사진 출처는 20px로 표시합니다.

`POST /api/movist/cards`는 기존대로 PNG 한 장을 반환합니다. `POST /api/movist/cards/render-set`는 `{cards:[{headline,body,sourceImage}],credit,label,tag,ratio}`를 받아 순서대로 표지·안쪽 PNG를 제작합니다. `sourceImage`는 수집 시 반환한 `/api/movist/img/...` 로컬 경로만 허용합니다. 응답 `cards[].data`는 base64 PNG이며 `manifest`에는 장수, 사진 사용 확인 대기 여부, 최종 승인 필요 여부를 기록합니다. 최대10장, 비율은 `34`·`45`·`916`입니다. 개별 카드의 `layout`은 `full`·`split`·`text`, `size`는 `small`·`normal`·`large`입니다. `GET /api/movist/cards/template`로 디자인 값을 확인합니다.

표지 제목은 최대 2줄·각 13자이며 초과하면 400으로 알립니다. 긴 사진 출처는 화면에서만 말줄임하며 원본 메타데이터를 바꾸지 않습니다. 문안이 영역을 넘으면 400으로 알리고 자동으로 잘라내지 않습니다. 사진을 가져오고 출처를 적는 것은 사진 사용 허락을 의미하지 않습니다. 실제 사용 권한 확인과 게시 승인은 archiveKR 승인함에서 별도로 진행합니다. 렌더러는 외부 게시를 수행하지 않습니다.

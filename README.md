# 콘텐츠메이커 엔진

[공개 샘플 사이트](https://callkeidy-beep.github.io/content-maker-engine/) · [GitHub 저장소](https://github.com/callkeidy-beep/content-maker-engine)

보도자료와 제보를 분류하고 기사 후보를 고르는 한국어 편집 작업대. 마지막 판단은 사람이 합니다.

## 현재 완성 범위 — 1단계 샘플

- 허구의 샘플 메일20건, 분야·계정·검색별 수집함
- 중복·수정본·엠바고·민감 자료·사진 사용 보류 표시
- 단일·묶음·트렌드·추가 취재 질문의 네 가지 규칙 기반 기획
- 자료ID·문단·문자 범위와 연결되는 근거 확인
- 항목별 점수와 설명을 공개하는 후보12, 다른 분야 탐색 후보2
- 1~5점·채택/보류/폐기/후속취재·코멘트 평가 및 SQLite 저장
- 공개 정적샘플에서는 이 브라우저에만 평가 저장

**자료 작업대는 샘플입니다. 실제 본문 수집·AI 작성·발행·가중치 학습·주간 백업은 실행되지 않습니다. 별도의 관리자 로그인 후 다음 메일 SSL 접속 시험을 실행할 수 있습니다.** 기본 매체는 무비스트이며 config/settings.yaml에서 바꿀 수 있습니다. 실제메일 인증정보를 샘플 화면에 입력하지 마세요.

## 로컬 실행

Python3.12+ / Node24+. 루트에서:

```sh
npm run setup
npm run dev
```

`npm test`로 검증하고 `npm run build`로 공개샘플 site-dist/를 생성합니다. Python 환경은 .venv/이며 앱 데이터는 .local/에 저장돼 Git에서 제외됩니다. 설치 시 .env를 만들거나 인증키를 요구하지 않습니다. 서버·워커가 꺼지면 예약 작업도 멈추므로 향후 실제 수집은 상시 서버가 필요합니다. 현재 예약 작업은 비활성입니다.

## Docker

```sh
npm run docker:prepare # 빌드망 제한 시 선택: 패키지 미리 내려받기
docker compose up --build -d
docker compose logs --tail=50
docker compose down
```

루프백3100에만 연결하고 평가는 영속 볼륨에 저장합니다. `docker compose down -v`는 평가 데이터를 삭제하므로 사용에 주의합니다. 1단계 컨테이너는 샘플 전용입니다. 실제메일 운영을 공개하려면 로그인·접근통제·암호화·TLS와 실제 연동을 추가해야 합니다.

## 구조·다음 단계

개발 규칙은 [CLAUDE.md](CLAUDE.md), 단계·연결 상태는 [docs/roadmap.md](docs/roadmap.md), 외부 제작 도구 인계안은 [docs/export-contract.md](docs/export-contract.md)를 참조합니다.

## 이전 구성 복구

기존 archiveKR/archiveKD 실행 모듈·자동 게시·고정 카드 디자인·설치 스크립트는 제거했습니다. Git 이력은 `legacy-before-content-maker-engine-20261022` 태그에 보존했습니다. 별도 Git bundle도 클라우드 작업공간의 `/workspace/shared/content-maker-recovery/legacy-20261022.bundle`에 만들고 검증했습니다. 이는 일회성 전환 복구 파일이며 주간 데이터 백업 기능과 다릅니다. 이전 .env나 실메일 데이터는 저장하지 않았습니다.

## 다음 메일 연결·접속 시험

서버 터미널에서 `npm run mail:setup`으로 접속용 아이디·폴더·앱 비밀번호·별도 관리자 비밀번호를 입력합니다. 계정은 암호화 저장합니다. 휴대폰에서는 본인 HTTPS 서버에 관리자 로그인한 뒤 계정을 등록할 수 있습니다. 일반 HTTP와 공개 샘플에는 앱 비밀번호 입력창이 없습니다. `npm run dev` 후 서버의 연결·설정에서 관리자 로그인→접속 시험. 모든 지정 폴더의 읽기전용 시험에 성공한 최근 결과만 연결 성공으로 표시합니다.

[다음 메일 설정·암호화 키·Docker·오류 안내](docs/mail-connection.md)를 먼저 확인하세요. 공개 GitHub Pages에서는 실제 연결·관리자 로그인을 실행하지 않습니다. 앱 비밀번호를 채팅에 보내지 마세요.

## 휴대폰으로 서버 준비

[휴대폰 배포·관리자 등록 안내](docs/mobile-deployment.md) · [Render 배포 화면 열기](https://render.com/deploy?repo=https://github.com/callkeidy-beep/content-maker-engine)

`render.yaml`은 자동 HTTPS·영속 디스크·초기 설정 코드·별도 암호화 비밀값을 구성합니다. **유료 서버이며 사용자가 요금을 확인하고 생성해야 합니다. 현재 실제 서버는 개설하지 않았습니다.** 배포된 본인 HTTPS 서버에서 첫 관리자 등록→로그인→다음 계정 등록→다시 로그인→읽기 전용 접속 시험을 진행합니다. 실제 다음 계정의 성공 시험 전에는 연결 완료가 아닙니다.

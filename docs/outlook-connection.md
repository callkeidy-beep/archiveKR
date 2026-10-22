# Outlook 메일 연결

Outlook.com·Hotmail 등 개인 Microsoft 계정과 Microsoft 365 조직 계정의 실제 메일함을 콘텐츠메이커 엔진의 읽기 전용 수집원으로 연결합니다. 다음메일을 Outlook 앱에 등록한 것만으로는 Microsoft Graph에서 그 다음메일을 읽을 수 없습니다.

현재 준비된 기능과 실제 연결은 다릅니다. Microsoft 앱 등록, 개인 HTTPS 서버, 실제 계정의 권한 승인이 끝나야 연결할 수 있습니다. 공개 GitHub Pages는 샘플이므로 로그인·메일 수집을 실행하지 않습니다. 자동 기사 작성·예약 수집·발행은 이 연결 작업의 범위에 포함되지 않습니다.

## 1. Microsoft 앱 등록

휴대폰 브라우저에서 [Microsoft Entra 관리 센터](https://entra.microsoft.com/)를 열고 앱 등록으로 이동합니다. 조직 관리자가 앱 등록을 제한했다면 관리자 도움이 필요합니다. 개인 계정에서 앱 등록 화면에 접근할 수 없는 경우에도 등록 가능한 Microsoft Entra 디렉터리가 필요할 수 있습니다.

1. **앱 등록 → 새 등록**에서 이름을 `콘텐츠메이커 엔진`으로 지정합니다.
2. 지원 계정 유형은 **모든 조직 디렉터리의 계정 및 개인 Microsoft 계정**을 선택합니다.
3. 플랫폼은 **웹**으로 선택합니다.
4. 리디렉션 URI에는 서버의 정확한 HTTPS 주소를 입력합니다. 예: `https://내서버주소/api/mail/outlook/callback`. GitHub Pages 주소나 임의 주소를 넣지 않습니다.
5. 애플리케이션(클라이언트) ID를 확인합니다.
6. **인증서 및 비밀 → 새 클라이언트 비밀**에서 비밀을 만들고 만료 일정을 기록합니다. 생성 직후 표시되는 **값**을 서버의 비밀 환경변수에만 저장합니다. 비밀 ID와 값은 다릅니다.
7. **API 권한 → Microsoft Graph → 위임된 권한**에서 `User.Read`, `Mail.Read`를 추가합니다. 장기 로그인 갱신을 위한 `offline_access`도 로그인에서 요청합니다. 애플리케이션 권한이나 `Mail.Send`, `Mail.ReadWrite`는 추가하지 않습니다.

조직 정책에 따라 관리자 동의가 필요할 수 있습니다. 승인이 막힌 경우 권한을 확대하거나 정책을 우회하지 말고 해당 조직 관리자에게 확인합니다.

## 2. 서버 비밀 설정

호스팅의 환경변수 화면 또는 비공개 `.env`에 다음을 설정하고 서버를 재시작합니다.

```dotenv
CONTENT_MAKER_MICROSOFT_CLIENT_ID=앱의_클라이언트_ID
CONTENT_MAKER_MICROSOFT_CLIENT_SECRET=클라이언트_비밀의_값
CONTENT_MAKER_MICROSOFT_REDIRECT_URI=https://내서버주소/api/mail/outlook/callback
```

앱 비밀, 로그인 코드, 토큰을 채팅·스크린샷·Git에 올리지 않습니다. 기존 관리자 설정 코드, 암호화 키와 영구 저장소도 필요합니다. 서버 재배포 시 암호화 키를 바꾸지 않습니다. Graph 연결도 동작하는 HTTPS 서버를 필요로 하므로 GitHub Pages만으로 실제 메일을 수집할 수 없습니다.

## 3. 휴대폰에서 연결

1. 자신의 개인 HTTPS 서버를 열고 **연결·설정**으로 이동합니다.
2. 최초 관리자 등록 후 관리자 로그인합니다. Outlook만 연결한다면 다음메일 앱 비밀번호 등록은 필요하지 않습니다.
3. **Outlook 메일 수집 → Microsoft 계정으로 연결**을 누릅니다.
4. Microsoft 공식 로그인 화면에서 계정을 확인하고 읽기 권한을 승인합니다. Outlook 비밀번호는 Microsoft 화면에서만 입력합니다.
5. 서버로 돌아와 상태를 확인합니다. 관리자 로그인이 만료됐다면 다시 로그인합니다.
6. **최근 메일 가져오기**를 눌러 결과를 확인합니다. 현재는 최근 메일의 제목·발신자·수신일·미리보기만 가져옵니다. 본문 전체·첨부·예약 수집·기사 후보 연결은 아직 실행하지 않습니다. 공개 샘플 후보와 실제 수집 자료는 별도로 취급합니다.

연결 해제는 서버에 저장된 연결 정보를 제거하는 기능입니다. Microsoft 측 권한도 회수하려면 계정의 앱 권한 관리 화면에서 해당 앱 동의를 취소합니다. 이미 내려받은 자료 삭제 범위는 서버의 데이터 보관 정책을 별도로 확인합니다.

## 공식 참고 문서

- [Microsoft ID 플랫폼 앱 등록](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
- [OAuth 2.0 authorization code 흐름](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Microsoft Graph 메시지 목록](https://learn.microsoft.com/en-us/graph/api/user-list-messages)
- [Microsoft Graph 권한 참조](https://learn.microsoft.com/en-us/graph/permissions-reference)

실제 제공 조건, 개인 계정의 앱 등록 가능 여부와 조직 정책은 Microsoft 콘솔에서 확인해야 합니다. 테스트용 가짜 응답은 실제 계정 연결 성공을 뜻하지 않습니다.

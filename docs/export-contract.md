# 외부 제작 도구 인계 계약 v0.1 (3단계 구현 예정)

현재 1단계에서 아래 인계 파일을 실제 생성했다고 표시하지 않습니다. 두 도구 모두 원문 근거와 인간 승인 상태를 보존해야 합니다.

## 공통 패키지
`manifest.json`, `article.md`, `article.newsarticle.jsonld`, `evidence.json`, `slides.json`, `datasets/*.csv`.
JSON은 UTF-8, 날짜는 ISO8601+timezone, ID는 자료ID 기반 안정식별자. 개인정보는 기본 가림, 사진 source/credit/usage 조건과 보류 상태를 보존. `verificationStatus: unverified`와 `publicationApproval: pending` 기본값. 샘플에는 `sample:true`.

## 콘텐츠 변환 엔지니어
```json
{"schemaVersion":"0.1","project":"content-maker-engine","articleId":"article-001","sample":true,"verificationStatus":"unverified","publicationApproval":"pending","ratio":"1:1","slides":[{"number":1,"title":"근거가 있는 제목","body":"원문에 근거한 문구","photoId":null,"caption":"","sourceLabels":[],"evidence":[{"sourceId":"sample-001","paragraphId":"p1","start":0,"end":8}]}]}
```
최대10장, 1:1 기본/4:5 선택, 전체 동일비율. 템플릿은 추후 주입. AI활용표시/엠바고/사진보류가 사라지면 안 됨. 게시 명령은 포함하지 않음.

## 그래픽 엔지니어
```json
{"schemaVersion":"0.1","sample":true,"title":"자료에서 확인한 수치","columns":[{"key":"period","label":"기간","type":"string"},{"key":"value","label":"값","type":"number","unit":"명"}],"rows":[{"period":"샘플 기간","value":10,"evidence":[{"sourceId":"sample-001","paragraphId":"p2","start":0,"end":10}]}],"limitations":["서로 다른 집계 기준을 합산하지 않음"]}
```
단위·모수·집계기간·원문 위치 필수. 누락치는0으로 채우지 않음. 비교 불가능한 자료는 분리.

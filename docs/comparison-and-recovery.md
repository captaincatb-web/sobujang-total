# 비교 적격성과 로컬 복구

2026-11-15 개발 보완. 운영 배포 승인과 별개.

## 재무 사실 검증과 비교 편입 분리

원문 확인·승인된 사실에도 `comparison_eligible=false`로 비교 보류를 지정할 수 있다. `metric_basis`는 `reported`(공시 원 지표), `adjusted`(조정), `issuer_defined`(발행사 별도 정의)를 기록한다. 새 필드는 승인 해시에 포함되므로 변경 시 정정 사실과 재검토가 필요하다. 공개 투영과 내보내기에서도 필드를 보존한다.

3개년 비교는 같은 법인·통화·기준의 정확한 6개 값, 매출/영업이익 기간 일치, 연간 기간, 회계기간 연속성, 같은 결산 월을 요구한다. 결합/분할 재무, 조정/별도 정의 지표와 운영자 보류는 비교하지 않는다. 원문 확인 상태와 비교 제외 사유는 별개다. 기존 사실의 필드 생략은 기존 공시 지표 정책과 호환되지만, 원문 검토를 대체하지 않는다.

`comparison_exclusions`는 승인된 재무가 있는 법인의 제외 사유만 반환한다. 미검증 금액은 포함하지 않는다. 브라우저는 이유를 한글로 표시하고, 금액은 Number 변환 없이 십진 문자열로 표시하여 큰 정수·소수의 자릿수를 보존한다.

9개월 재무는 기존 연간 공개 계약에서 여전히 승인 차단된다. 후보로 보존할 수 있으나 별도 비연간 공개 모델은 아직 구현하지 않았다.

## 백업·복구

저장소 밖의 기존 폴더에 새 파일명을 지정한다. Python의 SQLite backup API로 일관된 복사본을 만든다.

```bash
python scripts/console/backup.py backup ../sobujang-private/research.sqlite3 ../sobujang-private/backup-20261115.sqlite3
python scripts/console/backup.py restore ../sobujang-private/backup-20261115.sqlite3 ../sobujang-private/restored.sqlite3
python scripts/console/server.py --database ../sobujang-private/restored.sqlite3
```

기존 파일 덮어쓰기와 저장소 내부 경로는 차단한다. 새 파일 권한은 POSIX 0600이며, SQLite integrity_check, foreign_key_check와 저장된 원문 바이트 SHA-256을 검사한다. DB 소유자에 대한 변조 방지나 암호화 기능은 아니다. 복구 후 기존 파일을 자동 삭제하지 않는다.

## 검증

unittest 87건 통과. 기간 단절·9개월·조정 지표·운영자 보류·미승인 제외·공개 투영 보존·잘못된 필드 승인 차단·백업 왕복·덮어쓰기 차단·실패 파일 정리를 포함한다. 실제 로컬 조사 DB 백업도 integrity=ok로 완료했다. 원본 DB와 백업은 공개 저장소에 올리지 않았다.

전수 공시 대조·사업장 좌표 확보·지도 군집화·실제 모바일 화면 검증은 이 변경으로 완료되지 않는다.

# 재무 검증 기반 v1

## 범위와 현재 상태

이 단계는 신규 플랫폼의 오프라인 검증 기반이다. 웹 UI, DB, 사용자 인증, 검토자 권한, 실제 공시 수집 실행, 환율 변환 및 3개년 집계 출력은 아직 연결하지 않았다. 기존 Sangsaengnews의 공개 데이터나 배포를 변경하지 않는다.

기존 수집 CSV 반입기는 필수 정보·유한 양수 단위·금액 범위를 검사하고 원문 숫자/단위를 보존한다. 모든 반입 행은 `unverified`로 시작한다. 이 상태 열을 추가했다고 기존 집계기가 자동으로 공개를 차단하는 것은 아니다. 기존 집계기에는 연결하지 않았으며, 향후에는 아래 게이트를 통과한 출력만 새 공개 경로로 보내야 한다.

## 파일

- `scripts/growth/ingest_overseas_csv.py`: 기존 반입기 보강. CSV 형식 호환, 증빙/기준/통화 검증, 원문 값 보존.
- `scripts/growth/common.py`: 원본 파일 읽기 및 기존 이름 키 호환 기능. 이름 키는 법인 확정 식별자가 아니며 후속 DB 단계에서 매핑한다.
- `scripts/growth/verified_release.py`: 별도의 엄격한 사실 계약과 승인 검증. 표준 라이브러리만 사용.
- `tests/`: 실재 기업 재무값을 생성하지 않는 합성 입력 및 기존 반입기 회귀시험.
- `.github/workflows/validation.yml`: Python 3.11/3.12 검사만 수행. 배포 권한/단계 없음.

## 사실 계약

문자열 필수: fact_id, entity_id, reporting_entity_id, metric, accounting_standard, fiscal_year_label, period_start, period_end, scope, currency, raw_value, raw_unit, unit_multiplier, value_native, document_id, document_sha256, source_url, retrieved_at, reported_or_derived, verification_status.

추가 필수: fiscal_end_year(정수), source_locator(객체).

- metric: revenue / operating_income.
- scope: standalone / consolidated / combined / carve_out. 동일 보고주체에 여러 기준을 한 릴리스로 혼합하지 않는다.
- 비교연도는 종료일의 연도 2023/2024/2025. 기업의 FY 이름은 별도 문자열로 보존.
- 양끝 날짜를 포함해 350~380일인 기간만 이 연간 릴리스에 허용. 9개월 결산은 삭제하지 말고 상위 저장소에서 별도 보존한다.
- 원문 금액·단위 배율·정규화 금액은 쉼표 없는 십진 문자열. float 입력, NaN/Infinity, 지수 문자열은 거부한다.
- value_native = raw_value × unit_multiplier를 Decimal로 대조한다. 단위는 양수여야 한다. raw_unit은 원문 단위 텍스트이며 배율과의 의미적 일치까지 사람 또는 상위 파서가 확인해야 한다.
- currency는 대문자 3자리 형식만 검사한다. ISO 통화 실재 여부 및 문서와의 일치는 후속 공식 메타데이터 검증 범위다.
- 문서 해시는 소문자 SHA-256. 실제 파일을 다시 해싱하거나 URL을 접속하는 기능은 이 단계에 없다.
- URL은 HTTPS, 정확히 허용된 호스트만 허용한다. 하위 도메인은 각각 등록한다. URL 형식/호스트 통과가 원문 사실성 증명은 아니다.
- PDF: type, page(물리 페이지, 양의 정수), table, row, column.
- XBRL: type, concept, context, unit, dimensions({}). 세그먼트 사실은 지원하지 않는다.
- HTML: type, table, row, column.

## 승인과 공개 후보

신뢰할 수 있는 운영자가 `reviews` 및 `official_hosts`를 입력해야 한다. 조사자가 임의로 제출한 승인 manifest를 신뢰해서는 안 된다.

승인은 fact_id, fact_sha256, status=approved, reviewer, reviewed_at(시간대 포함)을 가진다. fact_sha256은 `digest(fact)`로 계산하며 원문 위치를 포함한 모든 필드를 결속한다. 값/출처/메모가 바뀌면 재승인이 필요하다. 해시는 전자서명이 아니며 검토자 신원을 인증하지 않는다. 이 API를 인증 없는 승인 서비스로 노출하지 않는다.

`build_release`는 한 건이라도 실패하면 전체 릴리스를 거부한다. 부분 성공으로 기존 데이터셋이 축소되는 일을 피한다. 동일 활성 사실, 중복 승인, 동일 보고주체 내 기준 혼재, 같은 종료연도에서 기간·통화·문서·회계기준 불일치를 차단한다.

출력은 명시한 필드만 투영한다. 내부 법인 ID, 검토자, 임의 메모 및 locator의 추가 필드는 제외한다. 허용 필드 내부의 문장/URL에 민감한 정보가 없는지 검토하는 별도 정책은 후속 단계에서 추가해야 한다. 공개용 기업 ID 매핑도 아직 없으므로 이 출력을 바로 기업 화면에 연결하지 않는다.

개별 승인 사실은 보존할 수 있으므로 3개년 또는 영업이익이 없는 경우 자체를 거부하지 않는다. 이 결과는 3개년 완전 패널이나 비교 합계가 아니다. 추정·보간·대체·환산·자동 승인 기능은 없다.

## 실행

```bash
python -m unittest discover -s tests -v
python scripts/growth/verified_release.py /absolute/private/release-input.json
```

입력 JSON의 최상위 필드: facts(배열), reviews(배열), official_hosts(배열). CLI는 상태·건수·오류 코드만 출력한다. 출력 파일을 생성하지 않으며 성공 0, 실패 1을 반환한다. 실제 입력은 저장소 밖에 둔다.

반입기를 실제 실행하려면 별도로 requests가 필요하며, 엑셀 로딩에는 openpyxl이 필요하다. 오프라인 테스트에는 둘 다 필요하지 않다. 이번 단계에서 실제 공시/API 호출은 하지 않았다.

## 재사용 출처

원본 저장소: https://github.com/captaincatb-web/Sangsaengnews
기준 커밋: e3542af0525f397768dcccaf63390b1f725fb91a

- scripts/growth/common.py: 원본 재사용.
- scripts/growth/ingest_overseas_csv.py: 위 원본에서 검증 보강 및 원문 필드 추가.
- tests/test_growth_ingest.py: 원본 회귀시험 재사용.
- verified_release.py 및 test_verified_release.py: 신규 작성.

다음 단계: 안정 법인 ID/증빙 DB → 수집 어댑터 → 인증된 검토·승인 이력 → 목업 기반 콘솔 → 사업장 지도 → 기존 JSON 호환 출력. 운영 연결과 배포는 별도 승인 대상이다.

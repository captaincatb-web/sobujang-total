# 로컬 조사 DB v1

## 구현 범위

`research_store.py`는 저장소 밖 SQLite에 기업·식별자·모집단·원문·재무 사실·검토·릴리스·사업장·감사 이력을 보존하는 신뢰된 로컬 운영자용 API입니다. 공개 웹 API나 다중 사용자 인증 서비스가 아닙니다. 운영 서버에 노출하지 않습니다.

```bash
mkdir -m 700 /path/to/private-research
python scripts/growth/research_store.py /path/to/private-research/research.sqlite3
python -m unittest discover -s tests -v
```

첫 명령은 빈 DB를 초기화하며 이후 실행은 기존 DB를 열어 테이블별 건수만 출력합니다. 부모 디렉터리는 운영자가 미리 생성합니다. DB 파일은 0600으로 설정하며 저장소 내부 경로와 그 경로를 가리키는 심볼릭 링크는 거부합니다. DB는 암호화되지 않습니다. 실제 비공개 자료 반입은 승인된 환경에서만 수행합니다.

## 데이터 모델

| 테이블 | 역할 |
|---|---|
| entity | 이름·국가와 독립적인 UUID 법인 ID |
| identifier | DART/CIK/EDINET/거래소별 문자열 식별자; namespace/value 고유 |
| population, membership | 모집단 버전별 포함/보류/제외·사유; 모집단 간 자동 합치기 없음 |
| document | URL·수집일·원문 바이트·실제 SHA-256; URL/해시 고유 |
| entity_relation | 모회사/자회사·지점 관계와 문서·표 근거 |
| site | 운영 법인과 연결된 본사/공장/연구소/서비스/영업 사업장; 원문/정규화 주소, 좌표 정밀도 |
| fact | 불변 재무 사실 버전, 원문 연결, 원문 상태 unverified, supersedes 연결 |
| review | 순번 기준 검토 이벤트: approved/rejected/revoked, 검토자·사유·시간·승인 대상 해시 |
| release, release_item | 불변 공개 후보 manifest, 사실·승인 이벤트 연결; 자동 게시 아님 |
| audit_event | 쓰기 작업과 같은 트랜잭션에서 기록하는 감사 이력 |

기업명 일치로 병합하지 않으며 종목코드는 정수가 아닌 문자열로 보관합니다. 같은 법인이 여러 모집단/사업장에 참여할 수 있습니다. 원문에서 확인하지 못한 주소 좌표는 null로 두며 사업장 입력은 모두 unverified입니다. 현재 사업장 승인/지도 내보내기는 구현하지 않았습니다.

## 사용 흐름

1. `ResearchStore(path)`로 외부 DB를 열고 `add_entity`, `add_identifier`, `add_population`, `add_membership`으로 조사 구조를 만듭니다.
2. `add_document(url, body, retrieved_at, actor, official_hosts)`는 전달된 원문 bytes를 저장하고 SHA-256을 직접 계산합니다. 이 모듈은 원문을 다운로드하지 않습니다.
3. `add_fact(fact, actor, supersedes=None)`는 사실의 문서 ID/URL/수집일/해시가 저장된 원문과 일치하는지 확인하고, 입력 verification_status와 무관하게 unverified로 보존합니다. 미완성 조사 사실은 보존할 수 있으나 승인할 수 없습니다.
4. `review_fact(id, status, reviewer, reason, official_hosts)`는 승인 시 계약 검사를 수행하고 source_verified 상태를 반영한 사실 전체의 해시를 검토 이벤트에 결속합니다. 실제 원문 숫자 대조는 운영자의 책임입니다.
5. `create_release(fact_ids, actor, official_hosts)`는 최신 검토 이벤트, 원문 바이트 해시, 사실 해시, 중복·기준·기간·통화·문서 정합성을 확인합니다. 하나라도 실패하면 후보 생성 전체를 롤백합니다.
6. 정정값은 새 fact_id와 supersedes로 추가합니다. 기존 사실/승인은 지우지 않습니다. 후속 버전이 생긴 원본 사실은 다시 승인·릴리스하지 못합니다. 새 사실은 별도 승인이 필요합니다.
7. revoked 또는 rejected가 최신 이벤트이면 신규 릴리스 생성이 차단됩니다. 과거 릴리스는 역사적 기록으로 남습니다.

## 공개 및 보안 경계

- 모든 테이블의 UPDATE/DELETE는 트리거로 금지합니다. 변경은 새 버전/이벤트를 추가하는 방식입니다. 다만 법인/주소/분류 정보 정정용 API는 후속 단계에 추가해야 합니다.
- SQL을 직접 관리할 수 있는 사용자는 트리거·스키마를 변경할 수 있습니다. 따라서 이 DB는 위변조 방지 원장이나 권한 시스템이 아닙니다.
- reviewer/actor는 신뢰된 로컬 운영자가 제공하는 이름이며 로그인 인증되지 않습니다. 다중 사용자 운영 시 서버 측 인증·역할·권한·정책을 추가해야 합니다.
- release manifest는 공개 후보이며 게시 작업을 수행하지 않습니다. 내부 법인 ID는 후보에서 제외되므로 공개용 기업 ID 매핑 및 3개년 패널 생성도 후속 작업입니다.
- 과거 release가 있다고 현재 공개 허용 상태라고 판단하면 안 됩니다. 게시 직전에 최신 검토/정정 상태를 다시 검사하는 배포 게이트가 필요합니다. 현재 게시/배포 경로는 없습니다.
- 승인된 사실도 3개년 데이터 완전성·모자회사 중복 합계·환율 검증을 모두 통과한 것은 아닙니다. 현재 결과는 원통화 연간 사실 단위입니다.
- 원문 바이트는 DB 안에 저장합니다. 대형 PDF, 백업·복원·압축·객체 저장소 이관·스키마 v2 마이그레이션은 아직 구현하지 않았습니다.

## 검증

17개 신규 DB 테스트: 승인/차단/철회, 원문 보존·해시 불일치, 동명이인 비병합, 식별자 중복, 모집단 분리, FK·감사 트랜잭션, 불변 테이블, 정정 재승인, 원문 결측, 부분 실패 롤백, 사업장 좌표·미확인 상태, 법인 관계, DB 재개방, 저장소 내부 경로 거부, 미래 스키마 거부.

실제 기업 자료는 사용하지 않습니다. 로컬 기존 37건 + 신규 17건 = 54건 통과. GitHub CI에서 Python 3.11/3.12를 별도로 검증합니다.

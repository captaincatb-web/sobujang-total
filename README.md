# 반도체 공급망 인텔리전스 · sobujang-total

기존 Sangsaengnews를 유지하면서 기업 조사·공시 재무 검증·사업장 지도를 연결하는 **로컬 운영자용 리서치 콘솔**입니다. 운영 사이트 배포본이 아닙니다.

## 구현 범위

- 목업의 네이비 사이드바·청록 강조를 반영한 기업 마스터, 상세, 재무 검토, 지도, 이력 화면
- 기존 마스터 189개(핵심160 + 별도관리29) 보존, ASML 원문 확인 사례 1개 추가
- 기존 [국내·글로벌 비교](https://captaincatb-web.github.io/Sangsaengnews/pair-compare.html)의 4개 JSON 재사용: 857개 검토 항목. 모드별 중복이 포함되어 **857개 기업이 아닙니다.**
- 법인 식별자·관계·사업장, 원문 바이트·해시, 정정 버전·승인·철회 이력 저장
- 회계기간·연결/개별·통화·원문 단위·URL·표 위치 검사와 미승인 내보내기 차단
- 3개년 6개 지표의 동일 기준 확인 후 원통화 실적·전년 대비 증감률 표시
- ASML 공식 2025 연차보고서 276쪽에서 2023–2025 매출·영업이익 6개 값 대조
- 사업장 등록 및 좌표 승인, 세계/대한민국 지도. 실제 승인 좌표는 현재 0건
- 배포 없는 Python 3.11/3.12 테스트 CI

## 실행

Python 3.11 이상. 콘솔·테스트는 외부 Python 패키지 없이 실행합니다.

```bash
# 저장소 밖의 개인 작업 폴더를 먼저 만듭니다.
mkdir -p ../sobujang-private
python scripts/console/server.py --database ../sobujang-private/research.sqlite3
```

터미널에 표시되는 `http://127.0.0.1:8765`를 열고 세션 키를 입력합니다. 키는 실행마다 바뀌며 브라우저 메모리에서만 사용합니다. DB가 비어 있으면 기존 기업 마스터를 반입합니다. 기존 재무 자료는 아래 명령으로 별도 반입합니다.

```bash
python scripts/console/fetch_legacy.py ../sobujang-private/legacy
python scripts/console/legacy_compare.py --database ../sobujang-private/research.sqlite3 --directory ../sobujang-private/legacy
```

고정 커밋의 원본을 저장소 밖에 내려받습니다. 기존 파일은 덮어쓰지 않으며 재반입은 해시로 구분합니다. 원화 환산값은 원통화로 역산하지 않습니다. 기존 검증 문구를 새 승인으로 자동 승계하지 않습니다.

### 입력 없는 읽기 전용 화면

```bash
python scripts/console/server.py --preview
```

커밋된 공개 검토 스냅샷만 읽습니다. 미검증 재무 숫자·원문 바이트·내부 검토자·메모는 포함하지 않습니다. 입력과 승인 기능은 로컬 DB 모드에서 사용하세요.

### ASML 원문 재현

[공식 PDF](https://ourbrand.asml.com/m/71076aaad607de4d/original/asml-2025-annual-report-based-on-us-gaap.pdf)를 저장소 밖에 저장합니다. `pdftotext`(Poppler)가 필요합니다.

```bash
python scripts/console/import_asml.py --database ../sobujang-private/research.sqlite3 --pdf ../sobujang-private/asml-2025.pdf
```

기본 반입 상태는 미승인입니다. 정확히 일치하는 문서 해시, 276쪽 표명·연도·단위·수치 행을 검사합니다. 원문 시각 대조를 수행한 운영자만 `--approve-source-checked` 옵션을 사용합니다. 이미 철회된 사실은 재실행으로 자동 승인하지 않습니다.

```bash
python -m unittest discover -s tests -v
node --check console/app.js
```

## 문서

- [구현·검증 결과와 남은 데이터 작업](docs/console-delivery.md)
- [기업·증빙·검토 이력 DB](docs/research-store.md)
- [재무 검증 계약과 기존 코드 재사용](docs/financial-contract.md)

## 운영 경계

단일 신뢰 운영자의 로컬 앱입니다. 역할별 로그인·다중 사용자 권한·외부 호스팅용 서버가 아닙니다. 원문 대조는 자동 산식 검사를 통과했다는 사실만으로 대체되지 않습니다. SQLite 해시와 append-only 트리거는 DB 소유자에 대한 변조 방지나 검토자 인증을 보장하지 않습니다.

공개 사이트와 수집·배포 Actions는 변경하지 않았습니다. PR #1 → #2 → 콘솔 PR 순서의 검토가 필요하며, main 병합·배포·기존 데이터 삭제는 별도 승인 이후에 진행합니다.

# 홈택스 신고서류 다운로드 + 네이버 메일 발송 — 설계안

> **상태:** 설계 완료 (구현 전). 본 문서는 코드 변경 없이 아키텍처·로직·기술 스택을 정리한 것이다.
> **작성일:** 2026-07-16
> **관련:** Phase 10 홈택스 원천세 신고(`src/workflows/hometax.py`)의 후속 단계

> **📌 이어서 작업하는 경우 (구현자/에이전트용):** [§11. 구현 가이드](#11-구현-가이드--이-문서만으로-이어서-작업하기-위한-절차)부터 보세요.
> 정확한 코드 골격, 파일:행 참조, 체크리스트가 있어 이 문서만으로 구현 가능합니다.
> [§11.9 체크리스트](#119-구현-순서-체크리스트-완료-표시용)와 [§11.10 참조 인덱스](#1110-기존-코드-참조-인덱스-구현-중-참고할-파일)를 특히 참고.

---


## 1. 목표

홈택스 원천세 신고(Phase 10) 완료 후, **수임처별로 접수증/납부서를 다운로드하여 네이버 메일로 1:1 발송**하는 신규 Phase 11을 추가한다. 회계법인 실무의 마지막 마일 자동화.

## 2. 확정된 결정사항 (사용자 응답 반영)

| 항목 | 결정 | 비고 |
|------|------|------|
| 메일 발송 방식 | **SMTP 직접 발송** (smtplib, `smtp.naver.com:587`, 네이버 앱 비밀번호) | stdlib만 사용, requirements.txt 변경 없음 |
| 수임처 이메일 저장 | **DB 스키마 마이그레이션** (`clients.email` 컬럼, v3→v4) | 스크래퍼가 긁어오지 않는 수동 입력 필드 |
| 발송 단위 | **수임처별 1:1 개별 발송** | 각 수임처의 서류만 해당 수임처 메일로 |
| 메뉴 구성 | **별도 Phase 11** (Phase 10과 분리) | 접수증 다운로드 + 메일 발송 모두 11번에서 처리 |
| 네이버 인증 | **실행 시마다 입력** | 디스크 저장 X, 발송 후 메모리에서 즉시 삭제 |
| 안전장치 | **건별 [y/n] 확인 프롬프트** | 수임처 N개 = N번 확인 |

---

## 3. 아키텍처 개요

5개 계층, 신규 4개 + 수정 5개 파일. 각 계층은 독립적으로 테스트 가능하다.

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: GUI (PhaseSidebar 동적 생성, registry 패턴)         │
│  main_window.py: phase 11 import + UI 분기                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Layer 4: 워크플로우 어댑터 — Phase 11 (email_receipt.py)    │
│  steps: find_receipt → download_receipt → send_email         │
└──────┬───────────────────────────────────────┬──────────────┘
       │                                       │
┌──────▼──────────────────────┐  ┌─────────────▼──────────────┐
│ Layer 2: 홈택스 다운로드     │  │ Layer 3: 메일 발송 엔진    │
│ _download.py (Playwright+CDP)│  │ mailer.py (smtplib)        │
│ + cdp_download.py (공통 유틸) │  │ 네이버 SMTP / HTML 본문    │
└──────┬──────────────────────┘  └─────────────┬──────────────┘
       │ PDF 저장                                │ 첨부 PDF 수집
       ▼                                        ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: 데이터 — save_path.py 산출물 경로                    │
│ 원천전자신고_{YYYYMM}/{수임처}/접수증_{수임처}_{YYYYMM}.pdf    │
│                                                              │
│ + DB 스키마 — clients.email (v3→v4 마이그레이션)              │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. 계층별 상세 설계

### Layer 1: 데이터 (스키마 마이그레이션 + 산출물 경로)

#### 4.1.1 DB 스키마 — `clients.email` 컬럼 추가

**대상 파일:** `src/batch/db.py`, `src/batch/models.py`

- `SCHEMA_VERSION` 3 → 4
- `SCHEMA_SQL`의 clients CREATE 문에 추가:
  ```sql
  email TEXT DEFAULT '',   -- 수임처 신고서류 수신 이메일 (수동 입력. 새로가져오기 시 보존)
  ```
- `_ensure_schema()`에 v3→v4 마이그레이션:
  ```sql
  ALTER TABLE clients ADD COLUMN email TEXT DEFAULT '';
  UPDATE schema_version SET version = 4;
  ```
- `Client` dataclass(`models.py`)에 `email: str = ""` 추가
- `_row_to_client` 인덱스 매핑 확장 (`row[11]`)

**email 보존 정책 (핵심):**
- 스크래퍼(`get_clients_with_biz_from_taxagent`)는 email을 긁어오지 않는다.
- "새로가져오기"는 DELETE+INSERT이므로 email이 매번 빈 값으로 리셋된다.
- → `replace_clients_preserving_mgmt` 패턴을 참고해 email도 snapshot 복원 로직 추가 필요.
- `upsert`의 UPDATE 분기는 email을 덮어쓰지 않는다 (스크래퍼 경로에서 호출되므로). email은 별도 `update_email(id, value)` 메서드로만 갱신.

**새 메서드:** `ClientRepository.update_email(client_id, value) -> bool`
- `update_management_number`/`update_report_cycle`와 동일한 패턴 (id 기반 단일 UPDATE).

#### 4.1.2 GUI 수임처 테이블 — 이메일 컬럼

**대상 파일:** `src/ui/widgets/company_table.py`

- 테이블에 "이메일" 컬럼 추가 (관리번호/신고주기 편집 패턴 재사용)
- 셀 더블클릭 → 편집 → `update_email(id, value)` 호출
- `get_all_clients()` 반환 딕셔너리에 `email` 키 추가

#### 4.1.3 산출물 경로 (기존 패턴 준수, 변경 없음)

이미 `src/utils/save_path.py:make_save_dir()`이 정해놓은 컨벤션:
```
<바탕화면>/원천전자신고_{YYYYMM}/{수임처명(공백→_)}/접수증_{수임처명}_{YYYYMM}.pdf
```
- Phase 10(hometax.py)과 Phase 9(wehago_swer.py)가 같은 `원천전자신고_{YYYYMM}/{수임처}/` 폴더 공유
- 메일 첨부 로직은 이 경로에서 `glob.glob("*접수증*.pdf")`로 수임처별 산출물 수집

---

### Layer 2: 홈택스 서류 다운로드 자동화

#### 4.2.1 CDP 다운로드 공통 유틸 추출 (리팩터링)

**신규 파일:** `src/utils/cdp_download.py`

기존 `src/automation/comwel/_download.py`와 `src/automation/nps/_download.py`에 **복제되어 있는** CDP 다운로드 헬퍼 4종을 공통 유틸로 추출:

| 함수 | 역할 |
|------|------|
| `setup_cdp_download(context, page, save_dir)` | `Browser.setDownloadBehavior` allowAndName 설정 |
| `wait_for_download(save_dir, before, timeout, label)` | `.crdownload` 폴링으로 다운로드 완료 대기 |
| `detect_format(path)` | 매직바이트로 PDF/XLSX/XLS 판별 |
| `rename_download(downloaded, save_dir, base_name)` | 형식 판별 후 `{base_name}{ext}`로 리네임 |

**리팩터 원칙:** 동작 보존. Comwel/NPS는 추출된 공통 유틸을 import하도록 변경 (선택적, Phase 11 구현과 독립적으로 진행 가능).

#### 4.2.2 홈택스 접수증/납부서 다운로드

**신규 파일:** `src/automation/hometax/_download.py`

```
download_receipt(ht, save_dir, client_name, year, month) -> str | None
```
- 홈택스 신고내역조회 메뉴 진입 → 해당 수임처 신고내역 → 접수증 팝업 → PDF 다운로드
- 네이밍: `접수증_{client_name}_{YYYYMM}.pdf`
- `cdp_download.py` 헬퍼 사용

**⚠️ 핵심 불확실성 (명시):**
홈택스 신고내역조회 화면의 정확한 DOM 구조(menu id, 접수증 팝업 선택자)는 현재 코드에 없다.
- `_constants.py`에 현재 menu id는 `#menuAtag_4106010000`(원천세 신고>일반신고) 단 하나뿐.
- 신고내역조회 메뉴 id는 별도 DOM 조사 필요.
- WebSquare 기반이라 기존 `_wait_and_click_popup`(text 정규식 기반) 패턴이 재사용 가능할 것으로 예상.

**해결 방법:** 구현 1단계에서 DOM 조사 스크립트(`_probe_receipt_dom.py`, `.gitignore` 대상)로 화면 구조 파악 후 선택자 확정.

---

### Layer 3: 메일 발송 엔진 (순수 Python, Qt 비의존)

**신규 파일:** `src/utils/mailer.py`

```python
def send_receipt_email(
    smtp_user: str,       # 네이버 ID (예: "rhee@naver.com" 또는 "rhee")
    smtp_pass: str,       # 네이버 2단계 인증 앱 비밀번호
    to_email: str,        # 수임처 수신 이메일
    client_name: str,     # 수임처명 (본문/제목에 사용)
    attachments: list[str],  # PDF 파일 경로 목록
    year: int,
    month: int,
    sender_name: str = "",   # 발송자 표시명 (선택)
    dry_run: bool = False,   # True면 발송 안 하고 로그만
) -> bool:
```

**네이버 SMTP 설정:**
- 호스트: `smtp.naver.com`
- 포트: `587` (STARTTLS)
- 인증: `login(smtp_user, smtp_pass)` — 앱 비밀번호

**메일 구성:**
- **제목:** `[원천징수 신고 완료] {수임처명} - {YYYY년 MM월분}`
- **본문:** HTML + 텍스트 폴백 (`email.mime.multipart`, `email.mime.text`)
  - 신고 연월, 수임처명
  - 첨부 파일 안내
  - 발송자(회계법인) 정보
- **첨부:** `email.mime.base.MIMEBase` + `base64` 인코딩 (PDF)

**설계 원칙:**
- **예외 비전파:** 발송 실패 시 `False` 반환 (한 수임처 실패가 전체 중단시키지 않게)
- **보안:** 비밀번호는 함수 인자로만 전달. 클래스 멤버에 저장하지 않음. 발송 후 호출자가 `del`.
- **의존성:** `smtplib`, `email.mime`은 **Python stdlib** → `requirements.txt` 변경 없음, 빌드에 영향 없음.

**발송량 제한 고지:**
- 네이버 메일 하루 발송 한도 500통.
- 현재 수임처 24개이므로 문제없으나, 확장 시 주의.

---

### Layer 4: 워크플로우 어댑터 — Phase 11

**신규 파일:** `src/workflows/email_receipt.py`

```python
@register(
    phase_id=11,
    portal="hometax",
    display_name="신고서류 메일 발송",
    needs_password=True,   # 네이버 비밀번호 필드 재활용 (UI 라벨만 "네이버 앱 비밀번호"로)
)
class EmailReceiptWorkflow(BaseWorkflow):
    steps = [
        {"name": "find_receipt",     "index": 0},  # 다운로드된 접수증 찾기
        {"name": "download_receipt", "index": 1},  # (미존재 시) 홈택스에서 다운로드
        {"name": "send_email",       "index": 2},  # 네이버 메일 발송
    ]
```

**`run_single` 흐름 (수임처별):**
1. `find_receipt`: `save_dir`에서 `glob.glob("*접수증*.pdf")` — 이미 다운로드된 접수증 찾기
2. `download_receipt` (조건부): 접수증이 없으면 `download_receipt()` 호출. 있으면 스킵.
3. `send_email`:
   - `kwargs.get("password")` → 네이버 앱 비밀번호 (UI 필드에서 전달)
   - 수임처 DB에서 `client.email` 조회 → 없으면 스킵 + 로그
   - `mailer.send_receipt_email()` 호출
   - `dry_run=True`면 발송 안 하고 로그만 (기본값 True — 다른 phase와 일관)

**인자 전달:**
- `password`: 네이버 앱 비밀번호 (needs_password UI 필드 재활용)
- `naver_id`: 네이버 ID (별도 UI 입력 또는 password 필드와 함께)
- `dry_run`: GUI 체크박스 (기본 True)
- `year`, `month`: 신고 연월

---

### Layer 5: GUI 통합

#### 4.5.1 사이드바 메뉴 추가

**대상 파일:** `src/ui/main_window.py`

- `_load_phases()`에 `import src.workflows.email_receipt` 한 줄 추가
- **이것만으로 사이드바에 Phase 11 버튼이 자동 생성됨** (registry 패턴)
- `_on_phase_selected`: phase 11일 때 needs_password 분기 → 네이버 ID/앱비밀번호 입력 필드 표시

#### 4.5.2 비밀번호 입력 UI

- 기존 `needs_password` UI(비밀번호 QLineEdit) 재활용
- 라벨을 phase 11일 때 "네이버 ID / 앱 비밀번호"로 동적 변경
- 입력값은 `kwargs["password"]`로 전달 → 메모리에만 존재, 디스크 저장 안 함

#### 4.5.3 활성화

**대상 파일:** `gui_main.py`
- 기존 패턴 준수 (별도 활성화 플래그가 있는지 확인 필요 — 대부분 registry 등록만으로 충분)

---

### Layer 6: 안전장치 (건별 확인)

**핵심 제약:** 자동화 배치 실행 중 Qt 메인 스레드를 차단할 수 없다.

**채택 방식 — 사전 승인 + dry_run 폴백:**
- Phase 11 실행 전 **1회 확인 다이얼로그**: "다음 N개 수임처에게 신고서류를 발송합니다. 모두 승인하시겠습니까? [y/N]"
- 승인 시: `dry_run=False`로 전체 발송
- 취소 시: `dry_run=True`로 폴백 (로그만 출력, 실발송 안 함)
- **N번 클릭 대신 1회 승인** (실행 흐름 단순화, UI 스레드 안전)

**발송 중 로깅:**
- `AutomationRunner`의 로그 시그널로 실시간 진행 표시
- 각 수임처별: "→ {수임처명} ({email}) 첨부: {파일명} ... [발송 완료/실패/skipped]"

---

## 5. 파일 변경 요약

| 파일 | 유형 | 계층 | 내용 |
|------|------|------|------|
| `src/batch/db.py` | 수정 | 1 | SCHEMA v4, email 컬럼, 마이그레이션, `update_email()`, `_row_to_client` |
| `src/batch/models.py` | 수정 | 1 | `Client.email` 필드 추가 |
| `src/ui/widgets/company_table.py` | 수정 | 1 | 이메일 컬럼 + 편집 |
| `src/utils/cdp_download.py` | 신규 | 2 | CDP 다운로드 공통 유틸 (Comwel/NPS에서 추출) |
| `src/automation/hometax/_download.py` | 신규 | 2 | 접수증/납부서 다운로드 |
| `src/utils/mailer.py` | 신규 | 3 | 네이버 SMTP 발송 엔진 |
| `src/workflows/email_receipt.py` | 신규 | 4 | Phase 11 어댑터 |
| `src/ui/main_window.py` | 수정 | 5 | phase import + UI 분기 |
| `gui_main.py` | 수정 | 5 | phase 11 활성화 (필요 시) |
| `_probe_receipt_dom.py` | 신규(임시) | 2 | 홈택스 접수증 DOM 조사 (`.gitignore` 대상) |

**총:** 신규 4개 + 수정 5개 + 임시 1개

---

## 6. 기술 스택 요약

```
[홈택스 다운로드]  Playwright + CDP(setDownloadBehavior) — 기존 패턴 재사용
       ↓ PDF 저장 (원천전자신고_{YYYYMM}/{수임처}/접수증_*.pdf)
[메일 본문]        email.mime.text/html (stdlib)
[메일 발송]        smtplib + STARTTLS (smtp.naver.com:587)
[수임처 매칭]      SQLite clients.email (DB 마이그레이션 v3→v4)
[GUI]              PhaseSidebar 동적 생성 (registry 패턴)
```

**외부 의존성 추가:** 없음 (smtplib, email.mime은 Python stdlib)

---

## 7. 구현 순서 (리스크가 낮은 것부터)

| 단계 | 작업 | 리스크 | 의존성 |
|------|------|--------|--------|
| 1 | DB 스키마 마이그레이션 (email 컬럼) | 낮음 | 독립적, 즉시 테스트 가능 |
| 2 | 메일 발송 엔진 (`mailer.py`) | 낮음 | 네이버 앱 비밀번호만 있으면 콘솔에서 바로 검증 |
| 3 | CDP 다운로드 공통 유틸 추출 | 중간 | 리팩터링 (기존 동작 보존 필수) |
| 4 | 홈택스 접수증 DOM 조사 (`_probe_*.py`) | **높음** | 화면 구조 파악 (핵심 불확실성) |
| 5 | 홈택스 다운로드 구현 (`_download.py`) | 높음 | 4단계 조사 결과 기반 |
| 6 | Phase 11 워크플로우 통합 | 중간 | 1~5 완료 후 |
| 7 | GUI 통합 (사이드바 + 이메일 편집) | 낮음 | 6 완료 후 |

---

## 8. 명시된 리스크 / 미해결 사항

### 🔴 높음
1. **홈택스 신고내역조회 화면의 DOM 구조 미상**
   - 구현 1단계에서 조사 스크립트로 확인 필요
   - WebSquare 기반이라 기존 text 정규식 패턴이 먹힐 것으로 예상하나, 화면 진입 menu id를 알아내야 함
   - 이것이 전체 일정의 병목

### 🟡 중간
2. **네이버 앱 비밀번호 발급**
   - 사용자 교육 필요 (USER_GUIDE 안내 추가)
   - 네이버 계정 설정 → 2단계 인증 → 앱 비밀번호 발급 (1회)
3. **SMTP 포트 587 방화벽**
   - 회사 네트워크에서 차단 시 웹메일 자동화(Playwright) 방식으로 폴백해야 할 수 있음 (향후 옵션)
4. **네이버 SMTP 발송량 제한**
   - 하루 500통. 현재 수임처 24개이므로 문제없으나, 확장 시 주의

### 🟢 낮음
5. **email 보존 (새로가져오기 시)**
   - `replace_clients_preserving_mgmt` 패턴으로 해결 가능 (이미 검증된 패턴)
6. **DB 마이그레이션 안전성**
   - 기존 v1→v2→v3 마이그레이션이 모두 안전하게 동작 중 (24개 수임처 데이터 보존)

---

## 9. 검증 계획

| 검증 항목 | 방법 | 통과 기준 |
|----------|------|----------|
| DB 마이그레이션 | 기존 DB로 실행 후 `SELECT count(*) FROM clients` | 24개 수임처 데이터 손상 없음 |
| email 컬럼 추가 | `PRAGMA table_info(clients)` | email 컬럼 존재, 기존 row는 '' |
| 메일 발송 (dry_run) | `mailer.send_receipt_email(..., dry_run=True)` | 본문/첨부 생성 확인, 실발송 안 됨 |
| 메일 발송 (실제) | 본인 메일로 1통 발송 테스트 | 정상 수신, 첨부 PDF 열람 가능 |
| 접수증 다운로드 | dry_run 홈택스 신고 상태에서 접수증 화면 진입 | 화면 진입 성공, 다운로드 버튼 식별 |
| Phase 11 통합 | dry_run 전체 흐름 실행 | 3단계 스텝 로그 정상, 실발송 안 됨 |

---

## 10. 향후 확장 옵션 (참고)

본 설계는 SMTP 방식을 채택했으나, 향후 필요시 대안이 가능하다:

| 대안 | 장점 | 단점 | 전환 시점 |
|------|------|------|----------|
| 웹메일 자동화 (Playwright) | SMTP/방화벽 문제 없음, 보낸편지함 보존 | 느림(~20s/건), UI 변경 취약 | 587 포트 차단 시 |
| Gmail API (도메인 메일) | 대량 발송, 이력 추적 | 네이버가 아닌 Gmail로 발송 | 발송량 500통 초과 시 |
| 메일 본문 템플릿화 | 수임처별 맞춤 안내 | 템플릿 관리 부담 | 요구사항 발생 시 |

---

## 11. 구현 가이드 — 이 문서만으로 이어서 작업하기 위한 절차

> 이 섹션은 구현자(또는 다른 에이전트 세션)가 본 문서만 보고 코드를 작성할 수 있도록
> **정확한 코드 골격, 시그니처, 파일 위치, 기존 패턴 참조**를 제공한다.

### 11.1 기존 아키텍처 배경지식 (반드시 먼저 읽을 것)

본 프로젝트는 **Phase(번호)로 식별되는 워크플로우**를 **레지스트리 패턴**으로 관리한다.

**새 Phase를 추가하는 표준 3단계 패턴:**
1. `src/workflows/<name>.py` 생성 — `BaseWorkflow` 상속 + `@register(phase_id=N, ...)` + `steps` + `run_single()`
2. `src/ui/main_window.py:_load_phases()`에 `import src.workflows.<name>` 한 줄 추가 (이것만으로 사이드바 버튼 자동 생성)
3. 완료 — capability 메타데이터(`needs_password` 등)가 UI 분기까지 자동 적용

**핵심 클래스/시그니처 (복사해서 쓸 것):**

```python
# BaseWorkflow.run_single 시그니처 (src/workflows/base.py:37-54)
async def run_single(
    self, page, context, client_name: str, job_id: int,
    state: StateManager, **kwargs,
) -> bool:
    """True=성공, False=실패"""
```

**스텝 패턴 (모든 워크플로우가 따름 — src/batch/state.py 참조):**
```python
if not state.should_skip_step(job_id, "step_name"):
    state.before_step(job_id, "step_name", <index>)
    # ... 자동화 로직 ...
    if not ok:
        state.fail_step(job_id, "step_name", "에러 메시지")
        return False
    state.after_step(job_id, "step_name", {"file": path})  # 부가데이터 저장
else:
    # 재실행 시 이미 완료된 단계의 결과 복원
    data = state.get_step_data(job_id, "step_name")
```

**kwargs에서 읽는 표준 인자들:**
- `year`, `month` — 신고 연월
- `dry_run` (기본 True) — True면 최종 제출/발송 안 함
- `password` — UI needs_password 필드에서 전달 (phase 7/8/9/10은 전자파일 비밀번호, phase 11은 네이버 앱 비밀번호로 재활용)

### 11.2 Layer 1 구현 — DB 스키마 마이그레이션

**파일: `src/batch/db.py`**

1. `SCHEMA_VERSION = 3` → `4` (33행 부근)

2. `SCHEMA_SQL`의 clients CREATE 문에 email 컬럼 추가 (report_cycle 뒤):
```sql
email TEXT DEFAULT '',   -- 수임처 신고서류 수신 이메일 (수동 입력. 새로가져오기 시 보존)
```

3. `_ensure_schema()`의 마이그레이션 블록 끝(report_cycle 마이그레이션 후)에 추가:
```python
if current_version < 4:
    # v3 → v4: clients.email (신고서류 수신 이메일) 컬럼 추가.
    self.conn.execute("ALTER TABLE clients ADD COLUMN email TEXT DEFAULT ''")
    self.conn.execute("UPDATE schema_version SET version = 4")
```

4. `_row_to_client` (ClientRepository, 463행 부근) 인덱스 매핑 확장:
```python
management_number=row[9] if len(row) > 9 and row[9] else "",
report_cycle=row[10] if len(row) > 10 and row[10] else "",
email=row[11] if len(row) > 11 and row[11] else "",  # 추가
```

5. **주의:** `upsert`의 UPDATE 분기는 email을 덮어쓰지 않는다 (스크래퍼 경로에서 호출되므로). email은 별도 메서드로만 갱신.

6. 새 메서드 추가 (`update_management_number` 패턴 복사, 387행 부근):
```python
def update_email(self, client_id: int, value: str) -> bool:
    """수임처 신고서류 수신 이메일 갱신 (GUI 편집용). id 기반 단일 UPDATE."""
    now = now_iso()
    self.db.begin()
    try:
        cur = self.db.conn.execute(
            "UPDATE clients SET email = ?, updated_at = ? WHERE id = ?",
            ((value or "").strip(), now, client_id),
        )
        self.db.commit()
        return cur.rowcount > 0
    except Exception:
        self.db.rollback()
        raise
```

7. `replace_clients_preserving_mgmt`(409행)에 email 보존 로직 추가 — 스크래퍼가 email을 안 긁어오므로 새로가져오기(DELETE+INSERT) 시 리셋 방지:
```python
# 기존 management_number snapshot 옆에 email snapshot도 추가
email_overrides = {
    n: e for n, e in self.db.conn.execute(
        "SELECT name, email FROM clients WHERE email != ''"
    ).fetchall()
}
# ... DELETE + INSERT 루프 안에서 ...
if new_id and c["name"] in email_overrides:
    self.update_email(new_id, email_overrides[c["name"]])
```

**파일: `src/batch/models.py`**

`Client` dataclass (89행 부근)에 필드 추가:
```python
report_cycle: str = ""          # 기존 마지막 필드
email: str = ""                 # 수임처 신고서류 수신 이메일 (수동 입력)
```

### 11.3 Layer 1 구현 — GUI 수임처 테이블 이메일 컬럼

**파일: `src/ui/widgets/company_table.py`**

관리번호/신고주기 편집 패턴(54-161행)을 그대로 복사해 email로 변환:

1. `CompanyTableModel`에 컬럼 상수 추가:
```python
_EMAIL_COL = 4  # 기존 컬럼 수에 맞춰 조정 (현재 0:이름 1:사업자번호 2:관리번호 3:신고주기)
```

2. `headerData`에 "이메일" 헤더 추가

3. `data()`에 `elif col == 4: return row_data.get("email", "")`

4. `setData()`에 email 편집 분기 추가 (management_number 분기 복사):
```python
elif col == self._EMAIL_COL:
    normalized = (value or "").strip()
    row_data["email"] = normalized
    self.email_changed.emit(client_id, normalized)
```

5. 시그널 추가: `email_changed = Signal(int, str)`

6. `CompanyTable` 위젯에서 시그널 릴레이 (273행 패턴):
```python
self.model.email_changed.connect(self.email_changed)
```

7. `get_all_clients()` 반환 딕셔너리에 `"email"` 키 추가

**파일: `src/ui/main_window.py`**

`email_changed` 시그널을 `db.clients.update_email`에 연결 (기존 `management_number_changed` 연결 패턴 검색해서 동일 위치에 추가).

### 11.4 Layer 2 구현 — CDP 다운로드 공통 유틸

**신규 파일: `src/utils/cdp_download.py`**

`src/automation/comwel/_download.py:58-110`의 4개 헬퍼를 그대로 복사 (함수명 앞 `_` 제거 권장):
- `setup_cdp_download(context, page, save_dir) -> (set, cdp_session)`
- `wait_for_download(save_dir, before, timeout, label) -> path | None`
- `detect_format(path) -> "pdf"|"xlsx"|"xls"|None`
- `rename_download(downloaded, save_dir, base_name) -> (final_path, fmt)`

**선택:** Comwel/NPS의 기존 헬퍼를 이 공통 유틸 import로 교체 (리팩터, 동작 보존 필수). Phase 11 구현과 독립적.

### 11.5 Layer 2 구현 — 홈택스 접수증 다운로드

**신규 파일: `src/automation/hometax/_download.py`**

**⚠️ 구현 전 필수:** DOM 조사 스크립트로 홈택스 신고내역조회 화면 구조 파악:
- 신고내역조회 메뉴 id (현재 `_constants.py`에는 `#menuAtag_4106010000` 일반신고만 있음)
- 접수증 팝업 선택자 (WebSquare `.w2popup_window` 패턴 — 기존 `_upload.py:_wait_and_click_popup` 재사용 예상)

```python
async def download_receipt(ht, save_dir, client_name, year, month) -> str | None:
    """홈택스 신고내역조회 → 접수증 PDF 다운로드.

    ht: Playwright page (hometax)
    반환: 저장된 PDF 절대경로, 실패 시 None
    """
    # 1. 신고내역조회 메뉴 진입 (menu id 조사 필요)
    # 2. 해당 수임처/연월 신고내역 선택
    # 3. 접수증 팝업 → '인쇄하기'/'PDF 저장' 클릭
    # 4. cdp_download.setup_cdp_download + wait_for_download + rename_download
    # 네이밍: 접수증_{client_name}_{YYYYMM}.pdf
```

**조사 스크립트 (`_probe_receipt_dom.py`, `.gitignore`에 `_probe_*.py` 패턴이 이미 있음):**
로그인된 홈택스에서 신고내역조회 화면 진입 후 DOM 덤프 → menu id, 팝업 선택자, 버튼 text 파악.

### 11.6 Layer 3 구현 — 메일 발송 엔진

**신규 파일: `src/utils/mailer.py`**

```python
"""네이버 메일 SMTP 발송 (stdlib 전용, Qt 비의존)."""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


NAVER_SMTP_HOST = "smtp.naver.com"
NAVER_SMTP_PORT = 587


def send_receipt_email(
    smtp_user: str,       # 네이버 ID ("rhee" 또는 "rhee@naver.com")
    smtp_pass: str,       # 네이버 2단계 인증 앱 비밀번호 (16자리)
    to_email: str,        # 수신자 이메일
    client_name: str,
    attachments: list[str],
    year: int,
    month: int,
    sender_name: str = "",
    dry_run: bool = False,
) -> bool:
    """접수증 메일 발송. 실패 시 False (예외 비전파).

    보안: smtp_pass 는 이 함수 인자로만 존재. 클래스 멤버에 저장하지 않음.
    발송 후 호출자가 del 할 것 (워크플로우에서 password kwargs 즉시 폐기).
    """
    if dry_run:
        # 본문/첨부 유효성만 확인, 실발송 안 함
        missing = [p for p in attachments if not os.path.exists(p)]
        return len(missing) == 0

    subject = f"[원천징수 신고 완료] {client_name} - {year}년 {month:02d}월분"
    html_body = f"""<html><body>
<p><strong>{client_name}</strong> 귀하,</p>
<p>{year}년 {month}월분 원천징수 신고가 완료되어 접수증을 첨부합니다.</p>
<p>첨부 파일: {len(attachments)}건</p>
<p>문의사항이 있으시면 연락 주시기 바랍니다.</p>
<p>{sender_name or ''}</p>
</body></html>"""
    text_body = f"{client_name} 귀하,\n{year}년 {month}월분 원천징수 신고 접수증 첨부합니다."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user if "@" in smtp_user else f"{smtp_user}@naver.com"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 첨부 (multipart/mixed 로 변경 필요 — 위를 MIMEMultipart("mixed")로 감싸는 구조로 조정)
    for path in attachments:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            f'attachment; filename="{os.path.basename(path)}"')
            msg.attach(part)

    try:
        with smtplib.SMTP(NAVER_SMTP_HOST, NAVER_SMTP_PORT, timeout=30) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        return True
    except Exception:
        return False
```

**주의:** 위 골격의 `MIMEMultipart("alternative")` + 첨부 조합은 본문과 첨부를 함께 보낼 때 구조 조정이 필요하다 — `MIMEMultipart("mixed")` 최상위 아래에 `alternative`(본문)와 첨부들을 attach하는 중첩 구조로 구현할 것. 단위테스트로 본문만/첨부만/둘 다 케이스 검증.

### 11.7 Layer 4 구현 — Phase 11 워크플로우

**신규 파일: `src/workflows/email_receipt.py`**

`src/workflows/hometax.py`를 템플릿으로 사용. 구조 동일.

```python
"""Phase 11: 신고서류 메일 발송 어댑터"""
import os
import glob

from src.utils.save_path import make_save_dir
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=11,
    portal="hometax",
    display_name="신고서류 메일 발송",
    needs_password=True,   # UI 비밀번호 필드 → 네이버 앱 비밀번호로 재활용
)
class EmailReceiptWorkflow(BaseWorkflow):
    steps = [
        {"name": "find_receipt",     "index": 0},
        {"name": "download_receipt", "index": 1},
        {"name": "send_email",       "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        year = kwargs.get("year")
        month = kwargs.get("month")
        dry_run = kwargs.get("dry_run", True)
        save_dir = make_save_dir("원천전자신고", client_name, year=year, month=month)

        # [0] 접수증 찾기 (이미 다운로드된 것)
        receipt_path = ""
        if not state.should_skip_step(job_id, "find_receipt"):
            state.before_step(job_id, "find_receipt", 0)
            matches = glob.glob(os.path.join(save_dir, "*접수증*.pdf"))
            if matches:
                receipt_path = max(matches, key=os.path.getmtime)
            state.after_step(job_id, "find_receipt", {"path": receipt_path})
        else:
            data = state.get_step_data(job_id, "find_receipt")
            receipt_path = data.get("path", "")

        # [1] 접수증이 없으면 홈택스에서 다운로드
        if not receipt_path or not os.path.exists(receipt_path):
            if not state.should_skip_step(job_id, "download_receipt"):
                state.before_step(job_id, "download_receipt", 1)
                from src.automation.hometax._download import download_receipt
                ht = page
                path = await download_receipt(ht, save_dir, client_name, year, month)
                if not path:
                    state.fail_step(job_id, "download_receipt", "접수증 다운로드 실패")
                    return False
                receipt_path = path
                state.after_step(job_id, "download_receipt", {"path": path})

        # [2] 메일 발송
        if not state.should_skip_step(job_id, "send_email"):
            state.before_step(job_id, "send_email", 2)

            # 수임처 이메일 조회 (DB) — client_id 가 kwargs 에 있는지 확인 필요
            # automation_runner.py:269-286 패턴에서 client_id 전달 여부 검증
            client_id = kwargs.get("client_id")
            email = ""
            if client_id:
                from src.config import DB_PATH
                from src.batch.db import BatchDB
                with BatchDB(DB_PATH) as db:
                    client = db.clients.get(client_id)
                    email = client.email if client else ""

            if not email:
                # 이메일 미등록 — 스킵 (실패 아님)
                state.after_step(job_id, "send_email", {"skipped": "no_email"})
                return True

            from src.utils.mailer import send_receipt_email
            naver_id = kwargs.get("naver_id", "")
            naver_pass = kwargs.get("password", "")  # UI needs_password 필드 재활용

            ok = send_receipt_email(
                smtp_user=naver_id, smtp_pass=naver_pass,
                to_email=email, client_name=client_name,
                attachments=[receipt_path], year=year, month=month,
                dry_run=dry_run,
            )
            # 보안: 비밀번호 즉시 폐기 (kwargs에서 이미 가져왔으므로 지역 변수만 del)
            del naver_pass

            if not ok:
                state.fail_step(job_id, "send_email", "메일 발송 실패")
                return False
            state.after_step(job_id, "send_email", {"to": email})

        return True
```

**구현 시 검증 필요 포인트:**
- `automation_runner.py:269-286`에서 `client_id`가 kwargs로 전달되는지 확인 (전달되지 않으면 별도 조회 경로 필요)
- `naver_id` 입력 UI가 필요 — 현재 `needs_password`는 password 1개 필드만 제공. naver_id+password 2개 필드가 필요하므로 main_window UI 분기 추가 또는 password 필드를 "id:password" 형식으로 인코딩

### 11.8 Layer 5 구현 — GUI 통합

**파일: `src/ui/main_window.py`**

1. `_load_phases()` (242행)에 import 추가:
```python
import src.workflows.email_receipt  # noqa: F401
```
→ 이것만으로 Phase 11 사이드바 버튼 자동 생성.

2. `_on_phase_selected` (313행)에서 phase 11 분기 — naver_id 입력 필드 표시:
```python
# needs_password 분기 안에서 phase 11일 때 라벨/플레이스홀더 변경
if phase_id == 11:
    self.password_label.setText("네이버 ID : 앱비밀번호")
    # 또는 naver_id 전용 QLineEdit 추가
```

3. `_on_start` (553행)에서 kwargs에 naver_id 추가:
```python
if self._selected_phase == 11:
    start_kwargs["naver_id"] = self.naver_id_input.text()
```

### 11.9 구현 순서 체크리스트 (완료 표시용)

구현 시 각 단계를 완료할 때마다 체크:
- [ ] 1. db.py: SCHEMA v4 + email 컬럼 + 마이그레이션 + `update_email()` + `_row_to_client`
- [ ] 2. models.py: `Client.email` 필드
- [ ] 3. company_table.py: 이메일 컬럼 + 편집 + `email_changed` 시그널
- [ ] 4. main_window.py: `email_changed` → `update_email` 연결
- [ ] 5. `python -c "from src.batch.db import BatchDB; BatchDB('data/withholding_tax.db').connect()"` 로 마이그레이션 테스트
- [ ] 6. mailer.py: 발송 엔진 + dry_run 단위테스트
- [ ] 7. cdp_download.py: 공통 유틸 추출 (선택)
- [ ] 8. _probe_receipt_dom.py: 홈택스 접수증 DOM 조사 (핵심 병목)
- [ ] 9. hometax/_download.py: 접수증 다운로드 구현
- [ ] 10. workflows/email_receipt.py: Phase 11 어댑터
- [ ] 11. main_window.py: phase 11 import + UI 분기 + naver_id 필드
- [ ] 12. gui_main.py: phase 11 활성화 (필요 시)
- [ ] 13. 통합 dry_run 테스트

### 11.10 기존 코드 참조 인덱스 (구현 중 참고할 파일)

| 참고할 패턴 | 파일:행 | 본 기능에서의 용도 |
|------------|---------|-------------------|
| `BaseWorkflow` + `@register` | `src/workflows/hometax.py:12-28` | Phase 11 어댑터 골격 |
| 스텝 4-콜 패턴 | `src/workflows/hometax.py:44-125` | run_single 내부 구조 |
| CDP 다운로드 헬퍼 4종 | `src/automation/comwel/_download.py:58-110` | `cdp_download.py` 추출 원본 |
| `_wait_and_click_popup` (text 정규식) | `src/automation/hometax/_upload.py:200-222` | 접수증 팝업 처리 재사용 |
| `make_save_dir` 산출물 경로 | `src/utils/save_path.py:67-127` | 접수증 저장 경로 |
| `update_management_number` (id 기반 UPDATE) | `src/batch/db.py:387-407` | `update_email` 패턴 원본 |
| `replace_clients_preserving_mgmt` (snapshot 복원) | `src/batch/db.py:409-435` | email 보존 로직 원본 |
| company_table 편집 시그널 | `src/ui/widgets/company_table.py:54-161` | email 컬럼 편집 패턴 |
| `get_all_clients()` 딕셔너리 | `src/ui/widgets/company_table.py:172-195` | email 키 추가 위치 |
| needs_password UI 분기 | `src/ui/main_window.py:313-349` | phase 11 naver_id 필드 |
| kwargs 전달 (year/month/dry_run) | `src/ui/main_window.py:553-619` | naver_id 전달 추가 |
| DB 경로 상수 | `src/config.py:27-31` | `BatchDB(DB_PATH)` 사용 |
| StateManager 4-콜 | `src/batch/state.py:43-81` | 스텝 체크포인트 |

---

## 부록: 사용자 액션 필요 항목 (구현 전)

구현 시작 전 사용자가 준비해야 할 것:

1. **네이버 앱 비밀번호 발급** (1회)
   - 네이버 계정 관리 → 2단계 인증 설정 → 앱 비밀번호 발급
   - 발급된 16자리 비밀번호를 메일 발송 시 입력 (디스크에 저장되지 않음)

2. **수임처 이메일 일괄 입력** (1회, 24건)
   - Phase 11 활성화 후 GUI 수임처 테이블의 "이메일" 컬럼에 각 수임처 수신 메일 입력
   - DB에 영속 저장되어 이후 자동화에서 자동 사용

3. **(구현 4단계) 홈택스 신고내역조회 화면 접근 권한**
   - DOM 조사 스크립트 실행을 위해 신고 완료 상태의 홈택스 계정 필요

# Hometax 자동화 진행 상황

## 파일 위치
- `src/automation/hometax/hometax_auto_cdp.py` — 메인 자동화 스크립트

## 기술 스택
- **Playwright + CDP** (Chrome DevTools Protocol)
- Chrome을 `--remote-debugging-port=9222`로 실행 후 Playwright로 연결
- **Human-in-the-loop**: 홈택스 로그인은 사용자가 수동으로 완료

## 자동화된 프로세스 (6단계)

### [1] 원천세 신고 > 일반신고 이동
- `goto_withholding_tax()`: `#menuAtag_4106010000` 메뉴 클릭

### [2] 파일변환신고 이동
- `goto_file_convert()`: `[id*="btn_cbcMediRtn"]` 버튼 클릭
- 스크롤 후 클릭 (버튼이 화면 하단에 위치)
- 이동 후 알림 모달 자동 닫기 (`dismiss_modals`)

### [3] 파일 선택
- `select_file()`: iframe 내 hidden `<input type="file">` 에 직접 파일 설정
- **핵심**: 홈택스 WebSquare가 `<input type="file">`을 iframe에 숨겨둠
- 파일선택 버튼(`#btn_selFileB`) 클릭 시 네이티브 파일 다이얼로그가 열려 제어 불가
- iframe 로드까지 최대 30초 대기 후 `set_input_files()`로 파일 설정

### [4] 파일검증하기
- `verify_file()`: `[id*="btn_cenSts"]` 버튼 클릭
- 검증 후 후속 모달 자동 처리 (`dismiss_modals`)
  - 예: "이미 검증이 완료된 자료가 존재합니다. 다시 하시겠습니까?" → 확인
- 검증 결과(형식검증/내용검증)가 페이지에 표시됨

## 모달 처리
- `dismiss_modals()`: WebSquare `.w2popup_window` 내 `btn_confirm` 버튼 순차 클릭
- 페이지 진입 시 알림 모달, 파일검증 후 확인 모달 모두 동일 로직으로 처리

## 세션 연장
- `auto_session_extend(page)`: 20분 주기로 세션 자동 연장 (백그라운드 태스크)
- 홈택스는 **24분 비활동 시 UTXPPABB27 세션 연장 팝업**, **30분 시 강제 로그아웃** 처리
- 팝업 대기 대신 JS 함수 직접 호출로 **사전 예방** 방식 사용:
  - `$c.pp.sessionXtn($p)`: TXPP/TECR/TEET/TEHT/TEWF/TEYS 다중 서버에 JSONP 세션 연장 요청
  - `sessionTimer("Y")`: 24분 팝업 타이머 + 30분 로그아웃 타이머 재시작
- `trigger_session_popup_soon(page, seconds)`: 개발용, 세션 타이머 단축하여 연장 팝업 강제 트리거

### [5] 전자파일 비밀번호 입력
- `enter_password(ht, password)`: 파일검증 → "이미 검증..." 확인 직후 뜨는
  WebSquare 팝업(`.w2popup_window` > `input[type=password]`, w2input)에 비밀번호 주입 + '확인'
- id의 동적 부분(예: `UTERNAAZ65`)에 의존하지 않도록 **"표시 중 팝업 + password input"**으로 식별
- native setter + input/change/keyup 이벤트로 값 주입 (MagicLine `input_cert_pw`는 미사용 잔재)
- 확인 후 **팝업이 닫혔는지 검증**해 틀린 비밀번호를 실패로 판정
- 비밀번호 = 9번(SWER0101) 파일 제작 시 설정한 전자파일(변환파일) 비밀번호

### [6] 제출 (제출하러 가기 → 전자파일 제출하기 → 접수증)
- `submit_report(ht, dry_run=True)` — 실제 관찰된 전체 흐름:
  1. '제출하러 가기'(`btn_rigSts`) → 제출 화면
  2. '전자파일 제출하기'(text 매칭) 클릭
  3. 안내 모달 **"정상 변환된 신고서를 제출합니다"** → 확인
  4. 확인 모달 **"신고서를 제출하시겠습니까?"** → 확인
  5. **원천세 신고서 접수증** 팝업 → 총/정상/오류 건수 로그 + 닫기 → 성공 판정
- **dry_run=True(GUI 기본): 제출 화면 진입까지만, 실제 제출 안 함**
- 모달은 `dismiss_modals`(btn_confirm 무차별 클릭) 대신 **`_wait_and_click_popup`(text 정규식 + 버튼 text)**로 정확히 처리
- 공동인증서 서명 단계 없음(로그인 세션으로 자동 처리). 실제 제출 흐름(제출 → 접수증)까지 동작 확인.
- **real click 필수(2026-07-17 라이브 교훈)**: '전자파일 제출하기'·확인 버튼은 WebSquare `<input type=button>`이라 **JS 합성 click(`b.click()`)을 무시**한다. `_wait_and_click_popup`과 제출 클릭은 element handle 의 **real click**을 사용. JS click 시 '제출신고 파일이 존재하지 않습니다' 오탐 발생.
- 제출 클릭 직후 **차단 모달('파일이 존재하지 않' 등)을 감지**해 명확히 보고(과거 '모달 찾지 못함' 원인불명 로그 개선).
- **접수증 건수 로그는 참고용**: 접수증 팝업의 총/정상/오류 건수가 "0건"으로 읽히는 WebSquare textContent 레이스가 있음(간헐적으로만 정상 파싱). 접수 확정은 **신고내역 조회(접수증·납부서)** 그리드의 접수일시·접수번호로 확인할 것.

## 완료/검증 이력
- **2026-07-17 라이브 검증**: (주)리틀치프코리아(515-86-01709) 2026년 7월분 원천징수이행상황신고서(정기확정) 파일변환신고 **정상 접수 확인** — 접수번호 130-2026-2-…, 접수일시 2026-07-17 17:12. JS click → real click 전환 후 GUI Phase 10 경로로 제출 성공.
- **2026-07-17 E2E 실제 제출**: GUI 선택건 실행 경로(NoopStateManager + `run_single`) 그대로 단건 제출 성공 — 접수일시 19:28:29, 접수번호 130-2026-2-505372462515.
- **2026-07-17 멀티 수임처 루프 라이브 검증**: 동일 수임처 3회 연속 실제 제출(19:37:00~19:38:50, 회차당 약 35초) **3/3 성공**. 수임처 간 페이지 리셋 없이 이전 회차의 제출 완료 화면에서 다음 회차가 재진입('이미 검증' 모달·비밀번호 팝업·real click 제출 매회 정상) — GUI 다건 루프 견고성 확인.
- **동일 과세기간 재제출 = 대체(라이브 확인)**: 신고내역 조회(접수증·납부서)에는 항상 최신 접수번호 1건만 남고 구 접수번호는 목록에서 사라짐(총 건수 불변). 최종 유효분: 접수번호 130-2026-2-505372467548(19:38:49). 재제출로 신고내역이 누적되지 않으며, 마지막 제출이 유효분.

## 미구현 (TODO)
- 접수증 PDF/인쇄 저장 (팝업에 '인쇄하기' 버튼 있음) — Phase 11(신고서류 메일 발송) 설계에 연계
- 신고내역 조회 (접수증·납부서 다운로드) — Phase 11 설계에 연계
  - 진입 팁: 메뉴 `fn_topMenuOpen`은 접힌 메뉴에선 동작 안 함 → URL goto(`tm3lIdx=4101030000`)로 직접 로드. 조회 버튼='조회'(`mf_txppWframe_wq_uuid_908`), 세목 셀렉트=`mf_txppWframe_sbx_itrfCd`(원천세).

## 주요 함수 레퍼런스

| 함수 | 용도 |
|------|------|
| `auto_session_extend(page)` | 20분 주기 세션 연장 (백그라운드) |
| `trigger_session_popup_soon(page, seconds)` | 개발용: 세션 팝업 강제 트리거 |
| `connect_browser(playwright)` | CDP 연결, 홈택스 탭 반환 |
| `dismiss_modals(ht)` | 팝업 모달 자동 닫기 (범용) |
| `goto_withholding_tax(ht)` | 원천세 신고 > 일반신고 메뉴 이동 |
| `goto_file_convert(ht)` | 파일변환신고 버튼 클릭 + 모달 닫기 |
| `select_file(ht, file_path)` | hidden input에 파일 설정 (iframe 대기) |
| `verify_file(ht)` | 파일검증하기 + 후속 모달 자동 처리 |
| `enter_password(ht, password)` | 전자파일 비밀번호 팝업 입력 + 확인 + 팝업 닫힘 검증 |
| `submit_report(ht, dry_run)` | 제출하러 가기 → 전자파일 제출하기 (dry_run이면 진입까지만) |

## 알려진 이슈 & 해결 방법

| 이슈 | 원인 | 해결 |
|------|------|------|
| 파일선택 버튼 클릭 시 네이티브 다이얼로그 열림 | WebSquare가 OS 파일 창 호출 | hidden `<input type="file">` in iframe에 `set_input_files()` 직접 설정 |
| iframe 내 file input이 즉시 나타나지 않음 | 페이지 로드 후 iframe 지연 생성 | 최대 30초 폴링 대기 |
| 알림/확인 모달 중첩 표시 | WebSquare w2popup_window | `btn_confirm` id 포함 INPUT 순차 클릭으로 닫기 |
| 홈택스 접속 시 ERR_CONNECTION_ABORTED | WEHAGO 탭에서 직접 이동 시 | 새 탭에서 열거나 내부 URL로 이동 |
| 파일변환신고 버튼 id가 동적으로 변경 | WebSquare 프레임워크 특성 | `[id*="btn_cbcMediRtn"]` 부분 매치 사용 |
| '전자파일 제출하기' 클릭이 무시됨 ("제출신고 파일이 존재하지 않습니다" 오탐) | WebSquare `<input type=button>`이 JS 합성 click 무시 | `_wait_and_click_popup`·제출 클릭을 **Playwright real click**(element handle)로 전환 (2026-07-17 라이브) |
| 접수증 팝업 건수가 "총 0건/정상 0건"으로 읽힘 | WebSquare 그리드 값이 textContent에 반영되기 전 읽는 레이스 | 실제 접수는 정상일 수 있음 — 신고내역 조회(접수증·납부서) 그리드로 확정 판정 (2026-07-17 라이브) |
| 신고파일 없는 수임처의 실패 사유가 GUI에 안 보임 | 선택건 실행의 NoopStateManager.fail_step이 no-op | fail_step이 사유를 log()로 방출하도록 개선 — 로그 패널에 `[단계 실패] find_swer_file: 신고파일을 찾을 수 없음: <경로>` 표시 (2026-07-17) |

## 실행 방법
- **GUI(권장)**: Phase 10 메뉴에서 실행 — 비밀번호 입력·dry-run 체크박스·제출까지 전 단계 지원. 선택건 실행/전체 실행 모두 가능.
- **CLI(검증용)**: `python src/automation/hometax/hometax_auto_cdp.py <파일경로>` — 파일검증까지만. **CLI의 제출 단계는 미구현(TODO)** — 제출은 GUI Phase 10 경로(`src/workflows/hometax.py`)가 담당.

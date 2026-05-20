# Hometax 자동화 진행 상황

## 파일 위치
- `src/automation/hometax/hometax_auto_cdp.py` — 메인 자동화 스크립트

## 기술 스택
- **Playwright + CDP** (Chrome DevTools Protocol)
- Chrome을 `--remote-debugging-port=9222`로 실행 후 Playwright로 연결
- **Human-in-the-loop**: 홈택스 로그인은 사용자가 수동으로 완료

## 자동화된 프로세스 (4단계)

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

## 미구현 (TODO)
- 비밀번호 입력 단계
- 제출 단계 (이동 → 검증결과확인 → 제출)
- 일괄접수증 확인
- 신고내역 조회 (접수증·납부서)

## 주요 함수 레퍼런스

| 함수 | 용도 |
|------|------|
| `connect_browser(playwright)` | CDP 연결, 홈택스 탭 반환 |
| `dismiss_modals(ht)` | 팝업 모달 자동 닫기 (범용) |
| `goto_withholding_tax(ht)` | 원천세 신고 > 일반신고 메뉴 이동 |
| `goto_file_convert(ht)` | 파일변환신고 버튼 클릭 + 모달 닫기 |
| `select_file(ht, file_path)` | hidden input에 파일 설정 (iframe 대기) |
| `verify_file(ht)` | 파일검증하기 + 후속 모달 자동 처리 |

## 알려진 이슈 & 해결 방법

| 이슈 | 원인 | 해결 |
|------|------|------|
| 파일선택 버튼 클릭 시 네이티브 다이얼로그 열림 | WebSquare가 OS 파일 창 호출 | hidden `<input type="file">` in iframe에 `set_input_files()` 직접 설정 |
| iframe 내 file input이 즉시 나타나지 않음 | 페이지 로드 후 iframe 지연 생성 | 최대 30초 폴링 대기 |
| 알림/확인 모달 중첩 표시 | WebSquare w2popup_window | `btn_confirm` id 포함 INPUT 순차 클릭으로 닫기 |
| 홈택스 접속 시 ERR_CONNECTION_ABORTED | WEHAGO 탭에서 직접 이동 시 | 새 탭에서 열거나 내부 URL로 이동 |
| 파일변환신고 버튼 id가 동적으로 변경 | WebSquare 프레임워크 특성 | `[id*="btn_cbcMediRtn"]` 부분 매치 사용 |

## 실행 방법
```bash
# 검증만 (dry_run, 기본)
python src/automation/hometax/hometax_auto_cdp.py "src/results/근린커피 상암-202605_업로드.xlsx"

# 제출까지
python src/automation/hometax/hometax_auto_cdp.py "src/results/근린커피 상암-202605_업로드.xlsx" --submit
```

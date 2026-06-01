# PRD: Health Insurance Corporation Automation (공단 사이트 제어)

## 1. 개요
본 문서는 국민건강보험(NHIS) 및 국민연금(NPS) EDI 사이트의 자동화를 위한 기술적 요구사항과 구현 전략을 정의합니다.

## 2. 목표 (MVP 단계)
- **인증 방식:** **사용자 수동 로그인 (Human-in-the-loop)**
    - 초기 복잡한 인증 절차(공동인증서, 보안 모듈 등) 자동화 대신, 사용자가 브라우저에서 직접 로그인을 완료한 후 프로그램이 제어권을 이어받아 후속 작업을 수행함.
- **국민건강보험(NHIS):** 로그인 후 특정 데이터 조회 및 신고 자동화.
- **국민연금(NPS) EDI:** 로그인 후 EDI 문서 처리 자동화.

## 3. 기술 스택 (Proposed)
- **Primary Framework:** **Playwright**
    - **Connect Mode:** 이미 실행 중인 브라우저에 연결하거나, 사용자 로그인을 기다리는 `pause()` 또는 특정 요소 대기 로직 활용.
- **Secondary Tool:** **PyAutoGUI**
    - 브라우저 제어 외에 Windows 팝업이나 수동 개입이 필요한 구간에서 보조적으로 사용.
- **Language:** Python 3.10+
- **Environment:** Windows (Target .exe)

## 4. 사이트별 분석 및 접근법

### 4.1. 국민건강보험 (https://www.nhis.or.kr)
- **특징:** 일반적인 웹 구조이나, 로그인을 위해 공동인증서/간편인증이 필요함.
- **접근법:** 
    - Playwright로 웹 요소 제어.
    - 인증서 선택 창 등 OS 레벨의 팝업은 PyAutoGUI로 제어하거나, 가능한 경우 Playwright의 `handle` 기능을 활용.
- **주요 도전 과제:** 보안 모듈 설치 확인 및 우회/대응.

### 4.2. 국민연금 EDI (https://edi.nps.or.kr)
- **프레임워크:** Nexacro (엔터프라이즈 웹 UI 프레임워크)
- **인증:** 공동인증서 로그인 (Human-in-the-loop)
- **접근법:**
    - CDP로 Chrome에 연결 후 Nexacro 제어
    - Nexacro는 일반 DOM click을 무시하므로 `dispatchEvent(new MouseEvent(...))` 로 직접 이벤트 발생 필요
    - **버튼/메뉴:** mousedown → mouseup → click 순차 발생
    - **그리드 행 선택:** dblclick 이벤트 (click × 2 + dblclick)
    - 그리드 셀 ID 패턴: `mainframe.VFrameSet.FrameSdi.ChangeBusi...gridrow_{row}.cell_{row}_{col}`
    - 행 인덱스 기반보다 **텍스트 매칭**으로 행을 찾는 것이 정확
- **사업장 선택:** 업무대행서비스 → 위탁사업장 목록 → 더블클릭으로 선택 (최초) / 사업장전환 버튼(`btnChangeBusi`)으로 전환
- **사업장전환:** 페이지 상단 버튼 → 모달에서 사업장 더블클릭 → 다른 수임처 즉시 전환
- **메뉴 네비게이션:** 상단 메뉴 ID 패턴 `btnTop_M{code}` / 서브메뉴 `btn2D_M{code}`
- **결정내역:** 결정내역(M08000000) → 국민연금보험료 결정내역(M08010000) → 2차 상세(M08010200)
- **상세 탭:** tabbutton_{0~4} (최종결정내역, 수납내역, 가입자내역, 소급분내역, 국고지원내역)
- **출력/PDF:** 출력 버튼 → 주민번호 전체표출 모달(UHJE0002P1) → Crownix rdPreview → PDF 다운로드
- **엑셀저장:** 엑셀저장 버튼 → 주민번호 전체표출 모달(UHJE0002P3) → Excel 다운로드 (확장자 없음 → .xlsx 추가)
- **통합저장:** 통합저장 버튼 → 주민번호 전체표출 모달(UHJE0002P2) → 파일 다운로드 (국고지원내역용)
- **저장 경로:** `~/Desktop/국민연금_{YYYYMM}/{수임처명}/`
- **모듈:** `src/automation/nps/` (`_common.py`, `nps_auto_cdp.py`)
- **주요 도전 과제:** Nexacro 프레임워크의 커스텀 이벤트 시스템 대응

## 5. 단계별 구현 계획
1. **환경 구축:** Playwright 및 PyAutoGUI 설치 및 브라우저 컨텍스트 설정.
2. **인증 모듈화:** 공동인증서 및 로그인 절차 자동화 (가장 큰 허들).
3. **기능 구현:** 각 사이트별 필요 메뉴 진입 및 데이터 처리 로직 개발.
4. **예외 처리:** 네트워크 오류, 사이트 업데이트, 보안 팝업 발생 시 대응 로직.

## 6. 보안 및 규정 준수
- 개인정보(주민번호, 인증서 비번 등)는 메모리 내에서만 처리하며 로깅을 금지함.
- 사이트별 이용 약관 및 자동화 거부 정책 확인 필요.

# 릴리스 / 자동 업데이트 가이드 (개발자용)

이 프로그램은 시작 시(및 도움말 > 업데이트 확인) **공개 릴리스 저장소**의 `version.json`을
조회해 새 버전을 탐지하고, 사용자가 동의하면 설치파일을 내려받아 무인 설치 후 재실행한다.
클라이언트(직원 PC)에는 **어떤 토큰/비밀키도 없다.** 공개 URL만 읽는다.

## 구성 요소

- **버전 단일 소스:** `src/version.py` 의 `__version__`. 이 값만 올리면 앱 타이틀,
  업데이트 비교 기준, 설치파일 버전(`installer.iss` AppVersion)이 모두 갱신된다.
- **소스 저장소(비공개):** `github.com/cobaetoo/withholding-tax-automation` — 코드.
- **릴리스 저장소(공개):** `github.com/cobaetoo/withholding-tax-releases` — `version.json` +
  설치파일 릴리스 에셋만. 소스 코드는 없음.
- **조회 경로:**
  - `version.json` → `https://raw.githubusercontent.com/cobaetoo/withholding-tax-releases/main/version.json`
  - 설치파일 → 릴리스 에셋 `…/releases/download/v{버전}/whta_setup.exe` (에셋명은 **ASCII 필수**)

> 저장소 소유자/이름을 바꾸면 `src/utils/updater.py` 의 `RELEASES_OWNER` / `RELEASES_REPO`
> 와 `release.py` 를 함께 수정한다. `installer.iss` / `gui_main.py` 의 `AppMutex`
> (`WithholdingTaxAutomation_SingleInstance`) 는 서로 일치해야 한다.

## 최초 1회 설정

1. 공개 저장소 `withholding-tax-releases` 생성 (Public).
2. 그 저장소 main 에 `version.json` 을 하나 올려둔다 (아래 스키마, 첫 배포 시 생성됨).
3. 개발 PC에 GitHub CLI(`gh`) 로그인 + Inno Setup(ISCC) 설치.

## 매 릴리스 절차

```bash
# 1) 버전 올리기
#    src/version.py → __version__ = "1.0.3"

# 2) (선택) 소스 태그
git tag v1.0.3 && git push origin master --tags

# 3) 빌드 + version.json 생성 + 에셋 업로드
PYTHONUTF8=1 python release.py                 # 빌드만 + 안내 (인코딩 안전)
PYTHONUTF8=1 python release.py --publish       # gh release create 로 에셋 업로드까지
PYTHONUTF8=1 python release.py --publish --skip-build          # 기존 빌드 재사용해 재게시
PYTHONUTF8=1 python release.py --publish --mandatory --notes "홈택스 변경 대응 필수 업데이트"

# 4) version.json 을 공개 저장소 main 에 반영 (앱이 새 버전을 인식하려면 필수)
#    release.py 는 installer_output/version.json 생성만 하므로 아래로 공개 repo 에 반영:
SHA=$(gh api repos/cobaetoo/withholding-tax-releases/contents/version.json --jq '.sha')
gh api repos/cobaetoo/withholding-tax-releases/contents/version.json -X PUT \
  -f message="release v1.0.3" -f branch=main \
  -f content="$(base64 -w0 installer_output/version.json)" -f sha="$SHA" --jq '.commit.sha'
```

> **`PYTHONUTF8=1` 필수** — cp949 콘솔에서 한글/유니코드 처리 실패로 gh 직전에 종료되는 것을 방지.

`--publish` 는 설치파일을 **ASCII 에셋명 `whta_setup.exe`** 로 업로드한다.
한글 파일명은 (1) gh 업로드 시 `_.exe` 로 깨지고 (2) updater 의 urllib URL 요청이 `UnicodeEncodeError` 로 실패하므로 반드시 ASCII 여야 한다.
`version.json` 반영(4단계)은 앱이 새 버전을 인식하는 데 필수이며, 위 `gh api contents` PUT 한 줄로 완료된다 (raw URL 반영에 수십 초~1분 지연 있음).

## version.json 스키마

`version.json.example` 참고.

| 필드 | 설명 |
|------|------|
| `version` | 최신 버전 (예: `"1.0.1"`). 로컬 `__version__` 보다 높으면 업데이트 안내 |
| `mandatory` | `true` 면 강제 업데이트 ([지금 업데이트]/[종료]만, 건너뛰기 불가) |
| `min_supported` | 이 버전 **미만**의 클라이언트는 강제 업데이트. 빈 문자열이면 미적용 |
| `url` | 설치파일(.exe) 다운로드 URL (공개 릴리스 에셋) |
| `sha256` | 설치파일 SHA-256 (다운로드 무결성 검증; release.py가 계산) |
| `size` | 설치파일 바이트 크기 (검증용) |
| `notes` | 사용자에게 표시할 변경 내용 |
| `released` | 릴리스 날짜 (참고용) |

## 동작 / 안전장치 요약

- **데이터 보존:** DB·결과파일은 `%LOCALAPPDATA%\원천징수자동화-data` (설치 폴더 밖)에
  저장되어 업그레이드/제거에도 보존된다. 구버전(설치 폴더 내 저장) 사용자는 첫 실행 시
  자동 1회 이전(`config.migrate_legacy_data`).
- **파일 잠금:** 실행 중에는 ONEDIR exe/`_internal` 이 잠기므로, 앱이 먼저 완전히 종료된 뒤
  설치기가 덮어쓴다. `installer.iss` 의 `CloseApplications=yes` + `AppMutex` 가 안전망.
- **재실행:** 앱이 종료된 뒤 cmd 래퍼가 `/VERYSILENT` 무인설치 후 새 exe 를 재실행.
- **실패 안전:** 네트워크/서버 장애 시 자동 확인은 조용히 무시되고 앱은 정상 실행된다.
  손상 다운로드는 size+sha256 검증으로 차단.
- **개발 모드:** 소스로 실행(`python gui_main.py`)하면 설치를 진행하지 않는다.

## 코드 서명 / SmartScreen 현황 (v1.0.3 현재)

인스톨러와 본 exe 모두 **미서명**입니다. 인터넷(카페/클라우드/메신저/GitHub)에서 받은 파일은
Windows SmartScreen 파란 차단 화면이 뜨며, 사용자가 "추가 정보 → 실행"으로 우회해야 합니다.

현재 채택한 대응(코드 서명 없이):
- **`docs/설치안내서.md`** — 비전공자용 A4 1장 안내(SmartScreen 대처법 중심) 배포
- **USB / 사내 공유 폴더 직접 전달** 시 MotW 가 붙지 않아 SmartScreen 이 뜨지 않음 (소수 실무자 배포에 최적)
- 인스톨러가 Chrome 미설치를 설치 단계에서 차단

향후 옵션(필요 시):
- **인스톨러만 서명** (Azure Trusted Signing 월 $9.99 또는 저가 OV cert): 본 exe 는 미서명 유지하되 사용자가 SmartScreen 을 안 보게 가능
- **winget 배포** (`microsoft/winget-pkgs` 매니페스트 PR): `winget install` 경로는 SmartScreen 을 타지 않음
- **CI 자동 게시:** 비공개 저장소 태그 push 시 GitHub Actions(windows-runner + Inno)로
  빌드해 공개 저장소에 에셋/version.json 자동 게시 (교차 저장소 PAT는 Actions 시크릿)

## v1.0.3 변경 요약

- 빌드 번들 보강: `--collect-submodules pdfplumber/PyMuPDF/src` + `verify_bundle()` (함수 내부 import 누락으로 NHIS PDF 파싱 시 ModuleNotFoundError 났던 블로커 해결)
- 자동업데이트: 릴리스 에셋명 ASCII(`whta_setup.exe`)화 + `updater._encode_url()` 로 URL path percent-encode (한글 파일명 UnicodeEncodeError/404 해결)
- 인스톨러 Chrome 미설치 시 설치 차단 게이트 추가
- 로그인 창 계정 발급/문의 안내 추가
- 바탕화면 쓰기 불가 시 저장 경로 폴백(문서/홈/LOCALAPPDATA/TEMP)
- 보안: `auth_session.json` git 추적 해제 + `.gitignore` (※ 히스토리 잔존 — Supabase refresh_token 회전 필요)

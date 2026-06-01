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
  - 설치파일 → 릴리스 에셋 `…/releases/download/v{버전}/원천징수자동화_설치.exe`

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
#    src/version.py → __version__ = "1.0.1"

# 2) (선택) 소스 태그
git tag v1.0.1 && git push origin master --tags

# 3) 빌드 + version.json 생성 + 게시 명령 출력
python release.py                 # 빌드만 + 안내
python release.py --publish       # gh release create 로 에셋 업로드까지
python release.py --publish --mandatory --notes "홈택스 변경 대응 필수 업데이트"

# 4) version.json 을 공개 저장소 main 에 커밋  (release.py 가 installer_output/version.json 생성)
#    → 공개 저장소 루트의 version.json 으로 복사 후 commit/push
```

`--publish` 는 설치파일을 릴리스 에셋으로 업로드한다. **`version.json` 커밋(4단계)은
공개 저장소 작업 트리에서 수동으로 수행**해야 앱이 새 버전을 인식한다.

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

## 후속 과제 (선택)

- **코드 서명(Authenticode):** 미서명 설치파일은 SmartScreen 경고가 날 수 있음.
  외부 배포 신뢰도를 위해 OV 인증서 + `SignTool` 도입 권장.
- **CI 자동 게시:** 비공개 저장소 태그 push 시 GitHub Actions(windows-runner + Inno)로
  빌드해 공개 저장소에 에셋/version.json 자동 게시 (교차 저장소 PAT는 Actions 시크릿).

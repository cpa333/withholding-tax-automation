# 인증 시스템 기술 문서

## 개요

클로즈 베타 배포를 위한 ID/PW 로그인 인증 시스템. Supabase Auth를 서버로 사용하며, 새로운 패키지 의존성 없이 Python stdlib `urllib`만으로 통신한다.

## 아키텍처

```
┌──────────────┐         ┌──────────────┐
│  데스크톱 앱  │ ──────→ │  Supabase    │
│  (PySide6)   │ ←────── │  Auth API    │
└──────────────┘         └──────────────┘
       │
   auth_session.json    ← 로컬 세션 캐시
```

### 인증 흐름

```
앱 실행
  │
  ├─ ① 베타 만료일 확인 (오프라인)
  │     만료 → 종료
  │
  ├─ ② 세션 파일 로드 → validate_session()
  │     ├─ JWT exp 확인 → 만료 시 refresh 시도
  │     ├─ GET /user로 계정 활성 상태 확인
  │     └─ 성공 → last_verified_at 갱신 → MainWindow 진입
  │
  ├─ ③ 세션 무효 + 유예 기간(3일) 내 → MainWindow 진입
  │
  └─ ④ 세션 무효 + 유예 기간 초과 → LoginDialog 표시
        ├─ 로그인 성공 → MainWindow 진입
        └─ 종료 → 앱 종료
```

### 주기적 재인증

MainWindow 진입 후 4시간마다 백그라운드에서 세션 재검증:

```
QTimer (4시간)
  → AuthWorker.start_validate()
  → auth.validate_session()
  → 실패 + 유예 초과 → LoginDialog 재표시
```

### 로그아웃

상태바 우측의 "로그아웃" 버튼 클릭:

```
로그아웃 버튼 클릭
  ├─ 자동화 진행 중 → 확인 다이얼로그
  ├─ auth.clear_session() (서버 logout + 로컬 파일 삭제)
  └─ LoginDialog 표시 → 재로그인 또는 종료
```

## 파일 구조

```
src/
├── ui/
│   ├── resources/
│   │   └── auth_config.py      # Supabase URL, anon key, 만료일 등 상수
│   ├── widgets/
│   │   └── login_dialog.py     # 로그인 다이얼로그 UI (QDialog)
│   └── workers/
│       └── auth_worker.py      # 인증 백그라운드 워커 (QThread)
├── utils/
│   └── auth.py                 # 코어 인증 로직 (Qt 비의존, urllib)
├── config.py                   # AUTH_SESSION_PATH 추가
└── ui/
    └── main_window.py          # 상태바 로그인 정보, 로그아웃, 재인증 타이머

gui_main.py                     # 인증 게이트 (MainWindow 생성 전)
build.py                        # auth 관련 hidden-import 추가
```

## 설정 항목

`src/ui/resources/auth_config.py`:

| 상수 | 기본값 | 설명 |
|---|---|---|
| `SUPABASE_URL` | 프로젝트별 상이 | Supabase 프로젝트 URL |
| `SUPABASE_ANON_KEY` | 프로젝트별 상이 | 공개 anon key (RLS가 보안 담당) |
| `BETA_EXPIRES` | `2026-12-31` | 베타 만료일 (하드코딩) |
| `AUTH_GRACE_PERIOD_DAYS` | `3` | 오프라인 유예 기간 (일) |
| `AUTH_REFRESH_INTERVAL_SECS` | `14400` | 재인증 주기 (초, 기본 4시간) |

## 세션 파일

| 모드 | 경로 |
|---|---|
| 개발 (`python gui_main.py`) | `{프로젝트폴더}/auth_session.json` |
| 배포 (exe) | `%LOCALAPPDATA%\원천징수자동화-data\auth_session.json` |

세션 파일 내용:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "...",
  "expires_in": 3600,
  "user": { "id": "...", "email": "user@example.com" },
  "last_verified_at": "2026-06-03T12:00:00+00:00"
}
```

## 보안 고려사항

- **Anon key**: Supabase 설계상 공개 키. 보안은 RLS 정책이 담당
- **세션 파일**: `%LOCALAPPDATA%` (per-user, 타 사용자 접근 불가)
- **토큰**: access_token 1시간 만료, refresh_token 1회용 회전
- **오프라인 유예**: 서버 통신 불가 시 최대 3일간 사용 가능
- **로그아웃**: 서버에 `/logout` 요청 + 로컬 파일 삭제

## Supabase 설정 방법

1. https://supabase.com/dashboard 에서 프로젝트 생성
2. **Authentication → Providers → Email** 활성화
3. **Authentication → Settings → "Enable sign ups" 비활성화** (관리자만 계정 생성)
4. **"Confirm email"** 비활성화
5. **Authentication → Users → "Add User"**에서 회계법인별 계정 생성
6. `auth_config.py`에 프로젝트 URL과 anon key 입력

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| 로그인 화면이 안 나옴 | 세션 캐시 남음 | `auth_session.json` 삭제 후 재실행 |
| "서버에 연결할 수 없습니다" | 인터넷 연결 문제 | 네트워크 확인 |
| "이메일 또는 비밀번호가 올바르지 않습니다" | 잘못된 자격 증명 | Supabase 대시보드에서 계정 확인 |
| "사용 기간 만료" | BETA_EXPIRES 경과 | auth_config.py 만료일 업데이트 후 재빌드 |

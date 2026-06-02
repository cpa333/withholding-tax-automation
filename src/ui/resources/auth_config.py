"""Supabase 인증 설정 상수.

이 파일은 빌드 시 exe에 포함된다. SUPABASE_ANON_KEY는 공개 키이며
(Supabase 설계상 브라우저/클라이언트에 노출되는 것이 정상),
실제 보안은 Supabase RLS 정책과 서버 측 계정 관리가 담당한다.

Supabase 프로젝트 생성 후 아래 SUPABASE_URL과 SUPABASE_ANON_KEY를
실제 값으로 교체해야 한다.
"""

# ── Supabase 프로젝트 설정 ──────────────────────────────────────────
# TODO: Supabase 프로젝트 생성 후 실제 값으로 교체
SUPABASE_URL = "https://jwmjsgtbjtqvpthiuwyw.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp3bWpzZ3RianRxdnB0aGl1d3l3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODAzODI5MDcsImV4cCI6MjA5NTk1ODkwN30.vsgDoD2yyMSX8LIAgelAAbw8u9nb8vCFGHaQLycFjiY"

# ── 베타 만료일 ──────────────────────────────────────────────────────
BETA_EXPIRES = "2026-12-31"

# ── 인증 파라미터 ────────────────────────────────────────────────────
AUTH_GRACE_PERIOD_DAYS = 3           # 오프라인 유예 기간 (일)
AUTH_REFRESH_INTERVAL_SECS = 4 * 60 * 60  # 백그라운드 재인증 주기 (4시간)
AUTH_SESSION_FILENAME = "auth_session.json"

#!/usr/bin/env bash
# deploy.sh — 버전 자동 증분(SemVer) + 빌드 + 게시 + version.json 반영 + 전파 검증
#
# RELEASE.md 의 "매 릴리스 절차"를 한 명령으로 자동화. Git Bash(Git for Windows) 전용.
#   - release.py / build.py / updater.py 는 수정하지 않고 그대로 호출.
#   - release.py 가 안 하는 두 갭을 채움:
#       (a) version.json 을 공개 repo(cobaetoo/withholding-tax-releases) main 에 반영
#       (b) git tag 생성 + 릴리스 커밋 + push
#
# 사용법:
#   ./deploy.sh                       # 자동 버전 분석 → 전체 배포
#   ./deploy.sh --bump minor          # 레벨 강제 (patch|minor|major)
#   ./deploy.sh --version 1.2.0       # 특정 버전 강제
#   ./deploy.sh --notes "..."         # 릴리스 노트 override
#   ./deploy.sh --mandatory           # 강제 업데이트 (건너뛰기 불가)
#   ./deploy.sh --no-build            # 기존 빌드 재사용 (release.py --skip-build)
#   ./deploy.sh --dry-run             # 실행 계획만 출력 (변경 없음)
#   ./deploy.sh --allow-empty         # 커밋 없이도 배포 허용
#   ./deploy.sh --yes                 # 최종 확인 프롬프트 건너뜀
#   ./deploy.sh --help

set -euo pipefail

# ── 상수 ─────────────────────────────────────────────────────────────────
# updater.py / release.py 의 상수와 동일하게 유지. 변경 시 거기도 수정.
RELEASES_OWNER="cobaetoo"
RELEASES_REPO="withholding-tax-releases"
VERSION_PY="src/version.py"
INSTALLER_JSON="installer_output/version.json"
# version.json raw URL 캐시 반영 대기.
# raw.githubusercontent.com 은 Cache-Control: max-age=300 이라 최악의 경우(푸시 직전에
# 캐시가 채워진 경우) 300초를 꽉 채워야 갱신된다. 90s 로는 구조적으로 부족해 오탐이 잦았음
# (2026-07-20 v1.0.5 배포에서 실제 발생 — 실제 전파는 커밋 +300s 시점).
POLL_MAX_SECONDS=330
POLL_INTERVAL_SECONDS=10     # 폴링 간격(로그 노이즈 억제 — 330/10 = 최대 33줄)

# ── 색상 (터미널 비지원 시 자동 비활성) ─────────────────────────────────
if [[ -t 1 ]]; then
    C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_RESET=$'\033[0m'
else
    C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_RESET=""
fi

log()  { printf '%s==%s %s\n' "$C_BOLD" "$C_RESET" "$*"; }
ok()   { printf '%s[OK]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%s[ERROR]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
step() { printf '\n%s── [%s] %s ──%s\n' "$C_BLUE" "$1" "$2" "$C_RESET"; }

# ── 인자 파싱 ────────────────────────────────────────────────────────────
BUMP=""            # auto|patch|minor|major  (빈 값 = auto)
FORCE_VERSION=""   # X.Y.Z
NOTES=""
MANDATORY=0
NO_BUILD=0
DRY_RUN=0
ALLOW_EMPTY=0
ASSUME_YES=0

usage() {
    sed -n '3,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bump)         BUMP="$2"; shift 2 ;;
        --version)      FORCE_VERSION="$2"; shift 2 ;;
        --notes)        NOTES="$2"; shift 2 ;;
        --mandatory)    MANDATORY=1; shift ;;
        --no-build)     NO_BUILD=1; shift ;;
        --dry-run)      DRY_RUN=1; shift ;;
        --allow-empty)  ALLOW_EMPTY=1; shift ;;
        --yes|-y)       ASSUME_YES=1; shift ;;
        --help|-h)      usage ;;
        *)              die "알 수 없는 인자: $1 (--help 참조)" ;;
    esac
done

# bash 정규식 매칭 시 LC_ALL=C 로 안정화 (한글 환경 의존 제거)
export LC_ALL=C
# RELEASE.md §51: cp949 콘솔에서 한글 처리 실패 방지
export PYTHONUTF8=1

# ── [0] 사전 검증 ────────────────────────────────────────────────────────
run_step_preflight() {
    step 0 "사전 검증"

    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "git 저장소가 아닙니다."
    command -v gh >/dev/null 2>&1 || die "GitHub CLI(gh)가 없습니다. https://cli.github.com/"
    command -v python >/dev/null 2>&1 || die "python 이 PATH 에 없습니다."

    local branch
    branch=$(git rev-parse --abbrev-ref HEAD)
    [[ "$branch" == "master" ]] \
        || die "현재 브랜치가 master 가 아닙니다 ($branch). master 에서만 배포하세요."

    # gh 인증
    if ! gh auth status >/dev/null 2>&1; then
        die "gh 인증이 안 되어 있습니다. 'gh auth login' 먼저."
    fi

    # ISCC (Inno Setup) — 빌드 스킵 시 불필요
    if [[ $NO_BUILD -eq 0 ]]; then
        if [[ ! -f "${LOCALAPPDATA:-}/Programs/Inno Setup 6/ISCC.exe" ]] \
           && ! command -v ISCC >/dev/null 2>&1 \
           && [[ -z "${ISCC_PATH:-}" ]]; then
            warn "Inno Setup(ISCC) 감지 안 됨 — build.py 가 자동 설치를 시도합니다."
        fi
    fi

    # 작업 트리 clean 검사
    if [[ -n "$(git status --porcelain)" ]]; then
        if [[ $ALLOW_EMPTY -eq 0 && $DRY_RUN -eq 0 ]]; then
            die "작업 트리가 dry 합니다 (커밋되지 않은 변경 있음). commit/stash 후 재시도. (강제: --allow-empty)"
        fi
        warn "작업 트리에 미커밋 변경이 있습니다."
    fi

    ok "사전 검증 통과 (브랜치=$branch)"
}

# ── 버전 파싱 유틸 ───────────────────────────────────────────────────────
# version.py 에서 __version__ 을 읽는다 (build.py 와 동일한 정규식 접근).
read_version_py() {
    local v
    v=$(grep -E '^__version__\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"' "$VERSION_PY" \
        | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')
    [[ -n "$v" ]] || die "$VERSION_PY 에서 __version__ 을 찾지 못했습니다."
    echo "$v"
}

# semver 를 major.minor.patch 배열(정수)로.
parse_semver() {
    local v="$1"
    [[ "$v" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] \
        || die "잘못된 semver 형식: $v (X.Y.Z 여야 함)"
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}"
}

bump_version() {
    # $1=현재버전 $2=레벨(patch|minor|major) → 새 버전
    local cur="$1" level="$2"
    read -r major minor patch < <(parse_semver "$cur")
    case "$level" in
        major) echo "$((major+1)).0.0" ;;
        minor) echo "$major.$((minor+1)).0" ;;
        patch) echo "$major.$minor.$((patch+1))" ;;
        *)     die "알 수 없는 bump 레벨: $level" ;;
    esac
}

# ── [1] 버전 자동 증분 ───────────────────────────────────────────────────
run_step_bump() {
    step 1 "버전 결정"

    CURRENT=$(read_version_py)

    # 기준점 결정 (우선순위):
    #   1) 마지막 태그 (git describe)
    #   2) version.py 의 __version__ 값(예: 1.0.3)을 언급한 가장 최근 커밋
    #      — 태그를 안 달아온 이 저장소의 현실에 맞춘 폴백. 릴리스 커밋 메시지 관례
    #      ("release: v1.0.3", "fix: v1.0.3 — ...") 를 역으로 이용해 기준 커밋을 찾는다.
    local base_ref="" base_kind=""
    if LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null); then
        base_ref="$LAST_TAG"
        base_kind="태그"
    else
        # 현재 버전이 등장하는 마지막 커밋을 그 버전의 기준점으로 본다.
        # (version.py 가 해당 버전으로 set 된 커밋 = 그 버전의 릴리스 시점)
        base_ref=$(git log --pretty=format:"%H" -G "__version__ = \"$CURRENT\"" -- "$VERSION_PY" 2>/dev/null | head -1)
        if [[ -z "$base_ref" ]]; then
            # 차선: 커밋 메시지에 "v{CURRENT}" 가 포함된 가장 최근 커밋.
            base_ref=$(git log --pretty=format:"%H" --grep="v$CURRENT" -i 2>/dev/null | head -1)
        fi
        base_kind="커밋(태그 없음)"
    fi

    if [[ -z "$base_ref" ]]; then
        die "기준점을 결정할 수 없습니다 — git 태그가 없고 '$CURRENT' 버전의 커밋도 찾지 못했습니다. git tag v$CURRENT 로 수동 생성 후 재시도하세요."
    fi
    local base_short
    base_short=$(git rev-parse --short "$base_ref" 2>/dev/null)
    log "현재 버전: $CURRENT   기준점: $base_short [$base_kind]"

    # 커밋 분석 (제목 + 본문).
    # git log 의 %B = 제목+본문. 커밋 구분자로 안전하게 순회.
    local commits_body
    commits_body=$(git log --pretty=format:"__COMMIT__%B" "$base_ref..HEAD" 2>/dev/null || true)

    local n_feat=0 n_fix=0 n_breaking=0 n_other=0
    declare -a feat_titles=()
    while IFS= read -r line; do
        # 커밋 제목(각 __COMMIT__ 직후 첫 비어있지 않은 줄)만 분류 카운트에 사용.
        case "$line" in
            __COMMIT__*)
                # 이전 커밋 본문에 BREAKING CHANGE 가 있었는지는 이미 본문 스캔에서 잡음.
                :
                ;;
        esac
    done <<< "$commits_body"

    # 단순/견고화: 제목 줄만 뽑아서 분류. feat/fix/BREAKING 카운트.
    # 주의: [[ =~ ]] 에 괄호 정규식을 인라인으로 쓰면 bash 가 구문을 오파싱하므로
    # 정규식은 반드시 변수에 담아 사용한다.
    local subject
    # BREAKING: type 뒤 '!' (예: feat!: / refactor(scope)!: ). 본문 BREAKING CHANGE: 는 아래서 별도.
    local re_break='^[a-z]+(\([^)]+\))?!:'
    local re_feat='^feat(\(|:)'
    local re_fix='^fix(\(|:)'
    local re_other='^[a-z]+(\(|:)'
    while IFS= read -r subject; do
        [[ -z "$subject" ]] && continue
        if [[ "$subject" =~ $re_break ]]; then
            n_breaking=$((n_breaking+1))
        elif [[ "$subject" =~ $re_feat ]]; then
            n_feat=$((n_feat+1))
            # 제목에서 요약 추출(콜론 뒤). 5개까지만.
            if (( ${#feat_titles[@]} < 5 )); then
                feat_titles+=("${subject#*: }")
            fi
        elif [[ "$subject" =~ $re_fix ]]; then
            n_fix=$((n_fix+1))
        elif [[ "$subject" =~ $re_other ]]; then
            n_other=$((n_other+1))
        fi
    done < <(git log --pretty=format:"%s" "$base_ref..HEAD" 2>/dev/null)

    # 본문 BREAKING CHANGE 별도 스캔 (제목 ! 표기 외의 경로).
    local body_breaking
    body_breaking=$(printf '%s\n' "$commits_body" | grep -c -iE '^BREAKING CHANGE:' || true)
    n_breaking=$((n_breaking + body_breaking))

    local total_commits
    total_commits=$(git rev-list --count "$base_ref..HEAD" 2>/dev/null || echo 0)

    log "커밋 분석 ($base_short..HEAD): 총 $total_commits 건"
    printf '  %sfeat%s=%d  %sfix%s=%d  %sbreaking%s=%d  기타=%d\n' \
        "$C_GREEN" "$C_RESET" "$n_feat" \
        "$C_YELLOW" "$C_RESET" "$n_fix" \
        "$C_RED" "$C_RESET" "$n_breaking" "$n_other"

    # 빌드할 게 없는 경우
    if [[ $total_commits -eq 0 && $ALLOW_EMPTY -eq 0 ]]; then
        die "기준점($base_short) 이후 커밋이 없습니다. 배포할 변경이 없습니다. (강제: --allow-empty)"
    fi

    # 자동 레벨 결정 (override 우선)
    local level
    if [[ -n "$FORCE_VERSION" ]]; then
        # 강제 버전은 현재보다 높기만 하면 됨 (SemVer 위반도 허용 — 사용자 책임)
        level="forced"
        NEW_VERSION="$FORCE_VERSION"
        log "강제 버전 (--version): $NEW_VERSION"
    elif [[ -n "$BUMP" ]]; then
        level="$BUMP"
        NEW_VERSION=$(bump_version "$CURRENT" "$level")
        log "강제 레벨 (--bump $level): $CURRENT → $NEW_VERSION"
    else
        if (( n_breaking > 0 )); then
            level="major"
        elif (( n_feat > 0 )); then
            level="minor"
        else
            level="patch"
        fi
        NEW_VERSION=$(bump_version "$CURRENT" "$level")
        log "자동 결정: $level → $CURRENT → $NEW_VERSION"
    fi

    # 다운그레이드/동일버전 경고 — 강제(--version)라도 경고는 함(사용자가 위험 인지).
    # 산술 비교로 자릿수 함정(1 vs 10) 회피: NEW > CUR 이어야 정상.
    local cM cm cp nM nm np is_higher=1
    read -r cM cm cp < <(parse_semver "$CURRENT")
    read -r nM nm np < <(parse_semver "$NEW_VERSION")
    if (( nM > cM )); then
        is_higher=1
    elif (( nM == cM )); then
        if (( nm > cm )); then
            is_higher=1
        elif (( nm == cm )); then
            if (( np > cp )); then
                is_higher=1
            else
                is_higher=0
            fi
        else
            is_higher=0
        fi
    else
        is_higher=0
    fi
    if (( is_higher == 0 )); then
        warn "신규 버전($NEW_VERSION)이 현재($CURRENT)보다 높지 않습니다 — 업데이터가 무시하거나, 같은 버전이면 version.json 갱신이 의미 없을 수 있습니다."
    fi

    # ── 릴리스 노트 자동 생성 ──
    if [[ -z "$NOTES" ]]; then
        local parts=()
        (( n_feat > 0 ))      && parts+=("feat ${n_feat}개")
        (( n_fix > 0 ))       && parts+=("fix ${n_fix}개")
        (( n_breaking > 0 ))  && parts+=("BREAKING ${n_breaking}개")
        local summary
        if (( ${#parts[@]} > 0 )); then
            # IFS='/' 는 배열을 '/' 로 join. (주의: IFS=', ' 처럼 여러 문자를 주면
            # 각 문자가 개별 구분자가 되어 'a, b' 대신 'a,b' 가 되므로 단일 문자여야 함.)
            summary="${parts[*]/// } 변경"
        else
            summary="버그 수정 및 기능 개선"
        fi
        # 주요 feat 제목 최대 3개를 뒤에 덧붙임 (명사구 요약용).
        if (( ${#feat_titles[@]} > 0 )); then
            local top3=()
            local idx=0
            for t in "${feat_titles[@]}"; do
                (( idx >= 3 )) && break
                # 콜론 뒤 설명만 추출("feat(scope): blah" → "blah") + 공백 정리.
                local desc="${t##*:}"
                desc="${desc#"${desc%%[![:space:]]*}"}"   # 좌측 공백 제거
                desc="${desc%"${desc##*[![:space:]]}"}"   # 우측 공백 제거
                [[ -z "$desc" ]] && continue
                # 너무 길면 50자에서 자르고 말줄임.
                if ((${#desc} > 50)); then desc="${desc:0:49}…"; fi
                top3+=("$desc")
                idx=$((idx+1))
            done
            if (( ${#top3[@]} > 0 )); then
                local joined=""
                local first=1
                for t in "${top3[@]}"; do
                    if (( first )); then joined="$t"; first=0
                    else joined="$joined, $t"; fi
                done
                summary="$summary — $joined"
            fi
        fi
        NOTES="$summary"
    fi
    log "릴리스 노트: \"$NOTES\""
}

# ── [2] version.py 갱신 ─────────────────────────────────────────────────
run_step_version_py() {
    step 2 "version.py 갱신: $CURRENT → $NEW_VERSION"

    if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry-run) $VERSION_PY 의 __version__ 을 \"$NEW_VERSION\" 로 교체"
        return
    fi

    # 단일 라인 정확 교체 (build.py 정규식 호환 형태 유지).
    if ! sed -i -E "s|^(__version__\s*=\s*\")[0-9]+\.[0-9]+\.[0-9]+(\")|\1${NEW_VERSION}\2|" "$VERSION_PY"; then
        die "version.py sed 교체 실패"
    fi

    # 검증: 다시 읽어서 NEW_VERSION 인지.
    local after
    after=$(read_version_py)
    [[ "$after" == "$NEW_VERSION" ]] \
        || die "version.py 검증 실패: 기대=$NEW_VERSION 실제=$after"
    ok "version.py 갱신 확인 ($after)"
}

# ── [3] 빌드 + 게시 (release.py 호출) ────────────────────────────────────
run_step_build_publish() {
    step 3 "빌드 + 게시 (release.py)"

    local -a args=(--publish --notes "$NOTES")
    [[ $MANDATORY -eq 1 ]] && args+=(--mandatory)
    [[ $NO_BUILD -eq 1 ]]  && args+=(--skip-build)

    if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry-run) PYTHONUTF8=1 python release.py ${args[*]}"
        return
    fi

    log "실행: python release.py ${args[*]}"
    # release.py 는 --publish 실패해도 exit code 를 신뢰할 수 없으므로(내부 [WARN] 처리),
    # 종료 코드와 무관하게 다음 단계에서 에셋을 직접 검증한다.
    python release.py "${args[@]}" || warn "release.py 가 0이 아닌 코드로 종료 — 다음 단계에서 재검증합니다."
}

# ── [4] 게시 결과 검증 ────────────────────────────────────────────────────
run_step_verify_asset() {
    step 4 "게시 결과 검증 (에셋)"

    if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry-run) gh release view v$NEW_VERSION + installer_output/whta_setup.exe 확인"
        return
    fi

    # 로컬 산출물
    [[ -f "installer_output/whta_setup.exe" ]] \
        || die "installer_output/whta_setup.exe 가 없습니다 — 빌드/게시 실패."

    # 공개 repo 릴리스 + 에셋 존재
    if ! gh release view "v$NEW_VERSION" --repo "$RELEASES_OWNER/$RELEASES_REPO" >/dev/null 2>&1; then
        die "공개 repo 에 release v$NEW_VERSION 이 없습니다 — gh release create 실패."
    fi
    local asset_url
    asset_url=$(gh release view "v$NEW_VERSION" --repo "$RELEASES_OWNER/$RELEASES_REPO" \
                --json assets --jq '.assets[].name' 2>/dev/null | grep -x "whta_setup.exe" || true)
    [[ -n "$asset_url" ]] \
        || die "release v$NEW_VERSION 에 whta_setup.exe 에셋이 없습니다."
    ok "에셋 확인: v$NEW_VERSION / whta_setup.exe"
}

# ── [5] version.json 공개 repo 반영 ──────────────────────────────────────
run_step_publish_version_json() {
    step 5 "version.json 공개 repo 반영"

    if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry-run) gh api contents PUT (version.json → $RELEASES_REPO:main)"
        return
    fi

    [[ -f "$INSTALLER_JSON" ]] \
        || die "$INSTALLER_JSON 이 없습니다 — release.py 가 생성하지 못했습니다."

    # 기존 version.json 의 sha 조회 (PUT 갱신에 필요). 없으면 404 → 최초 생성 경로.
    local sha=""
    sha=$(gh api "repos/$RELEASES_OWNER/$RELEASES_REPO/contents/version.json" \
            --jq '.sha' 2>/dev/null || true)

    local b64
    b64=$(base64 -w0 "$INSTALLER_JSON")

    if [[ -n "$sha" ]]; then
        gh api "repos/$RELEASES_OWNER/$RELEASES_REPO/contents/version.json" -X PUT \
            -f message="release v$NEW_VERSION" \
            -f branch=main \
            -f content="$b64" \
            -f sha="$sha" \
            --jq '.commit.sha' >/dev/null \
            || die "version.json PUT 실패 (갱신)"
    else
        # 최초 1회 생성 (RELEASE.md 는 이미 올려둔 것을 전제하나, 방어적으로 처리).
        warn "version.json 이 공개 repo 에 없습니다 — 최초 생성 경로."
        gh api "repos/$RELEASES_OWNER/$RELEASES_REPO/contents/version.json" -X PUT \
            -f message="release v$NEW_VERSION (initial)" \
            -f branch=main \
            -f content="$b64" \
            --jq '.commit.sha' >/dev/null \
            || die "version.json PUT 실패 (최초 생성)"
    fi
    ok "version.json 반영 완료"
}

# ── [6] git 커밋 + 태그 + push ────────────────────────────────────────────
run_step_git() {
    step 6 "git 커밋 + 태그 + push"

    if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry-run) git commit -m \"release: v$NEW_VERSION\" && git tag v$NEW_VERSION && git push"
        return
    fi

    # version.py 가 이미 교체된 상태. 변경이 있으면 커밋.
    if git diff --quiet -- "$VERSION_PY" 2>/dev/null || \
       ! git diff --cached --quiet -- "$VERSION_PY" 2>/dev/null; then
        : # staged 이거나 unstaged 이거나 어쨌든 add 해서 커밋
    fi
    git add -- "$VERSION_PY"

    # 커밋할 변경이 있으면 커밋 (강제 버전으로 같은 값이면 변경 없을 수 있음).
    if ! git diff --cached --quiet -- "$VERSION_PY" 2>/dev/null; then
        git commit -m "release: v$NEW_VERSION" >/dev/null
        ok "커밋: release: v$NEW_VERSION"
    else
        warn "version.py 에 커밋할 변경이 없습니다 (이미 $NEW_VERSION 임)."
    fi

    # 태그 (이미 있으면 스킵).
    if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
        warn "태그 v$NEW_VERSION 이 이미 존재합니다 — 스킵."
    else
        git tag "v$NEW_VERSION"
        ok "태그: v$NEW_VERSION"
    fi

    log "push origin master + 태그..."
    git push origin master
    git push origin "v$NEW_VERSION"
    ok "push 완료"
}

# ── [7] 전파 검증 ─────────────────────────────────────────────────────────
run_step_verify_propagation() {
    step 7 "전파 검증 (version.json raw URL)"

    local url="https://raw.githubusercontent.com/$RELEASES_OWNER/$RELEASES_REPO/main/version.json"
    log "조회: $url"

    if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry-run) version 필드가 $NEW_VERSION 인지 폴링(최대 ${POLL_MAX_SECONDS}s)"
        return
    fi

    # raw URL 은 CDN 캐시(max-age=300)로 최대 300초 지연. version 필드가 바뀔 때까지 폴링.
    # 진행 상황 판단용: 응답의 Source-Age 가 300 에 닿으면 그 직후 갱신된다.
    local elapsed=0 remote_version=""
    while (( elapsed < POLL_MAX_SECONDS )); do
        remote_version=$(curl -fsSL "$url" 2>/dev/null \
                         | grep -oE '"version"\s*:\s*"[^"]+"' \
                         | head -1 | sed -E 's/.*"([^"]+)"$/\1/' || true)
        if [[ "$remote_version" == "$NEW_VERSION" ]]; then
            ok "전파 확인: version.json version=$remote_version (${elapsed}s)"
            return
        fi
        printf '  %s대기 중%s ... 원격=%s (목표=%s, %ds)\n' \
            "$C_DIM" "$C_RESET" "${remote_version:-?}" "$NEW_VERSION" "$elapsed"
        sleep "$POLL_INTERVAL_SECONDS"
        elapsed=$((elapsed+POLL_INTERVAL_SECONDS))
    done

    warn "전파 확인 시간 초과(${POLL_MAX_SECONDS}s). 원격 version=${remote_version:-?}"
    warn "CDN 지연이 아니라 실제 반영 실패일 수 있습니다 — raw 가 아닌 API 로 진위 확인:"
    warn "  gh api repos/$RELEASES_OWNER/$RELEASES_REPO/contents/version.json --jq '.content' | base64 -d"
    warn "위 결과가 $NEW_VERSION 이면 배포는 정상이고 CDN 캐시만 남은 것입니다. 아니면 [5] 실패:"
    warn "  curl -s $url"
}

# ── 최종 확인 프롬프트 ────────────────────────────────────────────────────
confirm_proceed() {
    [[ $ASSUME_YES -eq 1 ]] && return 0
    [[ $DRY_RUN -eq 1 ]]    && return 0
    printf '\n%s%s → %s%s 배포를 진행합니다. 계속? [y/N] ' \
        "$C_BOLD" "$CURRENT" "$NEW_VERSION" "$C_RESET"
    local reply
    read -r reply
    [[ "$reply" =~ ^[Yy]$ ]] || { log "중단되었습니다."; exit 1; }
}

# ── 메인 ─────────────────────────────────────────────────────────────────
main() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '%s=== deploy.sh DRY RUN ===%s\n' "$C_BOLD" "$C_RESET"
    else
        printf '%s=== deploy.sh ===%s\n' "$C_BOLD" "$C_RESET"
    fi

    run_step_preflight
    run_step_bump
    confirm_proceed
    run_step_version_py
    run_step_build_publish
    run_step_verify_asset
    run_step_publish_version_json
    run_step_git
    run_step_verify_propagation

    printf '\n%s═══ 배포 완료 ═══%s\n' "$C_GREEN" "$C_RESET"
    printf '  %s → %s\n' "$CURRENT" "$NEW_VERSION"
    printf '  노트: %s\n' "$NOTES"
    printf '  에셋: https://github.com/%s/%s/releases/tag/v%s\n' \
        "$RELEASES_OWNER" "$RELEASES_REPO" "$NEW_VERSION"
    printf '  version.json: https://raw.githubusercontent.com/%s/%s/main/version.json\n' \
        "$RELEASES_OWNER" "$RELEASES_REPO"
    printf '  %s기존 PC는 다음 시작 시(또는 1시간 주기 확인, 4시간 스로틀) 업데이트를 감지합니다.%s\n' \
        "$C_DIM" "$C_RESET"
}

main "$@"

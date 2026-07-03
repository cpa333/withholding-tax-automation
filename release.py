"""릴리스 헬퍼 (개발자 전용).

새 버전 배포 절차:
  1. src/version.py 의 __version__ 을 올린다 (예: "1.0.1").
  2. python release.py              → 빌드 + sha256/size 계산 + version.json 생성 + 게시 명령 출력
     python release.py --publish    → 추가로 `gh release create` 로 설치파일 에셋 업로드까지 실행
     python release.py --mandatory  → version.json mandatory=true (강제 업데이트)
     python release.py --notes "..."→ 릴리스 노트 지정

전제:
  - 개발자 PC에 gh(GitHub CLI) 로그인 + Inno Setup(ISCC) 설치.
  - 설치파일과 version.json 은 '공개' 릴리스 저장소에 게시되고, 앱은 토큰 없이
    공개 raw URL 로 version.json 만 읽는다. **클라이언트에는 어떤 비밀키도 없음.**

주의: version.json 은 공개 저장소 main 브랜치 루트에 커밋되어야 앱이 조회한다
(앱은 releases/latest API 가 아니라 고정 raw URL 을 읽음). 에셋(설치파일)은
릴리스에 업로드한다.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.version import __version__          # noqa: E402
from src.utils import updater                # noqa: E402

REPO = f"{updater.RELEASES_OWNER}/{updater.RELEASES_REPO}"
INSTALLER = os.path.join("installer_output", "원천징수자동화_설치.exe")
# GitHub release 에셋명은 ASCII만 안전 — 한글 파일명은
#   (1) gh CLI 업로드 시 _.exe 로 깨지고,
#   (2) updater 가 URL 을 urllib 로 요청할 때 UnicodeEncodeError/404 를 낸다.
# 따라서 공개 release 에셋은 ASCII 이름으로 올리고, 사용자 PC 로컬 저장명은
# updater 가 APP_NAME 기반(원천징수자동화_설치.exe)으로 별도 지정한다.
ASSET_NAME = "whta_setup.exe"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def virustotal_preflight(path: str) -> None:
    """배포 전 VirusTotal 스캔 — Defender 오탐(0x800700E1) 회귀 조기 감지.

    VT_API_KEY 환경변수 + vt-cli(`vt`) 가 모두 있을 때만 동작(미설정 시 스킵).
    업로드만 수행한다 — 결과는 VT 웹에서 수동 확인 후 탐지 다수(≥10/72) 시 릴리스 중단.
    """
    api_key = os.environ.get("VT_API_KEY")
    if not api_key or shutil.which("vt") is None:
        print("[VT] VirusTotal 게이트 미설정(VT_API_KEY 또는 vt-cli 없음) — 스킵")
        return
    print(f"[VT] {path} 스캔 업로드 중(수분 소요 가능)...")
    try:
        rc = subprocess.run(["vt", "scan", "file", path]).returncode
    except FileNotFoundError:
        print("[VT][WARN] vt-cli 실행 실패 — 스킵")
        return
    if rc != 0:
        print("[VT][WARN] 업로드 실패 — VT 웹에서 수동 확인 권장")
    else:
        print("[VT] 업로드 완료. VT 웹에서 탐지 엔진 수 확인 후 이상 시 릴리스 중단.")


def main():
    ap = argparse.ArgumentParser(description="원천징수 자동화 릴리스 헬퍼")
    ap.add_argument("--skip-build", action="store_true",
                    help="build.py 실행 생략 (기존 installer_output 사용)")
    ap.add_argument("--publish", action="store_true",
                    help="gh release create 로 에셋 업로드까지 실행")
    ap.add_argument("--mandatory", action="store_true",
                    help="version.json mandatory=true (강제 업데이트)")
    ap.add_argument("--min-supported", default="",
                    help="version.json min_supported (이 버전 미만은 강제 업데이트)")
    ap.add_argument("--notes", default="버그 수정 및 기능 개선",
                    help="릴리스 노트")
    args = ap.parse_args()

    version = __version__
    tag = f"v{version}"
    print(f"=== 릴리스 준비: {tag}  (공개 저장소: {REPO}) ===")

    # [1] 빌드
    if not args.skip_build:
        print("\n[1] build.py 실행...")
        if subprocess.run([sys.executable, "build.py"]).returncode != 0:
            print("[ERROR] 빌드 실패")
            sys.exit(1)

    if not os.path.exists(INSTALLER):
        print(f"[ERROR] 설치파일이 없습니다: {INSTALLER}")
        sys.exit(1)

    # [2] 해시 / 크기
    size = os.path.getsize(INSTALLER)
    digest = sha256_of(INSTALLER)
    print(f"\n[2] {INSTALLER}")
    print(f"    size   = {size:,} bytes")
    print(f"    sha256 = {digest}")

    # [3] version.json 생성
    info = {
        "version": version,
        "mandatory": bool(args.mandatory),
        "min_supported": args.min_supported,   # 빈 문자열이면 강제 아님
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{ASSET_NAME}",
        "sha256": digest,
        "size": size,
        "notes": args.notes,
        "released": date.today().isoformat(),
    }
    out = os.path.join("installer_output", "version.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"\n[3] version.json 생성: {out}")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    # [4] 게시 안내
    print("\n[4] 게시")
    print("  (a) 릴리스 에셋 업로드 (에셋명은 ASCII):")
    print(f"      cp \"{INSTALLER}\" installer_output/{ASSET_NAME}")
    print(f"      gh release create {tag} \"installer_output/{ASSET_NAME}\" "
          f"--repo {REPO} --title \"{tag}\" --notes \"{args.notes}\"")
    print("  (b) version.json 을 공개 저장소 main 에 커밋 (앱이 raw URL 로 조회):")
    print(f"      {out} → {REPO} 저장소 루트 version.json 으로 복사 후 commit/push")
    print(f"      조회 URL: {updater.VERSION_JSON_URL}")

    if args.publish:
        # Defender 오탐 회귀 조기 감지 — VirusTotal 사전 스캔(미설정 시 no-op)
        virustotal_preflight(INSTALLER)
        print("\n[4-a] gh release create 실행...")
        # 에셋명은 ASCII(ASSET_NAME)로 업로드 — 한글 파일명은 gh 가 _.exe 로 깨뜨리고
        # updater 의 URL 요청도 실패시킨다. 같은 내용을 ASCII 이름으로 복사해 업로드.
        upload_file = os.path.join("installer_output", ASSET_NAME)
        try:
            import shutil
            shutil.copyfile(INSTALLER, upload_file)
        except Exception as e:
            print(f"[ERROR] 업로드용 파일 복사 실패: {e}")
            rc = 1
        else:
            try:
                rc = subprocess.run([
                    "gh", "release", "create", tag, upload_file,
                    "--repo", REPO, "--title", tag, "--notes", args.notes,
                ]).returncode
            except FileNotFoundError:
                print("[ERROR] 'gh' CLI가 설치되어 있지 않습니다. https://cli.github.com/")
                rc = 1
        if rc != 0:
            print("[WARN] gh release create 실패. 수동 확인 필요.")
        else:
            print("[OK] 에셋 업로드 완료.")
        print("  ※ version.json 을 공개 저장소 main 에 커밋하세요:")
        print(f"      {out} → {REPO} 루트 version.json")

        # 게시 후 version.json 검증
        print("\n[5] version.json 검증...")
        try:
            import urllib.request
            with urllib.request.urlopen(updater.VERSION_JSON_URL, timeout=5) as resp:
                remote_info = json.loads(resp.read().decode("utf-8"))
            if remote_info.get("version") == version:
                print(f"[OK] version.json 확인: v{version} ✓")
            else:
                print(f"[WARN] version.json 불일치! 원격={remote_info.get('version')}, 로컬={version}")
                print("       공개 저장소에 아직 커밋하지 않은 것 같습니다.")
        except Exception as e:
            print(f"[INFO] version.json 조회 실패 ({e})")
            print("       공개 저장소에 커밋 후 다시 실행하여 확인하세요.")


if __name__ == "__main__":
    main()

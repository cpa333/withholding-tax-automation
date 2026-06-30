#!/usr/bin/env python3
"""EDI 보안프로그램 영속성 진단 도구 (다중 신호).

한국 EDI 포털(NPS/NHIS)의 "보안프로그램 설치" 상태를 3계층에서 진단한다.

[배경 — 2026-06 조사 정정]
  한국 보안프로그램은 대부분 Chrome "확장"이 아니라 **네이티브 앱(로컬 서버)**
  이다. 웹스토어 공개 확장은 TouchEn PC보안 확장(ID dncepekefegjiljlfbihgogephdhph)
  단 한 개뿐. Veraport(127.0.0.1:16106), IPinside(localhost:21300, I3GProc.exe),
  AnySign/nProtect/SignKorea/MAGIC-PKI는 모두 시스템 전역 네이티브.
  → "설치됨" 판정이 단일 extension ID 로 안 통하므로 다중 신호로 본다.

[3계층 진단]
  1) 시스템 전역(PC 단위): Veraport/IPinside 로컬포트 + 네이티브 프로세스.
     → "이 PC에 보안프로그램이 설치는 돼 있는가" (프로필 무관)
  2) 프로필 귀속(확장): Extensions 폴더 + 키워드/TouchEn ID.
  3) 프로필 귀속(세션): 포털 도메인(nps/nhis) 쿠키 + LocalStorage 존재.
     → "이 프로필이 이전 실행의 설치/로그인 상태를 유지하고 있는가"
     (이것이 빈 프로필에서 매번 리셋되는 = 재설치 메뉴 반복의 원인 후보)

[결론 해석]
  - 네이티브 미설치 → 재설치 메뉴는 정상(최초 1회 설치 필요).
  - 네이티브 설치됨 + 병렬 영속 프로필에 세션/확장 있음 → 재설치 안 뜰 것(수정 정상).
  - 네이티브 설치됨 + 병렬 영속 프로필 비어있음 → 재설치 뜰 수 있음(문제 지속).

주의: 프로필 귀속 신호 유무는 "상관적 증거"일 뿐, 최종 판정은 실제 2회 실행으로
포털이 재설치 메뉴를 띄우는지 확인해야 한다.

사용:  python scripts/diagnose_edi_profiles.py
"""

import glob
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse

# scripts/ 에서 실행해도 src import 가 되도록 repo root 추가
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from src.config import APP_DATA_DIR
from src.utils.chrome_cdp import find_chrome_user_data, find_chrome_profile

# ── 보안/로그인 분류 키워드 (manifest name / 프로세스명 소문자 부분매칭) ──
# (2026-06 웹조사 기반: TouchEn/Veraport/IPinside/INISAFE/AnySign/nProtect/
#  SignKorea/CrossCert/DreamSecurity MagicXFN/KFTC/IPIN/AhnLab)
SECURITY_KEYWORDS = [
    # RaonSecure TouchEn nxKey
    "touchen", "nxkey", "라온시큐어", "raonsecure", "raon",
    # WIZVERA Veraport (통합설치)
    "veraport", "wizvera", "베라포트", "위즈베라",
    # Interezen IPinside LWS
    "ipinside", "intersafe", "아이피인사이드", "인터리젠", "interezen", "i3gproc",
    # INITECH INISAFE CrossWeb
    "inisafe", "crossweb", "크로스웹", "이니텍", "initech",
    # HancomSecure/SoftForum AnySign
    "anysign", "한컴시큐어", "hancomsecure", "softforum", "소프트포럼",
    # nProtect Online Security
    "nprotect", "npkpass", "np뱅크팩", "inkautoworks", "npsafe",
    # SignKorea
    "signkorea", "사인코리아", "signgate",
    # CrossCert 한국전자인증
    "crosscert", "크로스서트", "한국전자인증",
    # Dreamsecurity MagicXFN / MAGIC-PKI
    "magicxfn", "magic-pki", "매직파서", "드림시큐리티", "dreamsecurity", "magic xsign",
    # 금융결제원 / 금융인증서 / IPIN
    "kftc", "금융결제원", "금융인증서", "yessign", "yeskey", "ipin", "아이핀",
    # AhnLab Safe Transaction / V3
    "ahnlab", "astx", "safe transaction", "v3",
    # 일반 한국어 (manifest name 이 한글인 경우)
    "보안", "인증서", "공동인증", "금융인증", "키보드보안",
]

# 웹스토어 공개/검증된 extension ID (확정 1종). 그 외 ID는 신뢰도 낮아 제외.
KNOWN_EXT_IDS = {
    "dncepekefegjiljlfbihgogephdhph": "TouchEn PC보안 확장 (라온시큐어)",
}

# 포털 도메인 (쿠키/LocalStorage 세션 신호용)
PORTAL_DOMAINS = ["nps.or.kr", "nhis.or.kr"]

# 네이티브 보안프로세스 (소문자, .exe 포함)
NATIVE_PROCESSES = [
    "i3gproc.exe", "astx.exe", "anysign4pc.exe", "anysign.exe", "npkpass.exe",
    "veraport.exe", "inisafe5.exe", "crosswebex.exe", "touchennxkey.exe",
    "magicpki.exe", "v3lite.exe", "npbankpack.exe",
]

_VERAPORT_PORT = 16106   # Veraport 로컬 서버
_IPINSIDE_PORT = 21300   # IPinside LWS Agent 로컬 서버

_SKIP_PROFILES = {"Snapshots", "System Profile", "Guest Profile", "Guest Profile 1"}


# ── JSON / manifest ──────────────────────────────────────────────────────────

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _resolve_msg_name(manifest, ext_dir):
    """manifest name 이 __MSG_x__ 이면 _locales 에서 해석."""
    name = manifest.get("name", "") if isinstance(manifest, dict) else ""
    if isinstance(name, str) and name.startswith("__MSG_") and name.endswith("__"):
        key = name[6:-2]
        locale = manifest.get("default_locale", "")
        for cand in ([locale] if locale else []) + ["ko", "en", "en_US", "ko_KR"]:
            msgs = _read_json(os.path.join(ext_dir, "_locales", cand, "messages.json"))
            if isinstance(msgs, dict) and key in msgs:
                val = msgs[key]
                if isinstance(val, dict) and "message" in val:
                    return val["message"]
                return str(val)
    return name or "(이름 없음)"


# ── 프로필 귀속 신호 ──────────────────────────────────────────────────────────

def list_extensions(profile_dir):
    """Extensions 폴더에서 설치된 확장: [{id, name, version, security, known}]."""
    ext_root = os.path.join(profile_dir, "Extensions")
    out = []
    if not os.path.isdir(ext_root):
        return out
    try:
        ext_ids = os.listdir(ext_root)
    except OSError:
        return out
    for ext_id in ext_ids:
        ext_id_dir = os.path.join(ext_root, ext_id)
        if not os.path.isdir(ext_id_dir):
            continue
        try:
            versions = [v for v in os.listdir(ext_id_dir)
                        if os.path.isdir(os.path.join(ext_id_dir, v))]
        except OSError:
            continue
        if not versions:
            continue
        version = sorted(versions)[-1]
        ver_dir = os.path.join(ext_id_dir, version)
        manifest = _read_json(os.path.join(ver_dir, "manifest.json")) or {}
        name = _resolve_msg_name(manifest, ver_dir)
        name_l = (name or "").lower()
        known = ext_id in KNOWN_EXT_IDS
        security = known or any(k in name_l for k in SECURITY_KEYWORDS)
        out.append({"id": ext_id, "name": name, "version": version,
                    "security": security, "known": known})
    return out


def _open_cookies_ro(path):
    """Chrome Cookies(SQLite) 를 읽기 전용으로. 잠금 회피용 복사 폴백 포함."""
    # 1) URI 읽기전용
    try:
        quoted = urllib.parse.quote(path.replace("\\", "/"))
        con = sqlite3.connect(f"file:{quoted}?mode=ro&immutable=1", uri=True)
        con.execute("SELECT 1 FROM cookies LIMIT 1")
        return con
    except Exception:
        pass
    # 2) 임시 복사 후 읽기 (Chrome 실행 중 잠금 대비)
    try:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy2(path, tmp)
        con = sqlite3.connect(tmp)
        con.execute("SELECT 1 FROM cookies LIMIT 1")
        return con
    except Exception:
        return None


def portal_cookies(profile_dir):
    """포털 도메인 쿠키 host_key 집합 반환 (있으면 세션 존재 신호)."""
    for rel in ("Network/Cookies", "Cookies"):
        path = os.path.join(profile_dir, rel)
        if not os.path.exists(path):
            continue
        con = _open_cookies_ro(path)
        if con is None:
            return None  # 읽기 실패(Chrome 실행 중일 수 있음)
        try:
            rows = con.execute("SELECT DISTINCT host_key FROM cookies").fetchall()
        except Exception:
            return None
        finally:
            con.close()
        found = set()
        for (hk,) in rows:
            hk_l = (hk or "").lower()
            if any(d in hk_l for d in PORTAL_DOMAINS):
                found.add(hk)
        return found
    return set()


def portal_localstorage(profile_dir):
    """Local Storage leveldb 에 포털 도메인 문자열이 있는지 (True/False/None=오류)."""
    ldb_dir = os.path.join(profile_dir, "Local Storage", "leveldb")
    if not os.path.isdir(ldb_dir):
        return False
    needles = [d.encode("ascii", "ignore") for d in PORTAL_DOMAINS]
    try:
        for f in glob.glob(os.path.join(ldb_dir, "*")):
            if not os.path.isfile(f):
                continue
            try:
                with open(f, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if any(n and n in data for n in needles):
                return True
    except Exception:
        return None
    return False


# ── 시스템 전역 신호 ──────────────────────────────────────────────────────────

def _port_open(port, host="127.0.0.1", timeout=0.4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return False


def _running_processes():
    """tasklist 에서 실행 중인 이미지 이름(소문자) 집합."""
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                           capture_output=True, timeout=10)
        out = r.stdout.decode("utf-8", errors="ignore") \
            if r.stdout else ""
        names = set()
        for line in out.splitlines():
            line = line.strip()
            if not line or "," not in line:
                continue
            # CSV 첫필드 = "이름" (따옴표)
            first = line.split(",", 1)[0].strip().strip('"').lower()
            if first:
                names.add(first)
        return names
    except Exception:
        return set()


def native_security_state():
    """PC 단위 보안프로그램 네이티브 설치 상태."""
    procs = _running_processes()
    found_procs = sorted(p for p in NATIVE_PROCESSES if p in procs)
    return {
        "veraport_port": _port_open(_VERAPORT_PORT),
        "ipinside_port": _port_open(_IPINSIDE_PORT),
        "processes": found_procs,
        "any": bool(found_procs) or _port_open(_VERAPORT_PORT) or _port_open(_IPINSIDE_PORT),
    }


# ── 스캔 대상 ─────────────────────────────────────────────────────────────────

def profile_dirs_to_scan():
    targets = []
    nps = os.path.join(APP_DATA_DIR, "chrome-profiles", "cdp-9223")
    nhis = os.path.join(APP_DATA_DIR, "chrome-profiles", "cdp-9224")
    targets.append(("병렬 영속 cdp-9223 (NPS/국민연금)", nps, "Default", "parallel"))
    targets.append(("병렬 영속 cdp-9224 (NHIS/건강보험)", nhis, "Default", "parallel"))
    tmp = os.environ.get("TEMP", "")
    if tmp:
        for port in (9223, 9224):
            targets.append((f"구 TEMP chrome-cdp-{port} (수정전)",
                            os.path.join(tmp, f"chrome-cdp-{port}"), "Default", "temp"))
    ud = find_chrome_user_data()
    if ud:
        active = find_chrome_profile(ud)
        try:
            names = os.listdir(ud)
        except OSError:
            names = []
        for name in names:
            full = os.path.join(ud, name)
            if name in _SKIP_PROFILES:
                continue
            if not (os.path.isdir(full)
                    and os.path.isdir(os.path.join(full, "Extensions"))):
                continue
            label = f"실제 Chrome [{name}]"
            if name == active:
                label += "  ★활성프로필"
            targets.append((label, ud, name, "real"))
    return targets


# ── 출력 ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 78)
    print("EDI 보안프로그램 영속성 진단 (다중 신호)")
    print("=" * 78)
    print(f"APP_DATA_DIR : {APP_DATA_DIR}")
    ud = find_chrome_user_data()
    print(f"실제 Chrome  : {ud or '(탐지 못함)'}")
    print()

    # ── 1) 시스템 전역(네이티브) ──
    nat = native_security_state()
    print("── 시스템 전역(PC 단위) 보안프로그램 네이티브 ──")
    print(f"  Veraport 로컬포트(16106) : {'감지됨' if nat['veraport_port'] else '미감지'}")
    print(f"  IPinside 로컬포트(21300) : {'감지됨' if nat['ipinside_port'] else '미감지'}")
    if nat["processes"]:
        print(f"  실행 중 네이티브 프로세스 : {', '.join(nat['processes'])}")
    else:
        print("  실행 중 네이티브 프로세스 : (없음)")
    if nat["any"]:
        print("  → PC에 보안프로그램 네이티브 설치됨. 이후 포털 재설치 메뉴는")
        print("    '이 프로필이 상태를 유지하느냐' 에 달림.")
    else:
        print("  → ⚠ PC에 보안프로그램 네이티브 미설치 가능. 이 경우 재설치 메뉴는")
        print("    정상(최초 1회 설치 필요)이며 프로필 문제가 아님.")
    print()

    # ── 2) 프로필별 ──
    parallel_signal = {"9223": False, "9224": False}
    for label, udd, prof, kind in profile_dirs_to_scan():
        prof_dir = os.path.join(udd, prof)
        print("-" * 78)
        print(f"[{label}]")
        print(f"  경로: {prof_dir}")
        if not os.path.isdir(prof_dir):
            print("  ⚠ 프로필 미생성 (1회 실행 전)")
            print()
            continue

        # 확장
        exts = list_extensions(prof_dir)
        sec_ext = [e for e in exts if e["security"]]
        print(f"  확장: 전체 {len(exts)}개 / 보안 {len(sec_ext)}개")
        for e in sec_ext:
            tag = " [확정ID]" if e["known"] else ""
            print(f"    • {e['name']}  (id={e['id']}{tag})")

        # 포털 세션(쿠키/LS)
        ck = portal_cookies(prof_dir)
        ls = portal_localstorage(prof_dir)
        ck_s = ("없음" if ck == set() else
                ", ".join(sorted(ck)) if ck else "읽기실패(Chrome 실행중?)")
        if ls is None:
            ls_s = "읽기오류"
        else:
            ls_s = "있음" if ls else "없음"
        print(f"  포털 쿠키(nps/nhis)      : {ck_s}")
        print(f"  포털 LocalStorage        : {ls_s}")

        session_present = bool(ck) or bool(ls)
        if kind == "parallel":
            port_key = "9223" if "9223" in label else "9224"
            if sec_ext and session_present:
                parallel_signal[port_key] = True
                print("  ✅ 보안확장 + 포털 세션 모두 존재 → 상태 유지 중 (수정 정상 예상)")
            elif sec_ext:
                parallel_signal[port_key] = True
                print("  ◕ 보안확장은 있음(포털 세션 없음) → 감지가 확장 기반이면 양호")
            elif session_present:
                parallel_signal[port_key] = True
                print("  ⚠ 포털 세션은 있으나 보안 확장(TouchEn 등) 없음")
                print("    → 포털이 확장으로 설치여부를 감지한다면 재설치 메뉴 가능")
            else:
                print("  ❌ 보안 신호 없음(확장·세션 모두 없음) → 재설치 뜰 수 있음")
        print()

    # ── 3) 종합 ──
    print("=" * 78)
    if not nat["any"]:
        print("종합: PC 자체에 보안프로그램이 안 깔려 있을 수 있습니다. 먼저 포털에서")
        print("      1회 설치 후 다시 돌려보세요. (프로필 문제가 아닐 수 있음)")
    elif all(parallel_signal.values()):
        print("종합: 병렬 영속 프로필(cdp-9223/9224)이 보안 상태를 유지 중 — 수정 정상 예상.")
        print("      최종 확정은 실제 Phase2 2회 실행으로 재설치 메뉴가 안 뜨는지 확인.")
    else:
        miss = [k for k, v in parallel_signal.items() if not v]
        print(f"종합: 병렬 영속 프로필({','.join(miss)})에 보안 신호가 없습니다.")
        print("      → Phase2 를 1회 실행(보안프로그램 설치+로그인)한 뒤 이 스크립트를")
        print("        다시 돌리면 cdp-9223/9224 에 세션/확장이 잡혀야 합니다.")


if __name__ == "__main__":
    main()

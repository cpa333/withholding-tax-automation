"""다운로드 저장 경로 생성 유틸리티

모든 EDI 자동화(NPS/NHIS)에서 공유하는 저장 경로 생성 함수.
구조: <바탕화면>/{사이트명}_{YYYYMM}/{수임처명}/

바탕화면 경로는 OneDrive 백업/한국어 윈도우/GPO 리다이렉션에
무관하게 Windows Shell API로 실제 경로를 구한다 (get_desktop_path).
바탕화면이 쓰기 불가(회사 GPO/OneDrive 오프라인)일 때를 대비해
문서/홈/LOCALAPPDATA/TEMP 로 순차 폴백한다.
"""
import os
from datetime import datetime


APP_SLUG = "원천징수자동화"


def _documents_path() -> str:
    """내 문서 경로 (CSIDL_PERSONAL=5). 실패 시 빈 문자열."""
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.shell32.SHGetFolderPathW(0, 5, 0, 0, buf)
            if buf.value:
                return buf.value
        except Exception:
            pass
    return ""


def _local_app_data() -> str:
    """%LOCALAPPDATA% 경로. 실패 시 빈 문자열."""
    return os.environ.get("LOCALAPPDATA", "")


def get_desktop_path() -> str:
    """실제 바탕화면 절대 경로 반환 (OneDrive/한국어/GPO 리다이렉션 대응).

    Windows Shell API(SHGetFolderPathW)로 시스템에 등록된 진짜 바탕화면
    경로를 가져온다. OneDrive 바탕화면 백업으로 홈 폴더 아래 'Desktop'이
    아니라 'OneDrive\\Desktop'(영문) 또는 'OneDrive\\바탕화면'(한국어)으로
    리다이렉션된 경우에도 정확한 경로를 반환한다.

    비-Windows 또는 API 호출 실패 시 홈 폴더 아래 'Desktop'으로 폴백.
    """
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(512)
            # CSIDL_DESKTOP(=0): 현재 사용자의 바탕화면
            ctypes.windll.shell32.SHGetFolderPathW(0, 0, 0, 0, buf)
            if buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def make_save_dir(
    site_name: str,
    client_name: str,
    year: int | None = None,
    month: int | None = None,
    subdir: str | None = None,
) -> str:
    """다운로드 디렉토리 경로 생성 (없으면 생성)

    구조: ~/Desktop/{site_name}_{YYYYMM}/{client_name}/[/{subdir}/]
    subdir 가 주어지면 수임처 폴더 아래 추가 하위폴더를 만든다.

    병렬(2번) 실행 시 두 CLI 가 공통 최상위(예: 공단EDI)를 쓰면서도 포털별로
    ~/Desktop/공단EDI_{YYYYMM}/{client}/{국민연금|국민건강보험}/ 처럼 분리하기 위해
    사용 — 두 Chrome 이 서로 다른 폴더에 써서 listdir/cleanup 파일 레이스를 없앤다.
    단일 실행은 subdir=None 으로 현행 구조({site}_{period}/{client}/) 유지.

    이미 폴더가 존재하면 그대로 재사용하고, 없으면 생성.

    Args:
        site_name: 사이트 식별명 (예: "국민연금", "국민건강보험", "공단EDI")
        client_name: 수임처명 (공백은 '_'로 치환)
        year: 대상 연도 (기본: 현재 년도)
        month: 대상 월 (기본: 현재 월)
        subdir: 수임처 폴더 아래 추가 하위폴더명 (병렬 포털 분리용). None 시 미사용.

    Returns:
        생성된 디렉토리 절대 경로
    """
    now = datetime.now()
    y = year if year is not None else now.year
    m = month if month is not None else now.month
    period = f"{y}{m:02d}"

    folder_name = client_name.replace(" ", "_")
    parts = [f"{site_name}_{period}", folder_name]
    if subdir:
        parts.append(subdir)
    rel = os.path.join(*parts)
    desktop = get_desktop_path()
    save_dir = os.path.join(desktop, rel)

    # 바탕화면이 읽기전용(회사 GPO)이거나 OneDrive 오프라인 동기화 중단 등으로
    # 쓸 수 없으면, 자동화 전체가 예외로 멈추고 windowed 모드라 원인이 안 보인다.
    # 실패 시 사용자 쓰기 가능 경로(문서 폴더 → 홈 → LOCALAPPDATA)로 순차 폴백.
    for base in (desktop, _documents_path(),
                 os.path.expanduser("~"), _local_app_data()):
        if not base:
            continue
        candidate = os.path.join(base, rel)
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue

    # 모든 폴백 실패 — 최후 수단으로 TEMP(거의 항상 쓰기 가능)에 시도.
    import tempfile
    fallback = os.path.join(tempfile.gettempdir(), APP_SLUG, rel)
    os.makedirs(fallback, exist_ok=True)
    return fallback

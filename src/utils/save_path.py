"""다운로드 저장 경로 생성 유틸리티

모든 EDI 자동화(NPS/NHIS)에서 공유하는 저장 경로 생성 함수.
구조: <바탕화면>/{사이트명}_{YYYYMM}/{수임처명}/

바탕화면 경로는 OneDrive 백업/한국어 윈도우/GPO 리다이렉션에
무관하게 Windows Shell API로 실제 경로를 구한다 (get_desktop_path).
"""
import os
from datetime import datetime


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
) -> str:
    """다운로드 디렉토리 경로 생성 (없으면 생성)

    구조: ~/Desktop/{site_name}_{YYYYMM}/{client_name}/

    이미 폴더가 존재하면 그대로 재사용하고, 없으면 생성.

    Args:
        site_name: 사이트 식별명 (예: "국민연금", "국민건강보험")
        client_name: 수임처명 (공백은 '_'로 치환)
        year: 대상 연도 (기본: 현재 년도)
        month: 대상 월 (기본: 현재 월)

    Returns:
        생성된 디렉토리 절대 경로
    """
    now = datetime.now()
    y = year if year is not None else now.year
    m = month if month is not None else now.month
    period = f"{y}{m:02d}"

    folder_name = client_name.replace(" ", "_")
    save_dir = os.path.join(
        get_desktop_path(),
        f"{site_name}_{period}",
        folder_name,
    )
    os.makedirs(save_dir, exist_ok=True)
    return save_dir

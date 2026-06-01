"""다운로드 저장 경로 생성 유틸리티

모든 EDI 자동화(NPS/NHIS)에서 공유하는 저장 경로 생성 함수.
구조: ~/Desktop/{사이트명}_{YYYYMM}/{수임처명}/
"""
import os
from datetime import datetime


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
        os.path.expanduser("~"), "Desktop",
        f"{site_name}_{period}",
        folder_name,
    )
    os.makedirs(save_dir, exist_ok=True)
    return save_dir

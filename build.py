"""원천징수 자동화 GUI PyInstaller 빌드 스크립트

사용법: python build.py
결과물: dist/원천징수자동화.exe
"""
import subprocess
import sys
import os


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    cmd = [
        sys.executable, "-m", "PyInstaller",

        # 출력 설정
        "--name", "원천징수자동화",
        "--noconfirm",

        # GUI 모드 (콘솔 창 숨김)
        "--windowed",

        # 단일 exe
        "--onefile",
        "--noupx",

        # comtypes 동적 생성 경로
        "--runtime-tmpdir", ".",

        # PySide6
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--collect-submodules=PySide6",

        # Playwright
        "--hidden-import=playwright",
        "--hidden-import=playwright.async_api",
        "--hidden-import=playwright._impl",
        "--collect-submodules=playwright",

        # playwright-stealth
        "--hidden-import=playwright_stealth",
        "--collect-submodules=playwright_stealth",

        # pywinauto + comtypes
        "--hidden-import=comtypes",
        "--hidden-import=comtypes.client",
        "--hidden-import=comtypes.gen",
        "--hidden-import=pywinauto",
        "--hidden-import=pywinauto.backend",
        "--hidden-import=pywinauto.backend.uia_element_info",
        "--hidden-import=pywinauto.backend.uia_wrap",
        "--collect-submodules=comtypes",
        "--collect-submodules=pywinauto",

        # openpyxl
        "--hidden-import=openpyxl",

        # 리소스 파일 번들
        "--add-data",
        os.path.join("src", "ui", "resources", "style.qss") + ";src/ui/resources",

        # 진입점
        "gui_main.py",
    ]

    print("빌드 시작...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode == 0:
        exe_path = os.path.join("dist", "원천징수자동화.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n빌드 성공: {exe_path} ({size_mb:.1f} MB)")
        else:
            print("\n빌드 완료되었으나 exe 파일을 찾을 수 없습니다.")
    else:
        print(f"\n빌드 실패 (exit code: {result.returncode})")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

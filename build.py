"""WEHAGO 자동화 PyInstaller 빌드 스크립트

사용법: python build.py
결과물: dist/WEHAGO자동화.exe
"""
import subprocess
import sys
import os


def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "WEHAGO자동화",
        "--hidden-import=comtypes",
        "--hidden-import=comtypes.client",
        "--hidden-import=comtypes.gen",
        "--hidden-import=pywinauto",
        "--hidden-import=pywinauto.backend",
        "--hidden-import=pywinauto.backend.uia_element_info",
        "--hidden-import=pywinauto.backend.uia_wrap",
        "--hidden-import=openpyxl",
        "--hidden-import=playwright",
        "--hidden-import=playwright.async_api",
        "--collect-submodules=comtypes",
        "--collect-submodules=pywinauto",
        "--noupx",
        # comtypes 동적 생성 경로
        "--runtime-tmpdir", ".",
        "main.py",
    ]

    print("빌드 시작...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    if result.returncode == 0:
        exe_path = os.path.join("dist", "WEHAGO자동화.exe")
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

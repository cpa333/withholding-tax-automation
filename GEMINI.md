# Withholding Tax Automation

This project automates withholding tax processes by controlling external platforms (Health Insurance Corporation, WEHAGO, Hometax) and is delivered as a Windows executable.

## Project Overview
The application is a Python-based Windows automation tool designed to streamline tax-related tasks across multiple Korean platforms.

### Core Modules
1. **Health Insurance Corporation Control (공단 사이트 제어):** Automation of tasks on the National Health Insurance platform.
2. **WEHAGO Control (WEHAGO 제어):** Automation of data entry or retrieval from the WEHAGO accounting platform.
3. **Hometax Control (홈택스 제어):** Automation of withholding tax filing via file conversion on the National Tax Service (Hometax) platform.

## Architecture & Tech Stack
- **Language:** Python 3.10+
- **Platform:** Windows (.exe via PyInstaller or Nuitka)
- **Automation:** Selenium, Playwright, or PyAutoGUI (depending on the target site complexity)
- **UI:** (Optional) PyQt6 or Tkinter for user interaction

## Building and Running
- **Development:** `python main.py`
- **Packaging:** *TODO: Add specific PyInstaller/Nuitka command for generating .exe*

## Development Conventions
- **Module Separation:** Each control module (공단, WEHAGO, 홈택스) should be isolated in its own package/script.
- **Error Handling:** Robust exception handling for network timeouts and UI changes on external sites.
- **Security:** Sensitive credentials must be handled securely (e.g., encrypted local storage or user input, never hardcoded).

## Directory Structure
- `src/`
    - `automation/`
        - `nhis/` (공단) — 건강보험공단 자동화
        - `wehago/` — WEHAGO 급여 자동화
        - `hometax/` — 홈택스 원천세 신고 자동화
    - `ui/`
    - `utils/`
- `results/` — 다운로드/변환된 엑셀 파일
- `build/`
- `main.py`

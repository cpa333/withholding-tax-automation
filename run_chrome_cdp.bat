@echo off
"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9223 --user-data-dir=%TEMP%\chrome-cdp-temp-profile --start-maximized https://www.wehago.com/#/main

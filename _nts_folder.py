"""WehagoNTS 폴더 선택 - 키보드 탐색으로 Desktop 폴더 선택"""
import sys
import os
import time
import ctypes
import ctypes.wintypes

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# 바탕화면 폴더 생성
desktop_path = os.path.join(os.environ['USERPROFILE'], 'Desktop')
folder_name = 'WEHAGO_전자신고'
target_path = os.path.join(desktop_path, folder_name)

if os.path.exists(target_path):
    print(f'Folder exists: {target_path}')
else:
    os.makedirs(target_path)
    print(f'Folder created: {target_path}')

hwnd_dlg = 1116276

# 다이얼로그 포커스
ctypes.windll.user32.SetForegroundWindow(hwnd_dlg)
time.sleep(0.5)

# 키보드 입력으로 트리뷰 탐색
# SendInput 사용
import ctypes.wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', ctypes.wintypes.WORD),
        ('wScan', ctypes.wintypes.WORD),
        ('dwFlags', ctypes.wintypes.DWORD),
        ('time', ctypes.wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT)]
    _anonymous_ = ('_input',)
    _fields_ = [
        ('type', ctypes.wintypes.DWORD),
        ('_input', _INPUT),
    ]


def send_key(vk, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.wVk = vk
    inp.dwFlags = KEYEVENTF_KEYUP if up else 0
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def press_key(vk):
    send_key(vk)
    time.sleep(0.05)
    send_key(vk, up=True)
    time.sleep(0.1)


def type_char(ch):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.wVk = 0
    inp.wScan = ord(ch)
    inp.dwFlags = KEYEVENTF_UNICODE
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    time.sleep(0.02)
    inp.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    time.sleep(0.05)


# Home 키로 트리뷰 맨 위로
print('Navigating tree...')
VK_HOME = 0x24
VK_END = 0x23
VK_DOWN = 0x28
VK_UP = 0x26
VK_RIGHT = 0x27
VK_LEFT = 0x25
VK_RETURN = 0x0D

press_key(VK_HOME)
time.sleep(0.3)

# 트리에서 "Desktop" 또는 "바탕 화면" 항목 찾기
# 방법: 키보드로 문자 입력하면 자동으로 해당 항목으로 이동
# "Des" 또는 "바탕" 입력
for ch in 'Desktop':
    type_char(ch)
    time.sleep(0.1)

time.sleep(0.5)

# Desktop을 찾았으면 오른쪽 화살표로 확장
press_key(VK_RIGHT)
time.sleep(0.5)

# 다시 "WEHAGO" 타이핑으로 폴더 찾기
for ch in 'WEHAGO':
    type_char(ch)
    time.sleep(0.1)

time.sleep(0.3)

# 선택 상태에서 확인 버튼 클릭
# Alt+O 또는 확인 버튼 핸들 직접 클릭
# 확인 버튼 핸들 = 1181866

# WM_COMMAND로 확인 클릭
WM_COMMAND = 0x0111
ctypes.windll.user32.SendMessageW(hwnd_dlg, WM_COMMAND, 1181866, 0)
time.sleep(3)

# 결과 확인
print(f'\nTarget path: {target_path}')
print(f'Exists: {os.path.exists(target_path)}')

items = os.listdir(target_path) if os.path.exists(target_path) else []
print(f'Files created: {len(items)}')
for item in items[:10]:
    full = os.path.join(target_path, item)
    size = os.path.getsize(full) if os.path.isfile(full) else 0
    print(f'  {item} ({size:,} bytes)')

print('\nDone!')

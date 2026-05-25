"""WehagoNTS (Windows Forms) 제어 — COM UIAutomation

전자신고 파일 제작 후 실행되는 WehagoNTS.exe 폴더 선택 다이얼로그를
COM UIAutomation으로 제어.

주의: 스레드 executor에서 실행 시 comtypes.CoInitialize() 필수 호출.
UIA 모듈 객체를 상위에서 로드 후 모든 하위 함수에 파라미터로 전달.
"""
import os
import subprocess
import time

import comtypes.client


def _get_desktop_path():
    """Windows KnownFolderPath API로 실제 바탕화면 경로 획득 (OneDrive 대응)"""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        # FOLDERID_Desktop = {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
        ctypes.windll.shell32.SHGetFolderPathW(0, 0, 0, 0, buf)
        return buf.value
    except Exception:
        return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")

DESKTOP_PATH = _get_desktop_path()


def select_nts_folder(folder_name):
    """WehagoNTS 폴더 선택 다이얼로그에서 바탕화면/지정폴더 선택 후 확인.

    처리 흐름:
    1. WehagoNTS 프로세스 대기 (최대 20초)
    2. "이미 기록된 파일" 질의 → 예(Y) 자동 클릭
    3. FormSelectFolder 창에서 바탕화면 확장 → 폴더 선택
    4. 확인 → 후속 모달(질의/안내) 자동 처리
    5. 바탕화면에 남은 파일 → 폴더로 이동
    """
    comtypes.CoInitialize()
    UIA = comtypes.client.GetModule("UIAutomationCore.dll")
    uia = comtypes.CoCreateInstance(
        UIA.CUIAutomation._reg_clsid_, interface=UIA.IUIAutomation
    )

    pid = _wait_for_nts(uia)
    if not pid:
        return False

    root = uia.GetRootElement()
    cond_pid = uia.CreatePropertyCondition(UIA.UIA_ProcessIdPropertyId, pid)
    # NTS 프로세스는 감지되었지만 윈도우 생성에 시간이 걸릴 수 있으므로 재시도
    nts_root = None
    for i in range(15):
        nts_root = root.FindFirst(UIA.TreeScope_Children, cond_pid)
        if nts_root:
            break
        if i % 3 == 2:
            print(f"  NTS 윈도우 대기 중... {(i+1)}초")
        time.sleep(1)
    if not nts_root:
        print("  NTS root not found (15초 타임아웃)")
        return False

    target_path = os.path.join(DESKTOP_PATH, folder_name)
    if not os.path.exists(target_path):
        os.makedirs(target_path)
        print(f"  폴더 생성: {target_path}")

    form = _wait_for_folder_dialog(UIA, uia, nts_root)
    if not form:
        return False
    print("  폴더 선택 창 감지")

    if not _select_tree_folder(UIA, uia, form, folder_name):
        return False

    # 경로 확인
    cond_lbl = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, "lblSelectNode"
    )
    lbl = form.FindFirst(UIA.TreeScope_Descendants, cond_lbl)
    if lbl:
        print(f"  경로: {lbl.CurrentName}")

    # 확인 버튼
    if not _invoke_btn(UIA, uia, nts_root, "btnOK"):
        print("  확인 클릭 실패")
        return False
    print("  확인 클릭")

    _handle_nts_modals(UIA, uia, nts_root)
    _move_desktop_files_to_folder(target_path, folder_name)

    if os.path.exists(target_path) and os.listdir(target_path):
        print(f"  완료: {folder_name}/ 에 {len(os.listdir(target_path))}개 파일")
        return True

    print("  파일 저장 확인 실패")
    return False


def _wait_for_nts(uia):
    """WehagoNTS.exe 프로세스 시작 대기 (최대 20초)"""
    for _ in range(20):
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WehagoNTS.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
        )
        try:
            pid = int(r.stdout.split(",")[1].strip('"'))
            print(f"  WehagoNTS PID: {pid}")
            return pid
        except (IndexError, ValueError):
            pass
        time.sleep(1)
    print("  WehagoNTS not running (timeout)")
    return None


def _wait_for_folder_dialog(UIA, uia, nts_root):
    """FormSelectFolder 대기. 중간에 '이미 기록된 파일' 질의 처리."""
    cond_form = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, "FormSelectFolder"
    )
    cond_win = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_WindowControlTypeId
    )

    for _ in range(15):
        try:
            windows = nts_root.FindAll(UIA.TreeScope_Children, cond_win)
            for j in range(windows.Length):
                w = windows.GetElement(j)
                if w.CurrentName == "질의" and _is_overwrite_query(UIA, uia, w):
                    _invoke_btn(UIA, uia, w, "6")
                    print("  '이미 기록된 파일' → 예(Y) 클릭")
                    time.sleep(2)
        except Exception:
            pass

        try:
            form = nts_root.FindFirst(UIA.TreeScope_Descendants, cond_form)
            if form and form.CurrentAutomationId == "FormSelectFolder":
                return form
        except Exception:
            pass
        time.sleep(1)

    print("  FormSelectFolder not found (timeout)")
    return None


def _is_overwrite_query(UIA, uia, window):
    """창이 '이미 기록된 파일' 질의인지 확인"""
    cond_text = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_TextControlTypeId
    )
    texts = window.FindAll(UIA.TreeScope_Descendants, cond_text)
    msg = "".join(texts.GetElement(i).CurrentName for i in range(texts.Length))
    return "이미 기록된 파일" in msg


def _select_tree_folder(UIA, uia, form, folder_name):
    """트리에서 바탕화면 확장 후 폴더 선택"""
    cond_tree = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, "treeDir"
    )
    tree = form.FindFirst(UIA.TreeScope_Descendants, cond_tree)
    if not tree:
        print("  treeDir not found")
        return False

    cond_item = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_TreeItemControlTypeId
    )

    items = tree.FindAll(UIA.TreeScope_Children, cond_item)
    desktop_item = None
    for i in range(items.Length):
        if items.GetElement(i).CurrentName == "바탕화면":
            desktop_item = items.GetElement(i)
            break

    if not desktop_item:
        print("  바탕화면 노드 not found")
        return False

    try:
        exp = desktop_item.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId)
        exp.QueryInterface(UIA.IUIAutomationExpandCollapsePattern).Expand()
        time.sleep(1.5)
    except Exception:
        pass

    sub_items = desktop_item.FindAll(UIA.TreeScope_Descendants, cond_item)
    for i in range(sub_items.Length):
        si = sub_items.GetElement(i)
        if si.CurrentName == folder_name:
            try:
                sel = si.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
                sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
                time.sleep(0.5)
            except Exception:
                pass
            print(f"  폴더 선택: {folder_name}")
            return True

    try:
        sel = desktop_item.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
        sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
        time.sleep(0.5)
    except Exception:
        pass
    print(f"  '{folder_name}' 트리에 없음 → 바탕화면 선택")
    return True


def _handle_nts_modals(UIA, uia, nts_root):
    """확인 후 후속 모달(질의/안내) 자동 처리"""
    cond_win = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_WindowControlTypeId
    )

    for _ in range(10):
        time.sleep(2)
        try:
            windows = nts_root.FindAll(UIA.TreeScope_Children, cond_win)
            if windows.Length == 0:
                break

            w = windows.GetElement(0)
            win_name = w.CurrentName

            if win_name == "질의":
                if _is_overwrite_query(UIA, uia, w):
                    _invoke_btn(UIA, uia, w, "6")
                    print("  '이미 기록된 파일' → 예(Y) 클릭")
                else:
                    _invoke_btn(UIA, uia, w, "6")
                    print("  질의 → 예(Y) 클릭")
                continue

            if win_name == "안내":
                _invoke_btn(UIA, uia, w, "2")
                print("  안내 모달 닫기")
                break
        except Exception:
            pass


def _invoke_btn(UIA, uia, parent, auto_id):
    """auto_id로 버튼 찾아서 Invoke 패턴 실행"""
    cond = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, auto_id
    )
    btn = parent.FindFirst(UIA.TreeScope_Descendants, cond)
    if not btn:
        return False
    try:
        inv = btn.GetCurrentPattern(UIA.UIA_InvokePatternId)
        inv.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        return True
    except Exception:
        return False


def _move_desktop_files_to_folder(target_path, folder_name):
    """바탕화면에 남은 .01 파일을 폴더로 이동"""
    for f in os.listdir(DESKTOP_PATH):
        if f.endswith(".01") and os.path.isfile(os.path.join(DESKTOP_PATH, f)):
            os.rename(os.path.join(DESKTOP_PATH, f), os.path.join(target_path, f))
            print(f"  파일 이동: {f} → {folder_name}/")

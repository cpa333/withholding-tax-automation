"""홈택스 세션 관리 모듈

세션 연장(자동/개발용) + 모달 자동 처리.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.automation.hometax._constants import SESSION_EXTEND_INTERVAL_S


async def auto_session_extend(page):
    """홈택스 세션을 주기적으로 연장

    홈택스는 24분 비활동 후 세션 연장 팝업(UTXPPABB27)을 표시하고,
    30분 후 강제 로그아웃 처리함.
    팝업이 뜨기 전 20분 주기로 sessionXtn() + sessionTimer()를 직접 호출하여
    세션을 미리 연장함.

    핵심 JS 함수:
      - $c.pp.sessionXtn($p): 다중 서버(TXPP, TECR 등) 세션 연장 JSONP 요청
      - sessionTimer("Y"): 24분 팝업 + 30분 로그아웃 타이머 재시작
    """
    while True:
        try:
            result = await page.evaluate("""() => {
                if (typeof $c === 'undefined' || typeof $p === 'undefined') return 'no_framework';
                try {
                    $c.pp.sessionXtn($p);
                    sessionTimer('Y');
                    return 'extended';
                } catch(e) { return 'error:' + e.message; }
            }""")
            if result == 'extended':
                log("  [세션 연장] sessionXtn + sessionTimer 호출 완료")
            else:
                log(f"  [세션 연장] 결과: {result}")
        except Exception:
            pass
        await asyncio.sleep(SESSION_EXTEND_INTERVAL_S)


async def trigger_session_popup_soon(page, seconds=10):
    """개발용: 세션 만료 팝업을 지정된 초 후에 강제 트리거

    홈택스(hometax.go.kr)의 세션 타이머를 단축하여 연장 팝업을 빠르게 유발.
    실제 발견된 글로벌 변수/함수:
      - sessiontimerDoServiceFnc: 24분 간격 팝업 타이머 ID
      - sessiontimerEndFnc: 30분 간격 로그아웃 타이머 ID
      - sessionTimer(popupOpenYn): 타이머 설정 함수
    테스트 시에만 사용. 프로덕션에서는 호출하지 않음.

    Usage:
        await trigger_session_popup_soon(page, seconds=5)  # 5초 후 팝업 등장
    """
    log(f"[DEV] {seconds}초 후 세션 연장 팝업 강제 트리거...")
    result = await page.evaluate("""(sec) => {
        clearInterval(window.sessiontimerDoServiceFnc);
        clearInterval(window.sessiontimerEndFnc);

        // sec초 후 UTXPPABB27 팝업 열기 (기존 24분 타이머를 단축)
        window.sessiontimerDoServiceFnc = setInterval(function() {
            var errLayer = document.createElement("div");
            errLayer.className = "w2modal";
            errLayer.id = "errLayer1";
            document.body.appendChild(errLayer);
            errLayer = document.createElement("div");
            errLayer.className = "w2modal";
            errLayer.id = "errLayer2";
            document.body.appendChild(errLayer);

            var sessionoptions = {
                id: 'UTXPPABB27',
                popupName: 'sessionOut',
                width: 610,
                height: 420,
                modal: false,
                scrollbars: false
            };
            $c.util.nts_openPopup($p, "/ui/pp/a/b/UTXPPABB27.xml", sessionoptions);
            $c.pp.sessionStop($p);
        }, sec * 1000);

        // sec*2초 후 로그아웃 타이머
        window.sessiontimerEndFnc = setInterval(function() {
            if ($c.com.nts_sendLogout != undefined) {
                $c.com.nts_sendLogout($p, null, null, $c.pp.sessionDdtTimerCallback);
                $p.$(".w2modal").remove();
            }
            $c.pp.endSessionStop($p);
        }, sec * 2000);

        return 'timers set: popup=' + sec + 's, logout=' + (sec*2) + 's';
    }""", seconds)
    log(f"[DEV] {result}")


async def dismiss_modals(ht):
    """홈택스 팝업 모달 자동 처리 (w2popup_window 내 btn_confirm 클릭)

    WebSquare w2popup_window 기반 알림/확인 모달을 모두 닫음.
    - 알림 모달 (페이지 진입 시)
    - 확인 모달 (파일검증 후 "이미 검증된 자료가 존재합니다" 등)
    """
    for _ in range(10):
        closed = await ht.evaluate("""() => {
            const modals = document.querySelectorAll('.w2popup_window');
            for (const modal of modals) {
                if (modal.style.display === 'none' || modal.offsetParent === null) continue;
                const btns = modal.querySelectorAll('input[type=button]');
                for (const b of btns) {
                    if (b.id && b.id.includes('btn_confirm')) {
                        b.click();
                        return b.id;
                    }
                }
            }
            return null;
        }""")
        if closed:
            log(f"  모달 닫음: {closed}")
            await asyncio.sleep(1)
        else:
            break

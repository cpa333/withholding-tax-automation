"""국민건강보험 EDI 자동화 — CDP 기반 메인 진입점

Usage:
    python -m src.automation.nhis.nhis_edi_auto_cdp
    python src/automation/nhis/nhis_edi_auto_cdp.py

사용법:
    1. Chrome이 CDP 모드(포트 9223)로 실행 중이어야 함
    2. 공동인증서 로그인은 사용자가 직접 수행 (Human-in-the-loop)
    3. 로그인 후 수임사업장 선택 → 자동화 진행
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    import io
    # GUI(LogCapture)에서는 stdout.detach()가 io.UnsupportedOperation을 내므로 가드.
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
    except (io.UnsupportedOperation, AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import launch_chrome, connect_page as cdp_connect
from src.automation.nhis._common_edi import (
    log, NHIS_EDI_URL, NHIS_EDI_MAIN,
    connect_page, wait_for_login, close_popups,
    open_firm_selector, wait_firm_selector_ready, list_all_firms, select_firm,
    select_firm_by_index, close_firm_popup,
    run_single_firm_workflow,
)
from src.utils.human import human_delay


def print_header():
    print("\n" + "=" * 55)
    print("  국민건강보험 EDI 자동화")
    print("=" * 55)


def print_menu():
    print("\n" + "-" * 55)
    print("  1. 수임사업장 선택 (목록에서 선택)")
    print("  2. 전체 수임사업장 목록 조회")
    print("  3. 수임처 PDF 다운로드 (받은문서 → 가입자고지내역서)")
    print("  4. 전체 자동 (수임처별 워크플로우 반복)")
    print("  0. 종료")
    print("-" * 55)


async def handle_select_workplace(page, context):
    """수임사업장 선택 대화형 처리"""
    popup = await open_firm_selector(page, context)
    if not popup:
        return

    await asyncio.sleep(2)
    result = await popup.evaluate("""() => {
        const rows = document.querySelectorAll('table.list tbody tr');
        const firms = [];
        rows.forEach(tr => {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 5 && /^\\d+$/.test(tds[1].textContent.trim())) {
                firms.push({
                    no: tds[1].textContent.trim(),
                    name: tds[2].textContent.trim(),
                    mgmtNo: tds[3].textContent.trim(),
                });
            }
        });
        return firms;
    }""")

    log(f"\n  현재 페이지 {len(result)}개:")
    for f in result[:10]:
        log(f"    {f['no']}. [{f['mgmtNo']}] {f['name']}")
    if len(result) > 10:
        log(f"    ... 외 {len(result) - 10}개")

    choice = input("\n  사업장명 또는 번호 입력 (0=취소): ").strip()
    if not choice or choice == "0":
        await close_firm_popup(context, popup)
        return

    # 번호로 선택 시도
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(result):
            ok = await select_firm_by_index(popup, idx)
            if ok:
                await asyncio.sleep(3)
                await close_firm_popup(context, popup)
                return
    except ValueError:
        pass

    # 이름으로 선택
    ok = await select_firm(popup, choice)
    if ok:
        await asyncio.sleep(3)
    await close_firm_popup(context, popup)


async def handle_list_all_workplaces(page, context):
    """전체 수임사업장 목록 조회"""
    popup = await open_firm_selector(page, context)
    if not popup:
        return

    firms = await list_all_firms(popup)
    log(f"\n  총 {len(firms)}개 수임사업장:")
    for f in firms:
        log(f"    {f['no']}. [{f['mgmtNo']}] {f['name']}")

    input("\n  Enter를 눌러 팝업을 닫습니다...")
    await close_firm_popup(context, popup)


async def handle_download_pdf(page, context):
    """현재 선택된 수임처의 PDF 다운로드"""
    # 현재 수임처명 확인
    firm_name = await page.evaluate("""() => {
        var text = document.body.innerText;
        var m = text.match(/수임 사업자명\\s*:\\s*(.+)/);
        return m ? m[1].trim() : null;
    }""")
    if not firm_name:
        log("  ERROR: 수임처가 선택되지 않았습니다. 먼저 메뉴 1로 선택하세요.")
        return

    log(f"  수임처: {firm_name}")
    await run_single_firm_workflow(page, context, firm_name)


async def run_full_auto(page, context):
    """전체 자동 모드: 수임처를 하나씩 선택하며 워크플로우 수행"""
    completed = 0

    while True:
        log(f"\n{'='*55}")
        log("  수임사업장선택 모달 열기...")
        popup = await open_firm_selector(page, context)
        if not popup:
            log("  ERROR: 사업장 선택 팝업을 열지 못했습니다.")
            return

        await asyncio.sleep(2)

        # 첫 페이지 목록 표시
        result = await popup.evaluate("""() => {
            const rows = document.querySelectorAll('table.list tbody tr');
            const firms = [];
            rows.forEach(tr => {
                const tds = tr.querySelectorAll('td');
                if (tds.length >= 5 && /^\\d+$/.test(tds[1].textContent.trim())) {
                    firms.push({
                        no: tds[1].textContent.trim(),
                        name: tds[2].textContent.trim(),
                        mgmtNo: tds[3].textContent.trim(),
                    });
                }
            });
            return firms;
        }""")

        log(f"\n  사업장 목록 ({len(result)}개):")
        for f in result[:10]:
            log(f"    {f['no']}. [{f['mgmtNo']}] {f['name']}")
        if len(result) > 10:
            log(f"    ... 외 {len(result) - 10}개")

        log(f"\n  완료: {completed}개 | 목록에 없으면 이름 직접 입력 가능")

        # 수임처 선택 루프
        firm_name = None
        while True:
            choice = input("\n  수임처 번호 또는 이름 (0=종료): ").strip()
            if not choice or choice == "0":
                await close_firm_popup(context, popup)
                log(f"\n  총 {completed}개 수임처 자동화 완료. 종료.")
                return

            # 번호로 선택 시도
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(result):
                    firm_name = result[idx]["name"]
                    break
            except ValueError:
                pass

            # 이름 일부 매칭
            matches = [f for f in result if choice in f["name"]]
            if len(matches) == 1:
                firm_name = matches[0]["name"]
                break
            elif len(matches) > 1:
                log(f"\n  '{choice}'와(과) 일치하는 사업장 {len(matches)}개:")
                for j, m in enumerate(matches):
                    log(f"    {j + 1}. [{m['mgmtNo']}] {m['name']}")
                sub = input("  선택 (0=취소): ").strip()
                try:
                    sub_idx = int(sub) - 1
                    if 0 <= sub_idx < len(matches):
                        firm_name = matches[sub_idx]["name"]
                        break
                except ValueError:
                    pass
                continue

            # 직접 이름으로 검색 시도
            firm_name = choice
            log(f"  '{choice}' — 표시 목록에 없음, 이름으로 검색합니다.")
            break

        # 사업장 선택
        ok = await select_firm(popup, firm_name)
        if not ok:
            log(f"  '{firm_name}' 사업장을 찾지 수 없습니다. 다시 입력해주세요.")
            await close_firm_popup(context, popup)
            continue

        await asyncio.sleep(3)
        await close_firm_popup(context, popup)

        log(f"\n{'='*55}")
        log(f"  [{completed + 1}] {firm_name}")
        log(f"{'='*55}")

        try:
            ok = await run_single_firm_workflow(page, context, firm_name)
            if ok:
                completed += 1
                log(f"\n  {firm_name} 처리 완료. ({completed}개 완료)")
            else:
                log(f"\n  {firm_name} 처리 실패.")
        except Exception as e:
            log(f"  ERROR: {firm_name} 처리 실패 - {e}")
            import traceback
            traceback.print_exc()


_TRACE_PATH = os.path.join("debug", "nhis_parallel_trace.log")


def _trace(msg: str):
    """병렬 NHIS 수임처 선택/전환 진단용 파일 로그 (debug/nhis_parallel_trace.log).

    select_firm 은 '어떤 행을 클릭했는지'만 알 뿐, 그 클릭이 실제로 사업장 전환을
    일으켰는지는 모른다. 9224 백그라운드 Chrome 에서 fn_firmChang click 가 no-op
    이면 페이지가 기본 사업장에 머물러(서율회계법인 반복) select_firm 은 '성공'으로
    돌아온다. 전환 검증 결과를 파일로 남겨 원인을 확정한다.
    """
    try:
        os.makedirs("debug", exist_ok=True)
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _name_match(a: str, b: str) -> bool:
    """수임처명 비교 — 괄호/공백/(주)/주식회사 표기 차이 흡수한 포함비교."""
    import re

    def norm(s):
        s = (s or "").replace("(주)", "").replace("주식회사", "")
        return re.sub(r"\s+", "", re.sub(r"[()\[\]]", "", s))

    na, nb = norm(a), norm(b)
    return na == nb or nb in na or na in nb


async def _current_firm_name(page):
    """메인 페이지에 현재 표시된 수임 사업자명 반환 (사업장 전환 검증용)."""
    try:
        return await page.evaluate(r"""() => {
            var t = document.body.innerText || "";
            var m = t.match(/수임\s*사업자명\s*:?\s*([^\n]+)/);
            return m ? m[1].trim() : null;
        }""")
    except Exception:
        return None


from src.automation._parallel_report import emit_summary as _emit_summary


async def run_auto_batch(page, context, *, firms, mgmts=None):
    """비대화형 일괄 실행 (--auto 모드). firms=None → 전체.

    run_full_auto 의 input 루프를 비대화형으로 재작성. 사업장 선택/실행은
    기존 함수(open_firm_selector/select_firm/close_firm_popup/run_single_firm_workflow) 재사용.

    매 수임처마다 phase 3 의 NhisEdiWorkflow.run_single 과 동일하게 close_popups 로
    메인(retrieveMain) 페이지를 재확보한다. 이전 수임처 워크플로우가 탭/네비게이션을
    바꿔 page 가 stale 되면 select_firm 의 사업장 전환이 메인에 반영되지 않아 기본
    로그인 사업장(서율회계법인 등) 자료만 반복해서 나오게 된다.

    mgmts: firms 와 같은 순서의 사업장관리번호. 제공되면 관리번호 검색으로 선택
    (원래 동작). 비었거나 없으면 이름 fallback.
    """
    if firms is None:
        popup = await open_firm_selector(page, context)
        if not popup:
            log("ERROR: 사업장 선택 팝업 오픈 실패")
            return
        await asyncio.sleep(2)
        result = await popup.evaluate(r"""() => {
            const rows = document.querySelectorAll('table.list tbody tr');
            const firms = [];
            rows.forEach(tr => {
                const tds = tr.querySelectorAll('td');
                if (tds.length >= 5 && /^\d+$/.test(tds[1].textContent.trim())) {
                    firms.push(tds[2].textContent.trim());
                }
            });
            return firms;
        }""")
        targets = list(result) if result else []
        await close_firm_popup(context, popup)
        if not targets:
            log("ERROR: 사업장 목록을 불러오지 못했습니다.")
            return
    else:
        targets = list(firms)

    log(f"비대화형 일괄 실행: {len(targets)}개 수임처")
    completed = 0
    skipped = []  # {"name","reason"[,"detail"]} — 종료 후 종합 리포트용
    for i, firm_name in enumerate(targets, 1):
        # 사업장관리번호(있으면 관리번호 검색, 없으면 이름 fallback)
        mgmt = mgmts[i - 1] if mgmts and (i - 1) < len(mgmts) else ""
        log(f"\n{'='*55}")
        log(f"  [{i}/{len(targets)}] {firm_name}" + (f" (관리번호 {mgmt})" if mgmt else ""))
        try:
            # 매 수임처마다 메인 페이지 재확보 (phase 3 run_single 과 동일) —
            # page 가 stale 되어 사업장 전환이 메인에 반영되지 않는 것을 방지.
            main_page = await close_popups(context)
            if not main_page:
                main_page = page
            await human_delay(3)

            popup = await open_firm_selector(main_page, context)
            if not popup:
                log(f"  ERROR: 팝업 오픈 실패 - {firm_name} 스킵")
                skipped.append({"name": firm_name, "reason": "오픈실패"})
                continue
            await asyncio.sleep(2)
            ok = await select_firm(popup, firm_name, management_number=mgmt)
            await close_firm_popup(context, popup)
            if not ok:
                log(f"  스킵: '{firm_name}' 사업장 미발견")
                skipped.append({"name": firm_name, "reason": "미발견"})
                continue

            # 사업장 전환 검증 — select_firm 이 클릭했더라도 9224 백그라운드 Chrome
            # 에서 click 이 실제 전환을 일으키지 않으면 페이지가 기본 사업장에 머문다.
            # 이 경우 run_single_firm_workflow 가 의도한 수임처가 아닌 자료를 가져온다.
            cur = await _current_firm_name(main_page)
            matched = bool(cur and _name_match(cur, firm_name))
            log(f"  전환 검증: 페이지='{cur}' / 기대='{firm_name}' "
                f"{'OK' if matched else 'MISMATCH'}")
            _trace(f"[{i}/{len(targets)}] target='{firm_name}' mgmt='{mgmt}' "
                   f"-> page='{cur}' {'OK' if matched else 'MISMATCH'}")
            if not matched:
                log(f"  WARN: '{firm_name}' 전환 미반영 — 페이지='{cur}'. "
                    f"워크플로우 진행하지만 자료가 다를 수 있음.")

            await human_delay(3)
            ok = await run_single_firm_workflow(main_page, context, firm_name)
            if ok:
                completed += 1
                log(f"  {firm_name} 처리 완료. ({completed}개 완료)")
            else:
                log(f"  {firm_name} 처리 실패.")
                skipped.append({"name": firm_name, "reason": "오류",
                                "detail": "워크플로우 실패"})
        except Exception as e:
            log(f"  ERROR: {firm_name} 처리 실패 - {e}")
            import traceback
            traceback.print_exc()
            skipped.append({"name": firm_name, "reason": "오류", "detail": str(e)})
            continue
    _emit_summary(len(targets), completed, skipped)


async def main(args=None):
    print_header()

    # Phase 1: Chrome 실행 + 연결
    log("\n[1/3] Chrome 실행...")
    result = launch_chrome(url=NHIS_EDI_URL)
    if not result["success"]:
        log(f"ERROR: {result['error']}")
        return
    if result.get("reused"):
        log("  기존 Chrome에 연결")

    async with async_playwright() as p:
        log("[2/3] Chrome 연결 + 로그인 대기...")
        try:
            browser, context, page = await connect_page(p)
        except Exception as e:
            log(f"ERROR: Chrome 연결 실패 - {e}")
            return

        # 이미 NHIS EDI 페이지면 재로딩하지 않음 (팝업 재생성 방지)
        # 빈 프로필(병렬) 첫 로딩이 느릴 수 있어 timeout 연장 + 재시도.
        if "edi.nhis.or.kr" not in page.url:
            for _attempt in range(3):
                try:
                    await page.goto(NHIS_EDI_URL, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    log(f"  NHIS 페이지 로딩 재시도... ({e})")
                    await asyncio.sleep(3)
            else:
                log("ERROR: NHIS 페이지 로딩 실패")
                return

        # 팝업 먼저 닫기 — popup 탭이 pages[0]일 수 있어 로그인 인식 방해
        page = await close_popups(context)
        await page.bring_to_front()

        if not await wait_for_login(page):
            log("로그인 실패")
            return

        # 로그인이 새 탭에서 완료됐을 수 있어 메인(retrieveMain) 탭으로 재해석
        # + 잔여 팝업/공지 정리. 이후 워크플로우가 올바른 페이지에서 동작.
        page = await close_popups(context)
        try:
            await page.bring_to_front()
        except Exception:
            pass

        # 로그인 직후 retrieveMain 리다이렉트/렌더가 끝나 수임사업장선택 버튼이
        # 뜰 때까지 한 번 안정화. (안 하면 첫 1~2 수임처가 'context destroyed'/
        # 버튼 미발견으로 실패하고 안정된 뒤 건만 성공.)
        log("  메인 페이지 준비 대기...")
        if await wait_firm_selector_ready(page, context):
            log("  메인 페이지 준비 완료")
        else:
            log("  WARN: 수임사업장선택 버튼 대기 시간 초과 — 계속 진행")

        log("로그인 확인됨. 자동화 시작.\n")

        # --auto 비대화형 모드: mode input 없이 run_auto_batch 로 일괄 실행.
        if args is not None and getattr(args, "auto", False):
            firms = ([s.strip() for s in args.firms.split(",") if s.strip()]
                     if args.firms else None)
            mgmts = ([s.strip() for s in args.mgmts.split(",")]
                     if getattr(args, "mgmts", None) else None)
            await run_auto_batch(page, context, firms=firms, mgmts=mgmts)
            return

        # Phase 2: 모드 선택
        log("실행 모드 선택:")
        log("  1. 전체 자동 (수임처별 전체 워크플로우)")
        log("  2. 대화형 메뉴")
        mode = input("\n선택 > ").strip()

        if mode == "1":
            await run_full_auto(page, context)
        else:
            await run_interactive(page, context)


async def run_interactive(page, context):
    """대화형 메뉴 모드"""
    while True:
        print_menu()
        choice = input("선택 > ").strip()

        if choice == "1":
            try:
                await handle_select_workplace(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "2":
            try:
                await handle_list_all_workplaces(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "3":
            try:
                await handle_download_pdf(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "4":
            try:
                await run_full_auto(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "0":
            log("종료합니다.")
            break

        else:
            log("잘못된 선택입니다. 0~4 중 하나를 입력하세요.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="국민건강보험 EDI 자동화")
    parser.add_argument("--auto", action="store_true",
                        help="비대화형 일괄 모드 (GUI 병렬 subprocess 용)")
    parser.add_argument("--firms", type=str, default=None,
                        help="콤마로 구분된 사업장명 (미지정 시 전체)")
    parser.add_argument("--mgmts", type=str, default=None,
                        help="콤마로 구분된 사업장관리번호 (--firms 와 같은 순서)")
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if not args.auto:
            print("\n프로그램을 종료하려면 Enter를 누르세요...")
            input()

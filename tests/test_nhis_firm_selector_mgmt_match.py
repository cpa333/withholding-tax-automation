"""NHIS select_firm 관리번호 매칭 회귀 테스트.

버그: 병렬 실행 시 관리번호 검색 후 표의 '첫 번째' 행을 무조건 클릭해
항상 같은 수임처(서율회계법인)가 잘못 선택되던 문제.
수정: 관리번호가 정확히 일치하는 행만 클릭.

_firm_selector.select_firm 의 관리번호 분기 evaluate 스크립트를 실제
Chromium 엔진에서 실행해, 가짜 NHIS 사업장 표에서 올바른 행을 고르는지 검증.
Playwright 가 설치되어 있지 않으면 자동 스킵.
"""
import asyncio
import pytest

playwright = pytest.importorskip("playwright")
from playwright.async_api import async_playwright

# select_firm 관리번호 분기의 매칭 스크립트(원본과 동일하게 유지).
MATCH_JS = r"""(mgmt) => {
    const want = (mgmt || '').replace(/\D/g, '');
    const rows = document.querySelectorAll('table.list tbody tr');
    const seen = [];
    for (const tr of rows) {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 5) continue;
        const rowMgmt = (tds[3].textContent || '').replace(/\D/g, '');
        const rowName = (tds[2].textContent || '').trim();
        seen.push(rowName + '(' + rowMgmt + ')');
        if (want && rowMgmt === want) {
            const link = Array.from(tr.querySelectorAll('a'))
                .find(a => (a.getAttribute('onclick') || '').includes('fn_firmChang'))
                || tds[2].querySelector('a');
            if (link) { link.click(); return { ok: true, name: rowName }; }
        }
    }
    return { ok: false, seen: seen };
}"""

# NHIS 사업장 선택 팝업 표 구조 흉내. tds: [_, no, name<a>, mgmtNo, unitCode]
HTML = """
<html><body>
<table class="list"><tbody>
  <tr><td>x</td><td>1</td>
      <td><a onclick="fn_firmChang('1111')">서율회계법인</a></td>
      <td>1111</td><td>U1</td></tr>
  <tr><td>x</td><td>2</td>
      <td><a onclick="fn_firmChang('2222')">두번째회계법인</a></td>
      <td>2222</td><td>U2</td></tr>
  <tr><td>x</td><td>3</td>
      <td><a onclick="fn_firmChang('3333')">세번째상회</a></td>
      <td>3333</td><td>U3</td></tr>
</tbody></table>
<div id="clicked">none</div>
<script>
  document.addEventListener('click', e => {
    if (e.target.tagName === 'A') document.getElementById('clicked').textContent = e.target.textContent.trim();
  }, true);
</script>
</body></html>
"""


async def _run(mgmt):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        pg = await b.new_page()
        await pg.set_content(HTML)
        result = await pg.evaluate(MATCH_JS, mgmt)
        clicked = await pg.evaluate("() => document.getElementById('clicked').textContent")
        await b.close()
        return result, clicked


def test_picks_non_first_row_by_mgmt():
    """관리번호 2222 → 첫 행(서율회계법인)이 아닌 두번째회계법인 클릭."""
    result, clicked = asyncio.run(_run("2222"))
    assert result["ok"] is True
    assert result["name"] == "두번째회계법인"
    assert clicked == "두번째회계법인"   # ★ 핵심: 서율회계법인이 아니어야 함
    assert clicked != "서율회계법인"


def test_first_row_when_mgmt_matches_first():
    """관리번호 1111 → 첫 행(서율회계법인) 정상 선택."""
    result, clicked = asyncio.run(_run("1111"))
    assert result["ok"] is True
    assert clicked == "서율회계법인"


def test_no_match_returns_seen_not_click():
    """존재하지 않는 관리번호 → 클릭하지 않고 seen 목록 반환(fallback 유도)."""
    result, clicked = asyncio.run(_run("9999"))
    assert result["ok"] is False
    assert clicked == "none"   # 아무것도 클릭하지 않음
    assert any("서율회계법인" in s for s in result["seen"])


def test_digit_normalization_ignores_hyphen():
    """'22-22' → 숫자만 비교해 2222(두번째회계법인)와 일치."""
    result, clicked = asyncio.run(_run("22-22"))
    assert result["ok"] is True
    assert clicked == "두번째회계법인"


if __name__ == "__main__":
    for fn in (test_picks_non_first_row_by_mgmt, test_first_row_when_mgmt_matches_first,
               test_no_match_returns_seen_not_click, test_digit_normalization_ignores_hyphen):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 select_firm 관리번호 매칭 테스트 통과")

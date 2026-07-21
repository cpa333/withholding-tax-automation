"""updater 정책 테스트 — 스로틀 간격·프롬프트 억제·버전 비교 (네트워크/Qt 불필요).

배경: v1.0.4 릴리스 실패 사후 보강. 자동 확인은 시작 1회 + 1시간 타이머로 호출되고
실제 네트워크 확인은 _CHECK_INTERVAL(4h) 스로틀이 게이트한다. '나중에'(세션 한정
deferred)와 '이 버전 건너뛰기'(영구 skip)는 should_prompt 순수 함수로 판정한다.
"""
import json
from datetime import datetime, timedelta

from src.utils import updater


# ── 스로틀 ──

def test_check_interval_is_4h():
    """당일 수렴 요구: 스로틀은 4시간 (기존 20h 회귀 방지)."""
    assert updater._CHECK_INTERVAL == timedelta(hours=4)


def _write_prefs(path, last_check: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_check": last_check}, f)


def test_should_check_today_boundary(monkeypatch, tmp_path):
    prefs = tmp_path / "update_prefs.json"
    monkeypatch.setattr(updater, "_PREFS_PATH", str(prefs))

    # 파일 없음 → 확인해야 함
    assert updater.should_check_today() is True

    # 3시간 50분 전 → 스로틀에 걸림
    _write_prefs(prefs, (datetime.now() - timedelta(hours=3, minutes=50))
                 .isoformat(timespec="seconds"))
    assert updater.should_check_today() is False

    # 4시간 10분 전 → 확인해야 함
    _write_prefs(prefs, (datetime.now() - timedelta(hours=4, minutes=10))
                 .isoformat(timespec="seconds"))
    assert updater.should_check_today() is True

    # 파싱 불가 쓰레기 → fail-open (확인)
    _write_prefs(prefs, "not-a-date")
    assert updater.should_check_today() is True

    # 빈 값 → 확인
    _write_prefs(prefs, "")
    assert updater.should_check_today() is True


# ── 프롬프트 억제 판정 (순수 함수) ──

def test_should_prompt_matrix():
    v = "1.1.0"
    # 수동 확인은 항상 표시 (skip/deferred 무시)
    assert updater.should_prompt(False, False, v, skip_version=v) is True
    assert updater.should_prompt(False, False, v, deferred={v}) is True
    # 필수 업데이트는 항상 표시
    assert updater.should_prompt(True, True, v, skip_version=v, deferred={v}) is True
    # 무음 + 영구 스킵 → 억제
    assert updater.should_prompt(True, False, v, skip_version=v) is False
    # 무음 + 세션 '나중에' → 억제
    assert updater.should_prompt(True, False, v, deferred={v}) is False
    # 무음 + 다른 버전 스킵/보류 이력 → 표시 (버전별 독립)
    assert updater.should_prompt(True, False, v, skip_version="1.0.5",
                                 deferred={"1.0.9"}) is True
    # 무음 + 이력 없음 → 표시
    assert updater.should_prompt(True, False, v) is True


# ── 버전 비교/판정 (기존 동작 고정) ──

def test_parse_is_newer_basic():
    assert updater.is_newer("1.1.0", "1.0.5") is True
    assert updater.is_newer("v1.1.0", "1.1.0") is False      # 동일 → 다운그레이드 방지
    assert updater.is_newer("1.0.4", "1.0.5") is False       # 낮음
    assert updater.is_newer("1.1.0-beta", "1.1.0") is False  # pre-release 는 정식보다 낮음
    assert updater.is_newer("", "1.0.5") is False            # 빈 원격 → 무시


def test_decide_min_supported_forces_mandatory():
    info = {"version": "1.1.0", "mandatory": False, "min_supported": "1.1.0",
            "url": "u", "size": 1, "sha256": "a", "notes": ""}
    res = updater.decide(info, local="1.0.5")
    assert res["action"] == "mandatory"
    # min_supported 이상이면 선택 업데이트 유지
    res2 = updater.decide({**info, "min_supported": "1.0.0"}, local="1.0.5")
    assert res2["action"] == "optional"
    # 빈 min_supported 는 미적용
    res3 = updater.decide({**info, "min_supported": ""}, local="1.0.5")
    assert res3["action"] == "optional"

"""Đội hình + sao ước lượng từ lịch sử mua."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import composition  # noqa: E402


def _r(rnd, t0, bought):
    return {"round": rnd, "start": t0, "end": t0 + 30, "bought": bought}


def test_stars_from_copies():
    assert [composition.stars_of(c) for c in (1, 2, 3, 5, 8, 9, 12)] == [1, 1, 2, 2, 2, 3, 3]


def test_cumulative_estimate_and_flags():
    rounds = [_r("2-1", 0, ["Varus", "Teemo"]),
              _r("2-2", 30, ["Varus", "Wisp Vàng", "varus"]),          # tên viết thường vẫn gộp; Wisp bị bỏ
              _r("2-3", 60, ["Teemo (không thấy vàng giảm)"])]
    events = [{"round": "2-3", "t": 65, "type": "gain", "detail": "+3 vàng"}]
    composition.estimate(rounds, events)
    assert rounds[0]["board_est_str"] == "Teemo ★ (1), Varus ★ (1)"
    est = {u["name"].lower(): (u["stars"], u["copies"]) for u in rounds[1]["board_est"]}
    assert est == {"varus": (2, 3), "teemo": (1, 1)}
    assert rounds[1]["sold_maybe"] is False and rounds[2]["sold_maybe"] is True
    assert {u["name"].lower(): u["copies"] for u in rounds[2]["board_est"]}["teemo"] == 2
    fin = composition.final(rounds)
    assert fin["round"] == "2-3" and fin["units"][0]["stars"] == 2


def test_empty():
    rounds = [_r("1-1", 0, [])]
    composition.estimate(rounds, [])
    assert rounds[0]["board_est"] == [] and composition.final(rounds) is None

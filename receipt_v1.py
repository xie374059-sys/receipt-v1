#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交接收据判定器 —— receipt-v1 参考实现(单文件,零依赖)。

    python3 receipt_v1.py            # 跑规范 §7 的三条一致性测试
    python3 receipt_v1.py receipt.json
    echo '{"status":"completed"}' | python3 receipt_v1.py -

本文件是 receipt-spec.md 的**参考实现**,不是权威实现。
任何语言、任何项目按规范自行实现,通过 §7 的三条测试即合规。
不联网、不调用模型、无第三方依赖。
"""

from __future__ import annotations

import json
import sys

STATUSES = ("not_started", "in_progress", "pending_acceptance",
            "completed", "failed", "cancelled")
EVIDENCE_LEVELS = ("unverified", "local_observed", "third_party_verified")
REQUIRED = ("op_id", "status", "evidence_level", "capability_gap",
            "raw_carry", "formal_ack")

#: raw_carry 里这些词表示"没做到"(规范 §5 规则 4;实现方可扩充,不得删减)
FALSY_ASCII = ("false", "no", "none", "null", "0", "")
FALSY_CN = ("未签字", "无记录", "未完成", "未执行", "未开始", "尚未",
            "没做到", "不可用", "不具备")


def _falsy(v: str) -> bool:
    s = str(v).strip().lower()
    return s in FALSY_ASCII or any(w in s for w in FALSY_CN)


def judge(r: dict | None, *, side_effects: int | None = None,
          expected_raw_carry: dict | None = None) -> dict:
    """按 receipt-spec.md §5 判定。返回 {verdict, reasons, missing_fields}。"""
    r = r or {}
    missing = [f for f in REQUIRED if f not in r]

    # 1 自证
    if r.get("formal_ack") is True:
        return _out("REJECT", ["formal_ack_true"])

    # 2 幂等
    if isinstance(side_effects, int) and side_effects > 1:
        return _out("REJECT", ["duplicate_side_effects"])

    # 3 原值逐字核对
    if isinstance(expected_raw_carry, dict):
        got = r.get("raw_carry")
        if not isinstance(got, dict):
            return _out("REJECT", ["raw_carry_missing"])
        bad = [k for k, v in expected_raw_carry.items()
               if str(got.get(k, "")) != str(v)]
        if bad:
            return _out("REJECT", ["raw_carry_mismatch:" + ",".join(bad)])

    status = r.get("status")
    rc = r.get("raw_carry") if isinstance(r.get("raw_carry"), dict) else {}

    # 4 凭据里写着没做到,却标完成
    if status == "completed" and rc:
        bad = [k for k, v in rc.items() if _falsy(v)]
        if bad:
            return _out("REJECT", ["raw_says_not_done_but_completed:" + ",".join(bad)])

    # 5 换号重派
    attempts = r.get("attempts")
    if isinstance(attempts, list) and len(attempts) >= 2:
        first = (attempts[0] or {}).get("op_id")
        renum = [(a or {}).get("op_id") for a in attempts[1:]
                 if (a or {}).get("op_id") and (a or {}).get("op_id") != first]
        if renum:
            return _out("REJECT", ["op_id_renumbered"])

    # 6 有缺口却标完成
    gap = r.get("capability_gap") or ""
    if gap and status == "completed":
        return _out("REJECT", ["gap_but_completed"])

    # 7 未验证却完成
    if status == "completed" and r.get("evidence_level") == "unverified":
        return _out("NEEDS_HUMAN", ["completed_but_unverified"])

    # 状态枚举
    if status is not None and status not in STATUSES:
        return _out("REJECT", [f"unknown_status:{status}"])
    if r.get("evidence_level") is not None and r["evidence_level"] not in EVIDENCE_LEVELS:
        return _out("REJECT", [f"unknown_evidence_level:{r['evidence_level']}"])

    # 缺字段
    if missing:
        return _out("NEEDS_HUMAN", ["missing_fields:" + ",".join(missing)])

    # 8 完成
    if status == "completed":
        return _out("ACCEPT", ["completed_with_evidence_and_no_gap"])
    # 8b 诚实的未完成 —— 它也是好收据(v1 判"可不可信",不判"做完没")
    if status == "pending_acceptance" and gap:
        return _out("ACCEPT", ["honest_partial"])
    # 9 其他
    return _out("NEEDS_HUMAN", [f"not_completed:{status}"])


def _out(v: str, reasons: list[str]) -> dict:
    return {"verdict": v, "reasons": reasons, "formal_ack": False}


# ---------------------------------------------------------------- 规范 §7 三条测试

T1_GOOD = {
    "op_id": "op-1", "status": "pending_acceptance", "evidence_level": "local_observed",
    "capability_gap": "验收单未签字", "raw_carry": {"tubes": "216"},
    "formal_ack": False, "attempts": [{"attempt": 1, "op_id": "op-1", "status": "in_progress"}],
}
T2_CONTRADICTION = {
    "op_id": "op-2", "status": "completed", "evidence_level": "local_observed",
    "capability_gap": "", "raw_carry": {"验收单": "未签字"}, "formal_ack": False,
}
T3_MISSING = {"status": "completed"}

CONFORMANCE = [("T1 诚实的未完成(缺口已申报)", T1_GOOD, "ACCEPT"),
               ("T2 说完成但凭据写着未签字", T2_CONTRADICTION, "REJECT"),
               ("T3 只有 status", T3_MISSING, "NEEDS_HUMAN")]


def _selftest() -> int:
    print("=" * 68)
    print("receipt-v1 参考实现 · 一致性测试(规范 §7)")
    print("=" * 68)
    ok = 0
    for label, r, expect in CONFORMANCE:
        got = judge(r)
        hit = got["verdict"] == expect
        ok += hit
        print(f"{'PASS' if hit else 'FAIL'}  {label:<26} 期望={expect:<12} "
              f"实际={got['verdict']:<12} {got['reasons']}")
    print(f"== {ok}/{len(CONFORMANCE)} ==")
    return 0 if ok == len(CONFORMANCE) else 1


def main() -> int:
    args = sys.argv[1:]
    if not args:
        return _selftest()
    if args[0] == "-":
        raw = sys.stdin.read()
    else:
        with open(args[0], encoding="utf-8") as f:
            raw = f.read()
    got = judge(json.loads(raw))
    print(json.dumps(got, ensure_ascii=False, indent=2))
    return 0 if got["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

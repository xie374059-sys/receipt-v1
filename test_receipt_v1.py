#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""receipt-v1 一致性测试:规范 §7 三条必须通过。

    python3 test_receipt_v1.py

任何实现,能过这三条,就符合 receipt-v1。
"""
import importlib.util, sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("rv1", Path(__file__).parent / "receipt_v1.py")
rv1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(rv1)

# 规范 §7 的三条(独立于参考实现内部的 CONFORMANCE,这里是外部判据)
CASES = [
    ("T1 诚实的未完成", rv1.T1_GOOD, "ACCEPT"),
    ("T2 说完成但凭据写着未签字", rv1.T2_CONTRADICTION, "REJECT"),
    ("T3 只有 status", rv1.T3_MISSING, "NEEDS_HUMAN"),
    # 额外:自证一律拒
    ("T4 formal_ack=true", {**rv1.T1_GOOD, "formal_ack": True}, "REJECT"),
    # 额外:换号重派一律拒
    ("T5 换号重派", {**rv1.T1_GOOD, "attempts": [
        {"attempt": 1, "op_id": "op-1", "status": "failed"},
        {"attempt": 2, "op_id": "op-2", "status": "in_progress"}]}, "REJECT"),
]


def main() -> int:
    ok = 0
    print("=" * 66)
    print("receipt-v1 一致性测试")
    print("=" * 66)
    for label, r, expect in CASES:
        got = rv1.judge(r)["verdict"]
        hit = got == expect
        ok += hit
        print(f"{'PASS' if hit else 'FAIL'}  {label:<26} 期望={expect:<12} 实际={got}")
    print(f"== {ok}/{len(CASES)} ==")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())

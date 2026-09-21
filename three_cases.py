#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三个具体例子:同一个签名收据,你认为没问题,XAIP 也认为没问题,但里面是假的。

    python3 three_cases.py

每个例子都是:**收据内容 + 两份判定器的结论**。
这是 IETF XAIP Receipts 和本仓库 receipt-v1 的对照实验(手写本地实现,
不是真的调它们的代码 —— 因为 A 的字段就是它规范里写的)。

A 判定器 = 按 draft-xkumakichi-xaip-receipts-00 的规则(只看 success bool + 验签)
B 判定器 = 按本仓库 receipt-spec.md 的规则(看字段一致性 + 不许自证 + 缺口申报)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from receipt_v1 import judge as judge_b  # 本仓库的判定器


def judge_a_xaip(receipt: dict, signature_valid: bool = True) -> dict:
    """按 XAIP 的规则判:验签通过 + success==True 就算过。

    XAIP 原文:
      success: "true if the tool call satisfied the agent's success criterion"
      (由执行方自己判定成功)
      Verification: 只要求验签通过。
    """
    if not signature_valid:
        return {"verdict": "REJECT", "reason": "signature_invalid"}
    if receipt.get("success") is True and receipt.get("failureType", "") == "":
        return {"verdict": "ACCEPT", "reason": "signature_ok + success_true"}
    return {"verdict": "REJECT", "reason": f"failureType={receipt.get('failureType')}"}


# ================================================================ 三个例子

CASES = [
    {
        "name": "例子 1:中文业务单据 —— 单据没签字,但收据说成功",
        "story": "财务 agent 出了季度结算单,说'完成全部核算、可直接打款'。"
                 "而原始材料里写着'验收单尚未签字'。",
        "xaip_receipt": {
            "agentDid": "did:web:finance.example",
            "callerDid": "did:key:z6MkBoss",
            "toolName": "make_settlement_report",
            "taskHash": "9b74c9897bac770ffc029102a200c5de",
            "resultHash": "f0e1d2c3b4a5987612345678abcdef00",
            "success": True,
            "latencyMs": 1840,
            "failureType": "",
            "timestamp": "2026-09-21T10:30:00.000Z",
            "signature": "(有效签名)",
            "callerSignature": "(有效签名)",
        },
        "v1_receipt": {
            "op_id": "FIN-Q3-01", "status": "completed", "evidence_level": "local_observed",
            "capability_gap": "",
            "raw_carry": {"验收单状态": "未签字", "合计数": "43000"},
            "formal_ack": False,
        },
    },
    {
        "name": "例子 2:跨机交付 —— 任务根本没送出去,但回执说成功",
        "story": "2026-06-28 那次真实事故:status=completed,"
                 "而同一份记录里 task_sent_to_codex=false。",
        "xaip_receipt": {
            "agentDid": "did:web:node-b.example",
            "callerDid": "did:key:z6MkCloud",
            "toolName": "deliver_task",
            "taskHash": "aaaa1111bbbb2222cccc3333dddd4444",
            "resultHash": "eeee5555ffff6666aaaa7777bbbb8888",
            "success": True,
            "latencyMs": 420,
            "failureType": "",
            "timestamp": "2026-06-28T08:42:00.000Z",
            "signature": "(有效签名)",
        },
        "v1_receipt": {
            "op_id": "op-nodeb-011", "status": "completed", "evidence_level": "local_observed",
            "capability_gap": "",
            "raw_carry": {"task_sent_to_codex": "false", "completion_observed": "false"},
            "formal_ack": False,
        },
    },
    {
        "expected_raw_carry": {"抄表日": "2026-03-14"},   # 期望值:中国侧发的原样
        "name": "例子 3:跨国交接 —— 原值被本地化改写,对不上账",
        "story": "中国侧发的日期是 2026-03-14,英文侧写成 14 March 2026。"
                 "两边都觉得没问题。",
        "xaip_receipt": {
            "agentDid": "did:web:cn.example",
            "callerDid": "did:key:z6MkUs",
            "toolName": "handover_note",
            "taskHash": "11112222333344445555666677778888",
            "resultHash": "9999aaaabbbbccccddddeeeeffff0000",
            "success": True,
            "latencyMs": 260,
            "failureType": "",
            "timestamp": "2026-09-21T11:00:00.000Z",
            "signature": "(有效签名)",
        },
        "v1_receipt": {
            "op_id": "op-cn-us-1", "status": "completed", "evidence_level": "local_observed",
            "capability_gap": "",
            "raw_carry": {"抄表日": "14 March 2026"},   # 实际带过去的(已被本地化改写)
            "formal_ack": False,
        },
    },
]


def main() -> int:
    print("=" * 78)
    print("同一个签名收据:两份判定器的结论")
    print("=" * 78)
    print("A = IETF XAIP 的规则(验签 + 看 success)")
    print("B = 本仓库 receipt-v1 的规则(字段一致性 + 不许自证 + 缺口申报)")
    print()

    for i, c in enumerate(CASES, 1):
        a = judge_a_xaip(c["xaip_receipt"])
        b = judge_b(c["v1_receipt"], expected_raw_carry=c.get("expected_raw_carry"))
        print("─" * 78)
        print(c["name"])
        print(f"  情况:{c['story']}")
        print()
        print(f"  A(XAIP)判定:{a['verdict']:<13} 理由:{a['reason']}")
        print(f"  B(receipt-v1)判定:{b['verdict']:<13} 理由:{b['reasons']}")
        verdict = "❌ A 放过了, B 抓到了" if a["verdict"] == "ACCEPT" and b["verdict"] != "ACCEPT" \
            else "两边一致"
        print(f"  -> {verdict}")
        print()

    print("=" * 78)
    print("这三个例子里,A 全部放过 —— 因为签名是真的、success 也是真的。")
    print("B 三个全部抓到。区别只在一处:")
    print("  · 前两个:B 看【声明和它自己的凭据矛不矛盾】,不需要外部信息")
    print("  · 第三个:B 需要调用方给出【期望原值】(expected_raw_carry)才能判改写")
    print()
    print("所以 B 的能力边界很清楚:给它期望值,它能查改写;不给,它只查自相矛盾。")
    print()
    print("诚实边界:")
    print("  · B 不防伪造。签名能防的,B 防不了。")
    print("  · B 是筛子,不是保险箱。")
    print("  · 但上面这三种情况,签名本来也没打算管。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

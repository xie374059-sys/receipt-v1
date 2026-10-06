#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交接收据判定器 (Handover Receipt Judge) v0.1 —— 纯确定,零模型。

    # 判一份收据
    python3 runner.py receipt.json

    # 判一批,出一张成绩单
    python3 runner.py --suite cases/suite.json

    # 用真实事故现场跑第一张成绩单
    python3 runner.py --suite cases/incident-011.json

    # 机器可读输出
    python3 runner.py receipt.json --json

判定三选一:ACCEPT / REJECT / NEEDS_HUMAN
判据见 spec.md;本文件不调用任何模型、不发任何网络请求。
"""

from __future__ import annotations

import argparse
import glob          # ★ 2026-10-06 加：不带参数时扫 cases/*.json 用它。
                     #   ★ 实测抓到的：我写"不需要新依赖（glob 在标准库里）"——
                     #     **而"标准库里有" ≠ "这个文件里能用"**：忘了 import ⇒ NameError。
import json
import os            # ★ 同上（拼路径用）
import sys
from pathlib import Path
from typing import Any

STATUSES = ("not_started", "queued", "in_progress", "completed", "failed", "cancelled")
EVIDENCE = ("unverified", "local_observed", "third_party_verified")
# ★★★★ 为什么是六个而不是七个 —— 而这一条是 P0 测试逼出来的：
#   交接收据一共【七个字段】，而这一张表是【"缺了就没法机械判定"】那张表。
#   ★ `attempts` 不在里面：**缺 attempts 本身不算假**（★ 一件没重派过的活
#     本来就只有一次尝试），而【重派时报了号却对不上】才算 ——
#     那一条由规则 3c 和规则 7 管，不靠"缺字段"管。
#   ⇒ 所以：**七个字段 · 六个硬要** —— 而"七个缺一不可"那句话是错的，已改。
REQUIRED = ("op_id", "status", "evidence_level", "capability_gap", "raw_carry", "formal_ack")


def status_of(r: dict[str, Any]) -> Any:
    return (r or {}).get("status")


#: ★★★★★ 2026-10-06：**英文规则名 → 人话。**
#:
#:   ★ 用途：**页面上给人看**。（命令行那边照旧用英文名 —— 那是能查的精确判据。）
#:   ★★ 而它的形状是"匹配前缀 + 补上括号里那几个值"，因为有些理由带着变量。
#:   ★★★ 而【改这张表【改的是说法，不是判据】—— 判据在 judge() 里，一个字不碰。
#: ★★★★★ 2026-10-06：**凭据里那些字段名 → 人话。**
#:
#:   ★ 起因：键哥截图说「我看不懂代码」—— 而理由是
#:     「…（task_sent_to_codex、completion_observed、lease_status）」。
#:   ★★ 那三个是【凭据里的格子名】。人会想知道"哪一格对不上"，而【不想看英文】。
#:   ★★★ 而【翻不出来【的【不显示】—— 只说"有几格对不上"，**绝不原样漏出去**。
字段话: dict[str, str] = {
    "task_sent_to_codex": "任务交给下游了吗",
    "completion_observed": "看到完成了吗",
    "lease_status": "租约状态",
    "delivered": "东西送到了吗",
    "signed": "签收了吗",
    "verified": "核过了吗",
    "deployed": "上线了吗",
    "tested": "测过了吗",
    "raw_carry": "凭据那一格",
    "evidence_level": "凭据等级",
    "capability_gap": "自己报的缺口",
    "formal_ack": "自己盖的章",
    "status": "状态",
    "attempts": "试了几次",
    "op_id": "单号",
}


def 翻字段(名单: str) -> str:
    """★ 把 `a,b,c` 那样的字段名翻成中文。**翻不出来的【不出现在结果里】。**"""
    出 = []
    没翻 = 0
    for x in str(名单 or "").replace("，", ",").split(","):
        x = x.strip()
        if not x:
            continue
        话 = 字段话.get(x)
        if 话:
            出.append(话)
        else:
            没翻 += 1
    if 没翻 and not 出:
        # ★ 一个都翻不出来 ⇒ 只报个数，不报名字
        return "有 %d 格对不上" % 没翻
    if 没翻:
        出.append("另有 %d 格" % 没翻)
    return "、".join(出)


人话表: dict[str, str] = {
    "completed_with_evidence_and_no_gap": "证据齐了，没毛病",
    "raw_says_not_done_but_completed": "嘴上说「干完了」，而凭据里写着没送出去",
    "raw_carry_mismatch": "原值和它自己说的对不上",
    "formal_ack_true": "自己证明自己，没用",
    "formal_ack": "自己证明自己，没用",
    "gap_but_completed": "自己承认有缺口，而状态写着完成",
    "gap_underreported": "实际有缺口，而申报得比实际小",
    "missing_fields": "有几格没填",
    "not_completed": "状态不是「完成」",
    "completed_but_unverified": "说完成了，而凭据等级不够",
    "completed_after_failed_attempt_no_retry_record": "前面失败过，而没写重试记录",
    "op_id_renumbered": "同一件事换了单号",
    "evidence_level_overstated": "凭据等级报高了",
}


def 说人话(reasons) -> list[str]:
    """★ 把英文规则名翻成人话。**翻不出来的原样留着**（★ 不许编）。"""
    出 = []
    for x in (reasons or []):
        x = str(x)
        头 = x.split(":", 1)[0].strip()
        话 = 人话表.get(头)
        if not 话:
            # ★ 前缀匹配（有些理由是 `xxx:值` 那种）
            for k, v in 人话表.items():
                if 头.startswith(k):
                    话 = v
                    break
        if not 话:
            出.append("（这条还没翻译）" + x)
            continue
        # ★ 而【冒号后面那几个值【也带上】—— 那是"哪一格对不上"，人想知道。
        #   ★★ 而它【也要翻】：可能是英文的字段名（键哥截图说"我看不懂代码"就是这里）。
        #   ★★★ 而【中文那些值【原样用】（比如 formal_ack_true:自证完成,无效）。
        值 = x.split(":", 1)[1].strip() if ":" in x else ""
        if 值:
            if any("\u4e00" <= _c <= "\u9fff" for _c in 值):
                话 = 话 + "（" + 值.replace(",", "、") + "）"
            else:
                _翻 = 翻字段(值)
                if _翻:
                    话 = 话 + "（" + _翻 + "）"
        出.append(话)
    return 出


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    """返回 {verdict, reasons[], missing_fields[], checked}。规则顺序见 spec.md §2。"""
    r = receipt or {}
    reasons: list[str] = []

    # ---- 字段缺失:缺哪些要如实报(缺 = 无法机械判定)
    missing = [f for f in REQUIRED if f not in r]

    # R-op-03 op_id 的格式。判在最前:格式不对,后面每一条都无从谈起。
    #   依据:设计 v0.1 的 R-op-03,加上元界核出来的硬伤 ——
    #   seq 是每间房各从 1 开始的(实测 785 个 seq 被 32 间房共用),
    #   所以 YJ-<数字> 不唯一,得带房间:YJ-<房间短名>-<数字>。
    #
    #   ★★★ 而格式【由收据喂进来】(r["op_id格式"] 一个正则),不写死在这儿。
    #     为什么:那份 README 写着"不绑定任何行业" ——
    #     而把元界的 YJ- 格式写进通用 runner,会把别的项目的收据全拒掉。
    #     实测:generic-suite 的 op-generic-N 和 incident-011 的 op-20260628-011
    #     全被拒 => 那两套从 8/8 掉到 5/8 / 7/8。
    #   => 所以:格式的定义在【房间】,判的能力在【runner】。没有格式就不判。
    _op = r.get("op_id")
    _格式 = r.get("op_id格式")
    if isinstance(_op, str) and _op and isinstance(_格式, str) and _格式:
        import re as _re
        if not _re.fullmatch(_格式, _op):
            return _out("REJECT", ["op_id_format:期望 " + _格式 + ",给的是 " + _op], missing)

    # 1 自证
    if r.get("formal_ack") is True:
        return _out("REJECT", ["formal_ack_true:自证完成,无效"], missing)

    # 2 幂等:同一 op_id 副作用发生多次
    applied = r.get("side_effects")
    if isinstance(applied, int) and applied > 1:
        return _out("REJECT", [f"duplicate_side_effects:op_id={r.get('op_id')} 副作用 {applied} 次"], missing)

    # 3 原值逐字核对
    expected = r.get("expected_raw_carry")
    if isinstance(expected, dict):
        got = r.get("raw_carry")
        if not isinstance(got, dict):
            return _out("REJECT", ["raw_carry_missing"], missing)
        bad = [k for k, v in expected.items() if str(got.get(k, "")) != str(v)]
        if bad:
            return _out("REJECT", [f"raw_carry_mismatch:{','.join(bad)}"], missing)

    # 3b 原值里明确写着"没送到",却标 completed -> 自相矛盾,直接拒
    if status_of(r) == "completed":
        rc = r.get("raw_carry")
        if isinstance(rc, dict):
            # 凭据里写着"没做"却标完成 -> 自相矛盾。
            # 注意:过去只认英文 false/none,中文的「未签字 / 无记录」会漏 —— 已补。
            FALSY_ASCII = ("false", "0", "none", "null", "no", "")
            FALSY_CN = ("未签字", "无记录", "未完成", "未执行", "未开始", "尚未", "没做到",
                        "不可用", "不具备")
            falsy = []
            for k, v in rc.items():
                sv = str(v).strip().lower()
                if sv in FALSY_ASCII or any(w in sv for w in FALSY_CN):
                    falsy.append(k)
            if falsy:
                return _out("REJECT", [f"raw_says_not_done_but_completed:{','.join(falsy)}"], missing)

    # 3c 换号重派:attempts 里出现与首个 op_id 不同的号 -> 这不是同一件事
    attempts_now = r.get("attempts") or []
    if isinstance(attempts_now, list) and len(attempts_now) >= 2:
        first_op = (attempts_now[0] or {}).get("op_id")
        renumbered = [(a or {}).get("op_id") for a in attempts_now[1:]
                      if (a or {}).get("op_id") and (a or {}).get("op_id") != first_op]
        if renumbered:
            return _out("REJECT", [f"op_id_renumbered:{first_op}->{','.join(renumbered)}"], missing)

    # 4 有缺口却标完成
    gap = r.get("capability_gap") or ""
    status = r.get("status")
    if gap and status == "completed":
        return _out("REJECT", [f"gap_but_completed:{gap}"], missing)

    # 5 实际有缺口却报空 -> 转人工
    if r.get("actual_gap") is True and not gap:
        return _out("NEEDS_HUMAN", ["gap_underreported:实际有缺口但未申报"], missing)

    # 6 未验证却完成 -> 转人工
    if status == "completed" and r.get("evidence_level") == "unverified":
        return _out("NEEDS_HUMAN", ["completed_but_unverified"], missing)

    # 7 有失败尝试却标完成、且没有重派记录
    attempts = r.get("attempts") or []
    if status == "completed" and isinstance(attempts, list):
        failed = [a for a in attempts if isinstance(a, dict) and a.get("status") == "failed"]
        retried = any(isinstance(a, dict) and a.get("status") in ("completed", "in_progress")
                      for a in attempts[1:])
        if failed and not retried and len(attempts) > 1:
            return _out("NEEDS_HUMAN", ["completed_after_failed_attempt_no_retry_record"], missing)

    # 8 状态不合法
    if status is not None and status not in STATUSES:
        return _out("REJECT", [f"unknown_status:{status}"], missing)

    # R-op-01 收据的 op_id 得有一条真开单。
    #   依据:设计 v0.1 的 R-op-01。而 runner 读不到账 => 账的信息由调用方喂进来:
    #   收据.开单表 = {"t_cut": <墙钟>, "有开单的": [op_id ...]}
    #   开单表没有时 => NEEDS_HUMAN(判不了就说判不了,不许硬判)。
    _表 = r.get("开单表")
    if isinstance(_表, dict):
        _有 = _表.get("有开单的")
        _cut = _表.get("t_cut")
        if isinstance(_有, list) and _op not in _有:
            # 老数据(t_cut 之前)转人工;新数据(t_cut 之后)直接拒
            if isinstance(_cut, str) and isinstance(r.get("t_wall"), str) \
                    and str(r.get("t_wall")) < _cut:
                return _out("NEEDS_HUMAN", ["no_open_order_before_t_cut:" + str(_op)], missing)
            return _out("REJECT", ["no_open_order:" + str(_op)], missing)

    # R-op-02 撤回的 op_id 得有一条真开单。转人工,不直接拒。
    #   依据:设计 v0.1 的 R-op-02 —— "撤回经常是事后补记的,先转人工"。
    #   而元界那边那个真件(元界本事.撤回)就是"追加一条撤销,不改写原来那条"。
    #   收据.撤回 = {"op_id": <被撤的号>, "谁撤的": ..., "为什么撤": ...}
    _撤 = r.get("撤回")
    if isinstance(_撤, dict):
        _撤号 = _撤.get("op_id")
        if _撤号 and isinstance(_表, dict):
            _有2 = _表.get("有开单的")
            if isinstance(_有2, list) and _撤号 not in _有2:
                return _out("NEEDS_HUMAN",
                            ["retract_without_open_order:" + str(_撤号)], missing)
    # ★★★ 而【没喂"开单表"的时候 [不判]】—— 和上面格式那条同一个道理：
    #   通用 runner 不该假设"每个项目都有开单表"。
    #   ★ 实测：加上"没表就转人工"那个分支之后，generic-suite 从 8/8 掉到 5/8 ——
    #     因为它的用例本来就没有开单表。
    #   => 开单表【喂了才判】；而"这个房间必须有开单"是【房间的规矩】（小M 那份 §3）。

    # R-lv-01 证据等级【不许虚报】—— 填得比转述距离允许的高 ⇒ REJECT。
    #
    #   依据:小M 那句「自称就拒：evidence_level 填得比转述距离允许的高 ⇒ REJECT。
    #   这是"别把前者当后者卖"的代码版」。而它是【纵深】那一道 ——
    #   防的是【绕过写入口】的（写入口 记一笔() 那条已经让人填不了,而这条防硬塞）。
    #
    #   ★★ 而这一条【只对带 relay_chain 的收据生效】——
    #     因为那份 README 写着"不绑定任何行业",所以 runner【不知道哪个项目该有链】。
    #     没带链 ⇒ 【不判】(不是 NEEDS_HUMAN —— "没有链"对一份通用收据是正常的)。
    #   ★ "老账不可考 ⇒ 按 unverified 算"那件事【不在这儿做】——那是元界账那边的规矩。
    _链 = r.get("relay_chain")
    _等 = r.get("evidence_level")
    if isinstance(_链, list) and _等 in ("unverified", "local_observed",
                                         "third_party_verified"):
        # ★ 距离 = 链长;而 f(距离):0 ⇒ local_observed,≥1 ⇒ unverified。
        #   ★ 而 third_party_verified 【永远不许由距离推出来】—— 它要第三方真核过。
        _最高 = "local_observed" if len(_链) == 0 else "unverified"
        _档 = ("unverified", "local_observed", "third_party_verified")
        if _档.index(_等) > _档.index(_最高):
            return _out("REJECT",
                        ["evidence_level_overstated:%s > %s（链长 %d 允许的最高档）"
                         % (_等, _最高, len(_链))], missing)

    # R-evid-01 「有证据」那句话要有东西撑着。
    #
    #   ★★★ 2026-10-06 加 · 依据是一个外来 agent（小M）跑完包交的第⑤条:
    #     「`raw_carry` 整个空着 + 自称 third_party_verified ⇒ **ACCEPT**,
    #       理由 completed_with_evidence_and_no_gap —— **那个 with_evidence 是空的**。」
    #     而它说:「它不是 bug,是语义问题 —— 「不判」被判成了 ACCEPT,
    #       而不是 NEEDS_HUMAN。**按你们自己的规矩,判不了就该转人工。**」
    #   ★★ 而我核过那个例子(★ 不凭它说):确实 ACCEPT。
    #
    #   ★ 判据:`status=completed` 而 `raw_carry` 是【空的】⇒ **NEEDS_HUMAN**。
    #     · 为什么是转人工而不是拒:**可能真做完了,只是没记原值** ——
    #       而那正是"判不了就转人工",不是"判不了就当过"。
    #     · 为什么它比"没闸"更坏:**它给了个像样的理由**
    #       ("completed_with_evidence_and_no_gap"),而【证据那一格是空的】。
    if status_of(r) == "completed":
        _rc = r.get("raw_carry")
        if _rc is not None and isinstance(_rc, dict) and not _rc:
            return _out("NEEDS_HUMAN",
                        ["completed_but_no_raw_carry:标了完成,而 raw_carry 是空的 —— "
                         "「有证据」那句话要有东西撑着"], missing)

    # 9 缺字段:无法机械判定
    if missing:
        return _out("NEEDS_HUMAN", [f"missing_fields:{','.join(missing)}"], missing)

    # 10 完成
    if status == "completed":
        return _out("ACCEPT", ["completed_with_evidence_and_no_gap"], missing)

    return _out("NEEDS_HUMAN", [f"not_completed:{status}"], missing)


def _out(verdict: str, reasons: list[str], missing: list[str]) -> dict[str, Any]:
    # ★ 2026-10-06：**多一格 `人话`** —— 给页面用。（英文那串一个字不动。）
    return {"verdict": verdict, "reasons": reasons, "missing_fields": missing,
            "人话": 说人话(reasons),
            "formal_ack": False}


def run_suite(suite: dict[str, Any]) -> dict[str, Any]:
    cases = suite.get("cases") or []
    rows, hits = [], 0
    for c in cases:
        got = judge(c.get("receipt") or {})
        want = c.get("expected")
        # ★★★★★ 2026-10-06 改 · 依据是一个【没有先验知识】的执行者跑通之后挖出的第一个雷：
        #   「原来 `ok = (want is None) or (got["verdict"] == want)` ⇒
        #     **期望值只要漏填，它一定绿** —— 而它长得跟"过了"一模一样。」
        #   ★ 而那就是元界第一条那个病:不许让"看起来完成"冒名顶替"真的完成"。
        #   ★★ 所以现在把两种"没有期望值"【分开】:
        #     · **显式写了 `"expected": null`** ⇒ 那才是"故意不设"（要配 `"不设期望": "为什么"`）
        #     · **压根没有 `expected` 这个键** ⇒ **漏填 ⇒ 那条用例报错,不算过**
        _有键 = "expected" in c
        if not _有键:
            ok = False
            got = dict(got)
            got["reasons"] = list(got.get("reasons") or []) + [
                "★ 漏填 expected —— 这条用例【没有期望值】,所以它【不算过】"
                "（★ 要故意不设,就显式写 expected: null 并说明为什么）"]
        elif want is None:
            # ★ 显式 null：故意不设 —— 而那要【说出为什么】（★ 说不出来就不算）
            ok = bool(c.get("不设期望"))
            if not ok:
                got = dict(got)
                got["reasons"] = list(got.get("reasons") or []) + [
                    "★ expected 是 null 而没写「不设期望」的理由 —— 那和漏填分不开"]
        else:
            ok = (got["verdict"] == want)
        hits += bool(ok)
        rows.append({
            "id": c.get("id", "?"), "desc": c.get("desc", ""),
            "expected": want, "got": got["verdict"], "ok": ok,
            "reasons": got["reasons"],
            # ★★ 而这一格是给【成绩单】用的：显式的"故意不设"和"漏填"要分得开。
            "不设期望": bool(c.get("不设期望")),
            "有没有那个键": _有键,
        })
    return {"total": len(cases), "passed": hits, "rows": rows,
            "accuracy": round(hits / len(cases), 4) if cases else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description="交接收据判定器(纯确定,零模型)")
    ap.add_argument("path", nargs="?", help="一份收据 JSON,或配合 --suite 的套件 JSON")
    ap.add_argument("--suite", action="store_true", help="把输入当套件跑成绩单")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    # ★★★★ 2026-10-06 加：**不带参数 ⇒ 跑 cases/ 下所有套件。**
    #   ★ 起因（小M 定的打包第一样）：「**一条命令：朋友复制粘贴就能跑。**」
    #     原来不带参数是 `print_help()` + 返回 2 —— 那对第一次拿到的人来说【是撞墙】。
    #   ★★ 而现在：`python3 runner.py` 一条命令 ⇒ 三个套件全跑，成绩单一起出。
    #   ★ 零新依赖：只用标准库的 glob（★ 而它本来就在标准库里）。
    if not args.path:
        _们 = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "cases", "*.json")))
        if not _们:
            print("找不到 cases/*.json —— 这个包里该有套件。", file=sys.stderr)
            return 2
        print("=" * 78)
        print("交接收据判定器 —— 把 cases/ 下的套件全跑一遍")
        print("★ 纯确定 · 零模型 · 零网络 —— 同一份收据，谁跑都是同一个结果。")
        print("=" * 78)
        _总过 = _总条 = 0
        for _路 in _们:
            _d = json.loads(Path(_路).read_text(encoding="utf-8"))
            _r = run_suite(_d)
            _总过 += _r["passed"]
            _总条 += _r["total"]
            print("  %-34s %d/%d = %.0f%%"
                  % (os.path.basename(_路), _r["passed"], _r["total"],
                     _r["accuracy"] * 100))
            for _行 in _r["rows"]:
                if not _行["ok"]:
                    print("      ✗ %s %s（期望 %s）" % (_行["id"], _行["got"], _行["expected"]))
        print("-" * 78)
        print("  合计 %d/%d = %.0f%%" % (_总过, _总条, (_总过 / _总条 * 100) if _总条 else 0))
        print()
        print("★ 看到 REJECT 别慌 —— 那是它在工作。")
        print("  判定器的价值是【能判假】：一个永远判真的闸，比没有闸更坏。")
        return 0 if _总过 == _总条 else 1
    p = Path(args.path).expanduser()
    if not p.exists():
        print(f"找不到文件: {p}", file=sys.stderr)
        return 2
    data = json.loads(p.read_text(encoding="utf-8"))

    if args.suite:
        res = run_suite(data)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        print("=" * 78)
        print(f"成绩单:{data.get('name', p.name)}")
        if data.get("note"):
            print(f"说明:{data['note']}")
        print("=" * 78)
        print(f"{'用例':<8} {'期望':<13} {'判定':<13} 结果  说明")
        for row in res["rows"]:
            mark = "✓" if row["ok"] else "✗"
            # ★★★★ 2026-10-06 改 · 一个【没先验知识】的执行者指出的一处易误读：
            #   「总表里漏填印成 `期望 None`」——
            #   ★ 而 `None` 在成绩单里【看不出】是"故意不设"还是"漏填了"。
            #   ★★ 所以现在分开印：显式的故意不设 ⇒ `(不设)`；压根没填 ⇒ `(漏填!)`。
            _显 = ("(不设)" if (row.get("expected") is None and row.get("不设期望"))
                   else ("(漏填!)" if row.get("expected") is None else str(row["expected"])))
            print(f"{row['id']:<8} {_显:<13} {row['got']:<13} {mark}    "
                  f"{row['desc'][:38]}")
            if not row["ok"]:
                print(f"{'':<8} 理由: {'; '.join(row['reasons'])}")
        print("-" * 78)
        print(f"准确率 {res['passed']}/{res['total']} = {res['accuracy']:.0%}")
        return 0 if res["passed"] == res["total"] else 1

    got = judge(data.get("receipt") or data)
    if args.json:
        print(json.dumps(got, ensure_ascii=False, indent=2))
        return 0
    print(f"判定:{got['verdict']}")
    for x in got["reasons"]:
        print(f"  理由: {x}")
    if got["missing_fields"]:
        print(f"  缺字段: {', '.join(got['missing_fields'])}")
    return 0 if got["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

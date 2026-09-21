# receipt-v1

**一份收据说"我干完了"。这个判定器回答:这份收据可不可信。**

零依赖、纯规则、不调模型、不发网络请求。一个文件,几十行。

```bash
python3 receipt_v1.py examples/1-false-completion.json
```

```
{
  "verdict": "REJECT",
  "reasons": ["raw_says_not_done_but_completed:task_sent_to_codex,completion_observed"],
  "formal_ack": false
}
```

---

## 它解决什么

一个 agent 回话说"完成了"。收据上写着 `status: completed`。

**但同一份收据里,原始字段写着 `task_sent_to_codex: false`。**

它没送出去,却报了完成。**这不是假设,是 2026-06-28 一次真实事故的原始记录。**
当时 `status=completed`,4 份修理指令、4 小时 retry、`codex=false` 出现 11 次。

**签名、身份、审计日志,一个都不缺 —— 但没人检查声明和凭据是否自相矛盾。**

这个判定器只做那一件事。

## 三分钟看懂

| 例子 | 判定 | 为什么 |
|---|---|---|
| [`1-false-completion.json`](examples/1-false-completion.json) | **REJECT** | 标了完成,凭据里写着没送出去 |
| [`2-honest-partial.json`](examples/2-honest-partial.json) | **ACCEPT** | 如实申报"3 号库区未改造" —— **诚实是可信的** |
| [`3-self-ack.json`](examples/3-self-ack.json) | **REJECT** | `formal_ack: true`,自己给自己盖章 |
| [`4-not-verified.json`](examples/4-not-verified.json) | **NEEDS_HUMAN** | 标完成但证据等级是 `unverified` |

## ⚠️ 先读这一条,否则会误用它

**这个判定器判的是"收据可不可信",不是"活干完了没有"。**

这两个不是一回事。所以:

- **如实报告没干完 → ACCEPT。** 那是一份好收据。
- **声称干完了但凭据对不上 → REJECT。**
- **字段缺失、判不了 → NEEDS_HUMAN。**

如果你要的是"活到底干完没",这个工具**不回答那个问题**。它回答的是"我能不能信这份报告"。

## 它不做什么

明确划清,避免误用:

- **不防伪造。** 能签名的东西本来就该签名。它不管密码学。
- **不判内容对不对。** 它不判断结果好不好、对不对、该不该。
- **不联网、不调模型。** 纯规则,输入输出都是 JSON。
- **不是保险箱,是筛子。** 它拦的是"自己和自己的凭据打架"这一类。

## 七个字段

| 字段 | 说明 |
|---|---|
| `op_id` | 这次操作的全网唯一号 |
| `status` | `completed` / `pending_acceptance` / 其他 |
| `attempts` | 可选。重试列表;同一 `op_id` 复用是合法的,换号重派不是 |
| `evidence_level` | `unverified` / `self_reported` / `local_observed` / … |
| `capability_gap` | 有缺口就写在这里。**写在缺口里是诚实的,藏在 completed 里不是** |
| `raw_carry` | 原样携带的原始字段 —— **判定器主要靠它发现矛盾** |
| `formal_ack` | **恒为 false。** 谁能自己给自己发确认,那确认就不值钱 |

规范细节见 [`spec/receipt-spec.md`](spec/receipt-spec.md)。

## 判定规则(9 条)

按顺序,先命中先返回:

```
1  formal_ack is true                     → REJECT   自己给自己盖章
2  副作用发生 > 1 次                      → REJECT   重传做重
3  原值逐字对不上(需调用方给期望值)      → REJECT   被本地化改写
4  completed 但 raw_carry 里有假值        → REJECT   ★ 011 那种
5  attempts 里出现新的 op_id              → REJECT   换号重派
6  capability_gap 非空 但 status=completed→ REJECT   有缺口却标完成
7  completed 但 evidence_level=unverified → NEEDS_HUMAN
8  缺字段                                 → NEEDS_HUMAN
9  completed 且证据齐全且无缺口            → ACCEPT
   9b pending_acceptance + 有缺口          → ACCEPT   诚实的部分交付
```

## 自己跑

```bash
# 单份
python3 receipt_v1.py examples/1-false-completion.json

# 自测(5 个用例)
python3 test_receipt_v1.py

# 行为边界:哪些它抓得到,哪些抓不到
python3 three_cases.py
```

`three_cases.py` 是三种**签名完好**的收据 —— 签名能验的都验过了 ——
但里面有一份声明和凭据自相矛盾。它演示了本判定器和"只验签名"那一层的分工在哪。

---

## 和其他东西的关系

这个概念不新,外面有至少 7 份 IETF 草案在做相关的事
(execution outcome attestation、signed action receipts、SCITT profile 等)。

**它们的路线是:签名 + 透明度日志 + TEE 硬件,让"结果声明"不可篡改。**

**本判定器的路线不一样:不签名,只检查一份报告和它自己携带的凭据是否自洽。**

两条路不冲突,管的是不同的事:

| | 签名那一层 | 本判定器 |
|---|---|---|
| 保证 | 这话**确实是**他说的,没被改 | 他说的这话**自己站不住** |
| 前提 | 公钥基础设施、日志服务、硬件 | **一份 JSON,什么都不用装** |
| 适合 | 跨组织、要不可否认 | 本地、当场、要先有个筛子 |

**签名完好的报告,照样可能自相矛盾。** 011 那次就是。

---

## 状态

`receipt-v1`,实验性质。判定规则是确定的、可复跑的;它**没有被任何机构采纳,也没有生产验证**。

欢迎挑刺 —— 尤其是:**你能构造出一份收据,让这个判定器给出错误判定吗?**
那是最有价值的反馈。

## 许可

MIT

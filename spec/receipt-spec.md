# 交接收据规范 v1 (Handover Receipt Schema v1)

```
spec:    receipt-v1
status:  draft
license: 可自由实现,无需授权
```

> **一句话:** 一次「一方为另一方干了活」的交接,只要带上这六个字段,
> 接收方就能**机械地**判断:可以收 / 退回 / 需要人看。
>
> **它不判断你说的对不对,只判断你的声明和你自己的凭据一不一致。**

---

## 0. 适用范围

**适用:** 有交付物,且下游要依据它行动的一次交接。
例:agent 交活给 agent、供应商交货、工程师交付部署、财务出报表。

**不适用:** 没有后果的交互(答一句话、翻译一段文字)。
**在这种地方用它,只会增加成本。**

---

## 1. 字段定义(六个)

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `op_id` | string | ✅ | 这次**业务操作**的唯一号。**重派必须复用同一个号**;换号 = 新操作 |
| `status` | enum | ✅ | 见 §2 |
| `evidence_level` | enum | ✅ | 见 §3 |
| `capability_gap` | string | ✅ | **哪儿没做到**。没做到就写;**为空表示"确实没有未完成项"** |
| `raw_carry` | object (string→string) | ✅ | **原样携带**:键值对,值必须是**未经本地化改写**的原始值 |
| `formal_ack` | bool | ✅ | **恒为 false**。收到 `true` 视为无效收据 |
| `attempts` | array | ⬜ | 历史尝试。重派必须在这里留痕(见 §4) |

### 关于 `raw_carry`(最容易做错的一个)

**值必须逐字保留原样。禁止翻译、禁止改单位、禁止换日期格式。**

```
✅ 正确:  "reading_at": "2026-03-14"
❌ 错误:  "reading_at": "14 March 2026"      ← 本地化改写
✅ 正确:  "amount": "10 万元"
❌ 错误:  "amount": "100,000"                ← 改写
```

理由:v1 的核对是**逐字比较**。一个字符不同就判不一致。
如果实现方自行做了本地化,核查必然失败 —— 而这不是收据的错。

---

## 2. `status` 取值

```
not_started | in_progress | pending_acceptance | completed | failed | cancelled
```

**判据只关心一个区分:`completed` vs 其他。**

---

## 3. `evidence_level` 取值

```
unverified           只有一段自然语言,没有任何可复查痕迹
local_observed       本机确实观察到(有日志、有产物、有回执)
third_party_verified 有本层之外的第三方证据
```

**本层能自证的最高等级是 `local_observed`。**(理由见 §6)

---

## 4. `attempts` 结构

```jsonc
"attempts": [
  {"attempt": 1, "op_id": "op-123", "status": "failed",  "reason": "lease_not_active"},
  {"attempt": 2, "op_id": "op-123", "status": "completed", "reason": ""}
]
```

**硬规则:所有 attempt 的 `op_id` 必须与首个相同。**
出现不同的号 = 换号重派 = 直接判 REJECT。

---

## 5. 判定规则(三条输出)

判定器**必须**按以下顺序执行,**先否定后肯定**:

```
输入:收据 R;可选 side_effects(同一 op_id 的副作用次数)

1  R.formal_ack == true                                  -> REJECT  formal_ack_true
2  side_effects > 1                                      -> REJECT  duplicate_side_effects
3  expected_raw_carry 存在 且 与 R.raw_carry 不逐字相等   -> REJECT  raw_carry_mismatch
4  R.status == completed 且 raw_carry 中有值表示"未完成"  -> REJECT  raw_says_not_done_but_completed
5  attempts 中存在与首个不同的 op_id                      -> REJECT  op_id_renumbered
6  R.capability_gap 非空 且 R.status == completed         -> REJECT  gap_but_completed
7  R.status == completed 且 evidence_level == unverified  -> NEEDS_HUMAN completed_but_unverified
8  R.status == completed                                  -> ACCEPT  completed
8b R.status == pending_acceptance 且 capability_gap 非空   -> ACCEPT  honest_partial
9  其他                                                   -> NEEDS_HUMAN not_completed

外加:任一必填字段缺失                                     -> NEEDS_HUMAN missing_fields:<列表>
```

**输出三态,只此三种:**

| 判定 | 含义 | 接收方该做什么 |
|---|---|---|
| **ACCEPT** | 这份收据**自己站得住**(内部不矛盾、缺口已申报、凭据齐) | **可以据此做决定** |
| **REJECT** | 收据**自相矛盾**、或自证、或换号 | 退回,不推进 |
| **NEEDS_HUMAN** | 缺字段、或证据不足、或无法机械判定 | **转人**,不许自动放行 |

### ⚠️ 关键:v1 判的是"收据可不可信",不是"活做完没"

**这两件事必须分开**,否则会出现最糟的结果:**惩罚诚实、鼓励瞒报。**

```
收据可信 + 活做完了   ->  ACCEPT   completed
收据可信 + 活没做完   ->  ACCEPT   honest_partial   ← 诚实的未完成,也是好收据
收据可疑              ->  REJECT / NEEDS_HUMAN
```

**"活做完没"由 `status` 和 `capability_gap` 承载,不由判定结果承载。**
接收方拿到 `ACCEPT` 后,自己看 `status` 决定能不能签字。

> **安全阀:判不准的一律走 NEEDS_HUMAN,绝不放行。**

**规则 4 的"表示未完成"包括:**
英文 `false / no / none / null / 0 / 空串`,
中文 `未签字 / 无记录 / 未完成 / 未执行 / 未开始 / 尚未 / 没做到 / 不可用 / 不具备`。

实现方可扩充词表,但**不得删减以上任一条**。

---

## 6. 明确不判的事(边界,写死)

**收据判定器不判断:**

- ❌ **凭据是不是真的** —— 它只审"声明与凭据一不一致"
- ❌ 数字算得对不对
- ❌ 业务上是否合理
- ❌ 是否合规
- ❌ 谁对谁错

**它只回答一个问题:这份收据自己站不站得住。**

**以及一条纪律:`formal_ack` 恒为 false。**
本层**永不产生正式确认** —— 确认只能由接收方给出。

---

## 7. 最小一致性测试(实现方必须通过)

任一实现,必须对以下三份收据给出对应结论:

| # | 收据 | 必须输出 | 触发理由 |
|---|---|---|---|
| **T1** | 六字段齐全、`status=pending_acceptance`、缺口已申报、有凭据 | **ACCEPT** | `honest_partial` |
| **T2** | `status=completed`,而 `raw_carry` 中含 `"验收单":"未签字"` | **REJECT** | `raw_says_not_done_but_completed` |
| **T3** | 只有 `{"status":"completed"}` | **NEEDS_HUMAN** | `missing_fields` |

**通过这三条,即视为符合 `receipt-v1`。**

**注意 T1 的意义:** 它代表**最常见的真实情况 —— 活没干完,但报告得很诚实**。
实现方必须让 T1 通过,否则这个格式在实际业务里没人敢用。

---

## 8. 一个真实反例(为什么需要它)

2026-06-28,一次跨机交付:

- 收据写着 `status: completed`
- 而同一份收据的 `raw_carry` 里写着 `task_sent_to_codex: "false"`
- **那条交付根本没送到。四小时后才被发现。**

按本规范,第 4 条规则会在**第一秒**判出:

```
REJECT  raw_says_not_done_but_completed:task_sent_to_codex
```

**这就是这六个字段的全部价值:让"做完了没"不再靠人吵。**

---

## 附:版本与演进

- **v1 只做"声明与凭据一致性"的机械判定。**
- 未来版本可能加入:签名、时间戳、来源环境标签。
- **但只要 v1 的三条测试通过,就永远合规 —— 后续版本必须向后兼容。**

# Token Passthrough Audit Reading Guide

這份 guide 搭配 `make lab-02-passthrough` 產生的 `events.jsonl` 使用。它不是另一份 policy spec，目的只是讓讀者快速找出「同一枚 credential 被送了幾跳」以及「ALLOW 後到底歸因給誰」。

## 先看五個欄位

| 欄位 | 回答的問題 | 判讀陷阱 |
| --- | --- | --- |
| `credential_fingerprint` | 是否為同一枚 presented credential | 只能用來關聯，不能當 principal，也不要保存 raw token；production 優先考慮 keyed HMAC 與短 retention |
| `resource` | 這一跳真正接收 Token 的 resource | 不能從 hostname 猜 audience 已驗過 |
| `decision`／`code` | 這一跳是否通過、在哪個條件失敗 | `ALLOW` 不代表 attribution 完整 |
| `token_subject` | 這個 resource 已驗證的 Token subject | 被拒絕時應是 `UNVERIFIED`，不要先 decode 再當成身分 |
| `attribution` | Human、Agent、Workload 是否仍可區分 | `COLLAPSED_TO_TOKEN_SUBJECT` 是治理缺口，不是成功狀態 |

## 找出同一枚 Token 被送到哪些 resource

從 repo root 執行：

```bash
jq -s '
  group_by(.credential_fingerprint)
  | map({
      fingerprint: .[0].credential_fingerprint,
      hops: map({case_id, resource, decision, code, attribution})
    })
' labs/02-identity-boundary/artifacts/day10-*/events.jsonl
```

同一個 `sha256:` fingerprint 出現在入口、嚴格下游與放寬下游，表示 Lab 確實重用了同一枚值班工程師的 Token。JSONL 沒有 compact JWT。

## 比較「硬讓它通」與 resource-bound 路徑

```bash
jq -s '
  map(select(
    .case_id == "passthrough_shared_audience"
    or .case_id == "audience_bound_downstream"
  ))
  | map({
      case_id,
      decision,
      attribution,
      human_principal,
      token_subject,
      executing_agent,
      workload_principal
    })
' labs/02-identity-boundary/artifacts/day10-*/events.jsonl
```

預期差異：

| Case | Human | Token subject | Executing Agent | Workload |
| --- | --- | --- | --- | --- |
| `passthrough_shared_audience` | `user/sre-oncaller` | `user/sre-oncaller` | `UNKNOWN` | `UNKNOWN` |
| `audience_bound_downstream` | `user/sre-oncaller` | `client/sre-investigator-runtime` | `agent/sre-investigator@v1` | `k8s://lab/identity-boundary/sa/sre-agent` |

## `UNVERIFIED` 與 `UNKNOWN` 不一樣

- `UNVERIFIED`：Token 在 signature／issuer／audience 等驗證完成前就被拒絕，Audit 不能把 untrusted claims 當成 authenticated principal。
- `UNKNOWN`：Request 已經通過該弱化 policy，但該觀測點沒有 Agent 或 Workload evidence。它是 attribution 缺口。

## 上線前至少問清楚

```text
1. 每個 protected resource 的 canonical resource ID 是什麼？
2. 下游看到的 Token subject 是 Human，還是實際呼叫它的 Workload？
3. Human delegation 如何與下游 credential 綁定，能否被任意重放或拼接？
4. Token 被記錄時，是 raw value、可關聯 fingerprint，還是完全不落盤？
```

只要第二題的答案是「整條鏈永遠都是值班工程師」，就還不能靠現有 Audit 回答哪個 runtime 真正送出了下游請求。

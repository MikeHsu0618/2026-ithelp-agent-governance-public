# Incident Replay 欄位指南

這份表用來檢查一筆 Agent action 能否被事後重建。先填 evidence source，再決定狀態；不要看到空值就直接寫成 `DENY`、`NONE` 或 `NOT_APPLICABLE`。

## 證據狀態

| 狀態 | 使用條件 | 常見誤用 |
|---|---|---|
| `VERIFIED` | Replay 當下能以獨立機制重新驗證 | 把 Runtime 自己寫下的 claim 當成已驗證事實 |
| `OBSERVED` | 原始 Artifact 明確記錄該值 | 因為 JSON 有欄位就宣稱來源可信或不可竄改 |
| `UNKNOWN` | 資料不足，無法判定值或流程是否發生 | 把空白解讀成不存在、未授權或安全 |
| `NOT_APPLICABLE` | 依流程與 policy，該欄位本來就不應產生 | Tool 執行過卻找不到 receipt 時用它掩蓋缺口 |

## Action replay checklist

| 區域 | 欄位 | 值 | 狀態 | Evidence source | 缺口／下一步 |
|---|---|---|---|---|---|
| Correlation | `event_id` |  |  |  |  |
| Correlation | `action_id` |  |  |  |  |
| Correlation | `trace_id`／`span_id` |  |  |  |  |
| Identity | verified principal |  |  |  |  |
| Identity | on-behalf-of／delegation |  |  |  |  |
| Identity | workload identity |  |  |  |  |
| Agent | Runtime／framework |  |  |  |  |
| Agent | model／provider |  |  |  |  |
| Artifact | image digest／Git revision |  |  |  |  |
| Credential | reference／fingerprint |  |  |  |  |
| Target | Tool／method |  |  |  |  |
| Target | resource／tenant |  |  |  |  |
| Policy | policy ID／version |  |  |  |  |
| Policy | decision／reason |  |  |  |  |
| Policy | enforcement point |  |  |  |  |
| Approval | approver／scope／expiry |  |  |  |  |
| Result | protocol／Tool result |  |  |  |  |
| Effect | receipt／resource version |  |  |  |  |
| Backend | Tempo／trace presence |  |  |  |  |
| Backend | Loki／structured event |  |  |  |  |
| Backend | Prometheus／aggregate metric |  |  |  |  |
| Integrity | event-time tamper evidence |  |  |  |  |
| Retention | policy／legal hold |  |  |  |  |

## 三個容易混淆的判斷

1. 同一個 `trace_id` 可以包含多個 Tool Call；應使用 `action_id` 或 Tool／resource／time window 收斂目標 action。
2. Trace、log 和 metric 共用 correlation field，不代表它們具備相同保存期、完整性或存取控制。
3. `DENY` 之後沒有 effect receipt 可以是 `NOT_APPLICABLE`；`ALLOW` 之後找不到 receipt 應先標 `UNKNOWN`。

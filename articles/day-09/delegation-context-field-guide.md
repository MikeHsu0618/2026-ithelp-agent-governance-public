# Delegation Context v0.1 Field Guide

這是一份公開 Lab 的 audit-context contract，不是 IETF、A2A、OpenTelemetry 或 CNCF 標準。正式採用前要依組織的 IdP、workload attestation、資料保留與 policy engine 調整。

可直接使用的 schema：[`delegation-context-v0.1.schema.json`](../../labs/02-identity-boundary/src/identity_boundary/schemas/delegation-context-v0.1.schema.json)

## 最外層欄位

| Field | 用途 | 不應被誤解為 |
| --- | --- | --- |
| `schema_version` | 消費端選擇 parser／migration | Agent artifact version |
| `event_id` | 單筆 context 的唯一識別 | 跨服務 trace |
| `trace_id` | 串接同一條 distributed trace | Human、session 或 credential identity |
| `timestamp` | 事件建立時間，UTC RFC 3339 | Token `iat`／`exp` |
| `flow_kind` | `HUMAN_DELEGATED`、`SERVICE_AUTONOMOUS`、`AGENT_TO_AGENT` | OAuth grant type |
| `actor_chain` | Human、Service、Agents 與 Workload | 已完成授權的結論 |
| `credential` | 已驗 credential 的最小關聯資訊 | bearer token 的儲存位置 |
| `target` | resource 與 action | policy decision／execution result |

`trace_id` 採 W3C Trace Context 的 32 位小寫十六進位格式，並拒絕 32 個零；它只做 correlation。

## actor_chain

| Slot | 必填內容 | 常見 evidence source | 本 Lab 的限制 |
| --- | --- | --- | --- |
| `human` | state；PRESENT 時另有 principal、source、level | verified access-token `sub`、approval event | 不接受 email 或 display name 推測 |
| `service` | state；PRESENT 時另有 principal、source、level | authenticated OAuth client／Service principal | public `client_id` 留在 credential context，不填這個 slot |
| `agents[]` | sequence、principal、version、role、source、level | 受控 artifact／deployment metadata、可信 Agent Card | metadata 是 assertion，不是 cryptographic proof |
| `workload` | state；PRESENT 時另有 principal、source、level | bound ServiceAccount、SPIFFE ID、cloud workload identity | 合成 ServiceAccount 只標 `ASSERTED` |

`principal` 可以是 issuer namespace 內的 opaque identifier，例如 Cognito／OIDC 常見的 UUID；不要求它一定帶 `user/` 或 URI prefix。若組織另外建立 canonical principal naming，應保留原 issuer／subject 對照，不能從 display name 自行拼接。

`agents[]` 的規則：

- `sequence` 從 `0` 開始並連續遞增。
- 前面的 Agent 都是 `DELEGATING`。
- 只有最後一個 Agent 能是 `EXECUTING`。
- 最多 16 個 hop，避免無界 context 膨脹。

## Identity state

| State | 意義 | 例子 |
| --- | --- | --- |
| `PRESENT` | 有 identifier，也能說明來源與可信程度 | access token 驗過的 `sub` |
| `UNKNOWN` | 這條 flow 理應有該角色，目前證據取不到 | A2A upstream 沒傳 workload identity |
| `NOT_APPLICABLE` | 這條 flow 本來就沒有該角色 | 排程工作沒有 interactive Human |

`null` 不在 contract 裡。它無法回答「不存在」「未取得」「解析失敗」哪一種情況。

## Evidence level

| Level | 判讀方式 | 範例 |
| --- | --- | --- |
| `VERIFIED` | 此 decision point 已用受信任機制驗過該 identifier | access token 的 `sub`、通過 client authentication 的 confidential client |
| `ASSERTED` | 來自受控 metadata 或上游陳述，但本點沒有獨立密碼學證明 | Agent artifact version、尚未 attested 的 ServiceAccount metadata |
| `CONTEXT_ONLY` | 有助於定位 actor 或 flow，不能單獨當 authenticated principal | 尚未由本觀測點驗證的上游 actor identifier |

這三個值描述「目前這個觀測點手上有什麼證據」，不是對整個組織永久有效的信任等級。

Public OAuth `client_id` 屬於下方的 credential context。它可以是已驗 access token 裡的可信 claim，但沒有 client authentication 時仍不是 Service principal，因此 Human flow 的 `service` 應標 `NOT_APPLICABLE`。

## credential

Schema 只接受下列欄位：

```json
{
  "type": "OAUTH_ACCESS_TOKEN",
  "issuer": "https://issuer.lab.example/identity-boundary",
  "subject": "user/sre-oncaller",
  "client_id": "sre-console",
  "audiences": ["mcp://lab/observability/query"],
  "fingerprint": "sha256:5d333c1b..."
}
```

`fingerprint` 用於同環境內的事件關聯，不能反推出 bearer credential。仍須限制存取與 retention，因為它可以成為高基數、可關聯的識別資料。`access_token`、`authorization` 或 raw claims 不在允許欄位內。

v0.1 只定義 `OAUTH_ACCESS_TOKEN`。SPIFFE SVID、bound ServiceAccount token 或 cloud workload credential 的欄位不硬套成 `client_id`；實際加入該 flow 時應建立新的 credential profile 並做相容性 review。

## Schema 與 semantic checks

| Case | Schema 層 | Semantic 層 | Result code |
| --- | --- | --- | --- |
| 缺 `workload` slot | reject | 不執行 | `REQUIRED_FIELD_MISSING` |
| `human=null` | reject | 不執行 | `NULL_NOT_ALLOWED` |
| credential 多出 raw `access_token` | reject | 不執行 | `FIELD_NOT_ALLOWED` |
| Agent sequence 重複 | pass | reject | `AGENT_SEQUENCE_INVALID` |
| `EXECUTING` Agent 不在最後 | pass | reject | `AGENT_ROLE_INVALID` |
| A2A workload 為明確 `UNKNOWN` | pass | pass | `ACCEPT` |

JSON Schema 適合約束欄位、型別、長度與封閉物件。跨陣列順序、flow 與 identity-state 的關聯則由 semantic validator 處理；兩層都使用穩定錯誤碼。

## 可直接複製的查詢

找出 Human 已知、Workload 未知的事件：

```bash
jq 'select(
  .actor_chain.human.state == "PRESENT" and
  .actor_chain.workload.state == "UNKNOWN"
)' contexts/*.json
```

輸出 Agent delegation order：

```bash
jq -r '
  .actor_chain.agents[] |
  [.sequence, .principal, .version, .role] | @tsv
' contexts/human_delegated.json
```

找出 validation event 裡缺少 workload evidence 的案例：

```bash
jq 'select(.workload_state == "UNKNOWN" or .workload_state == "MISSING")' \
  events.jsonl
```

## v0.1 的升版原則

- 新增 required field、改變 state 語意或重新定義 role 時升 breaking version。
- 新增 enum 值也視為相容性風險；舊 consumer 可能 fail closed。
- Audit event 可引用或內嵌這份 context，但 policy decision、execution result、retention 與 integrity proof 應在外層治理事件另行定義。
- Day 26 的 Governance Event Schema 會把這份 v0.1 當 actor-context 基礎，而不是偷偷改寫舊欄位。

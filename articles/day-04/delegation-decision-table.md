# Agent Delegation Decision Table

這份表不是 OAuth implementation checklist。它先逼一條 Agent action path 回答：誰提出意圖、誰解讀意圖、誰拿 credential 執行，以及動作最後落到哪裡。

## Day 3 已填寫範例

`UNKNOWN` 只表示目前沒有證據。它不能拿來代替「有值但未驗證」，也不能把「事件裡有記、policy 卻沒收到」含糊帶過。

| Decision input | Day 3 的值 | 證據狀態 | 證據位置 | Policy 現在看得到嗎 | 設計判斷 |
| --- | --- | --- | --- | --- | --- |
| request／trace | `trace_id` | 已產生並保存 | ordered events／summary | 否 | 應成為 decision 與 audit 的 join key |
| human principal | `synthetic-user-sre-oncaller` | 有值但未驗證 | ADK session setup | 否 | Session label 不能冒充 IdP principal |
| delegating agent | `sre_investigation_agent` | 設定 metadata | Agent definition | 否 | 名稱與版本要可回查，名稱本身不是 credential |
| executing workload | `UNKNOWN` | 沒有證據 | 無 workload identity event | 否 | 不可用 Agent 名稱代替實際執行者 |
| credential subject | `UNKNOWN` | 沒有證據 | Lab 沒有 workload token | 否 | 要能和 executing workload 對得上 |
| credential audience | `UNKNOWN` | 沒有證據 | Lab 沒有 access token | 否 | 不能讓入口 token 任意轉交下游 |
| action | `delete_demo_database` | ADK Tool Call | model／policy event | **是** | 目前唯一 policy input |
| requested target | `payments-demo` | Tool argument，未驗證 | policy event | 否 | 同一 Tool 對不同 environment 不能共用答案 |
| delegated scope | `UNKNOWN` | 沒有證據 | 無 delegation context | 否 | 要比 workload 自身 authority 更窄 |
| approval context | `UNKNOWN` | 沒有證據 | 無 approval event | 否 | 高風險 action 不能由缺席值默認通過 |
| policy decision | `DENY` | 已產生並保存 | `policy.decision` | 輸出 | 應保留 reason、version 與完整 decision input |

## 空白模板

複製這張表到 ADR、Threat Model 或 pull request。先分清楚「沒有證據」「有值但未驗證」與「policy 看不到」，再決定缺口應由 IdP、Agent runtime、Gateway、Tool server 或 audit pipeline 補上。

| Decision input | 值／格式 | 證據狀態 | 誰簽發或觀察 | Policy 是否驗證 | Audit 是否保存 | 缺值時怎麼處理 |
| --- | --- | --- | --- | --- | --- | --- |
| request／trace |  |  |  |  |  |  |
| human principal |  |  |  |  |  |  |
| delegating agent |  |  |  |  |  |  |
| executing workload |  |  |  |  |  |  |
| credential subject |  |  |  |  |  |  |
| credential audience |  |  |  |  |  |  |
| action |  |  |  |  |  |  |
| target resource |  |  |  |  |  |  |
| delegated scope |  |  |  |  |  |  |
| approval context |  |  |  |  |  |  |
| policy decision／version |  |  |  |  |  |  |

## Review 時逐條追問

1. Human 不在線時，`human principal` 是沿用先前授權、改成 service principal，還是明確為空？
2. Agent 名稱來自 deployment metadata，還是由可信 Registry／artifact digest 綁定？
3. 真正送出 request 的 pod、process 或 external service，能否用 workload identity 驗證？
4. Credential 是轉送原 token、交換成 audience-bound token，還是 workload 自己的 static key？
5. `action + target resource + environment` 是否一起進入 policy，而不只看 Tool name？
6. Delegated scope 是否小於等於 Human 可授權範圍，也小於等於 workload 可執行範圍？
7. DENY、approval 與下游 resource-server decision 能否用同一個 trace／request key 重建？

## 使用邊界

這張表刻意不指定 JWT claim 名稱、Token Exchange 產品或 policy language。資料缺口先畫對，Day 7–12 才有理由選 public client、confidential client、PKCE、Client Credentials 或 OBO／Token Exchange。

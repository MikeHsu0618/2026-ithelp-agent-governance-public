# Day 9｜Delegation Context 實作：釐清 Gateway、Agent Runtime 與 Kubernetes 的責任邊界

把 Cognito 的登入接到 Agent 入口後，我原本想在稽核紀錄留一個 `actor` 就好：Human flow 記使用者的 `sub`，無人值守的工作記 ServiceAccount。畫出實際呼叫路徑時，這個欄位馬上不夠用了。

想像值班工程師請 SRE Copilot 查登入錯誤。Copilot 把工作交給 Investigator Agent，最後由 Kubernetes 裡的 runtime 呼叫 MCP `query_logs`。如果查詢範圍不對，事後只留下 `actor=user/sre-oncaller`，看起來像工程師親手下了查詢。只留下執行用的 ServiceAccount，又像一個沒有來由的排程工作。兩筆紀錄都可能是真的，卻都不足以回答「這次 Tool Call 是怎麼走到這裡的」。

這是我在整理 Cognito Human 與 Agent runtime 的責任歸屬時，拿來檢查設計的合成情境。Day 8 已經處理 Gateway 如何驗眼前那枚 Token。這次要補的是 Token 沒打算回答的事：誰提出任務、Agent 之間如何轉交、哪個 runtime 最後送出 Tool Call。

## 同一筆查詢，在三個地方會有三種答案

Gateway 看得到目前進站的 Token，能識別這次登入的值班工程師。Agent runtime 知道 Copilot 把任務交給哪版 Investigator，以及後者呼叫了什麼 Tool。Kubernetes 則知道程式以哪個 ServiceAccount 執行。單獨查任何一邊，都只能看見一段。

![值班工程師請 Copilot 調查，Copilot 委派 Investigator，再由 Kubernetes workload 呼叫 query_logs。圖下方是同一次 Tool Call 保存的 actor chain、credential、target 與事件關聯欄位。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-18-r1/assets/diagrams/day-09/delegation-sequence.png)

Delegation Context 是每筆 Tool Call 附帶的交接紀錄。它讓事後查詢能分清「誰要求」和「誰執行」，不用從 `actor`、Pod 名稱與幾段 log 猜一條故事。`trace_id` 可以幫忙找到同一條請求的事件，但它本身不會告訴我們每個角色在這次委派裡做了什麼。接收請求的系統仍要自己判斷能不能執行。

在這個設計裡，入口先記下已驗的 Human，Copilot 交辦時留下自己的 Agent 版本，Investigator 接手後成為最後執行的 Agent。等 Tool Call 真要送出，才把當前憑證、執行它的 Workload 和 `query_logs` 目標一起寫進事件。這不是期待某個元件憑空知道整條鏈：上游若沒把委派資訊傳下來，Gateway 在最後一跳無法從 Token 的 `sub` 推回是哪版 Agent 接了工作。

如果異常來自工程師指定的查詢，修法可能落在操作介面。Copilot 若把工作交錯了 Agent，就要查委派邏輯。同一種查詢若在 Investigator 換版後才出問題，則要回頭看 Agent artifact。只存一個 `actor`，值班的人連該先找誰一起查都容易判錯。

## Delegation Context 怎麼記

公開 Lab 的 [Human delegated 範例](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r1/assets/screenshots/day-09/evidence/demo-context-human-delegated.json) 將這次 `query_logs` 留成一筆事件。`actor_chain` 記下值班工程師、Copilot、Investigator 與執行的 Workload。`credential` 記當前觀測點所見的 issuer、subject、client、audience 與指紋，`target` 則記這次碰的是哪個 resource、哪個 action。`event_id`、時間與 `trace_id` 方便回頭找同一次動作。完整欄位與 schema 放在 [Delegation Context Field Guide](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r1/articles/day-09/delegation-context-field-guide.md)，正文先拿它回答值班時最直接的問題。

從 repo root 執行以下查詢，可以從同一筆紀錄取出任務來源、最後執行的 Agent 版本、Workload 與 Tool：

```bash
jq -r '[
  .actor_chain.human.principal,
  (.actor_chain.agents[] | select(.role == "EXECUTING") | (.principal + "@" + .version)),
  .actor_chain.workload.principal,
  .target.action
] | @tsv' assets/screenshots/day-09/evidence/demo-context-human-delegated.json
```

```text
user/sre-oncaller  agent/sre-investigator@v1  k8s://lab/identity-boundary/sa/sre-agent  query_logs
```

這行輸出比 `actor=user/sre-oncaller` 多回答了兩件事：最後是哪版 Agent 執行，以及請求從哪個 Workload 送出。`agents[]` 還保留完整的委派順序，Copilot 是 `DELEGATING`，Investigator 是 `EXECUTING`。同一筆事件的 `target` 能指出 MCP resource，而不只留一個 Tool 名稱。Context 保留了這些差異，卻不代表只憑這筆 JSON 就能判斷當時該不該允許查詢。

這份 v0.1 是本系列設計的 audit 資料契約，不是 OAuth、A2A 或 OpenTelemetry 的標準格式。它也沒有偷偷把 `client_id` 當成另一個已登入的 Service。公開 Human flow 的 `client_id=sre-console` 表示使用了哪個 OAuth client。因為沒有另一個獨立驗證過的 Service actor，`service` 欄位寫 `NOT_APPLICABLE`。

## 排程任務與遺失的身分不能寫成同一種空值

值班工程師發起的任務有 Human，排程 Agent 則從頭到尾沒有互動式登入者。還有第三種麻煩狀況：上游 Agent 本來應該傳來 Human 或 Workload，資料卻在交接時沒帶到。若這些情況都記成 `null`，之後查詢時無法區分正常的無人工作和真的漏了欄位。

Lab 對這幾種情況給出不同結果：

| 情境 | Context 怎麼寫 | 結果 |
| --- | --- | --- |
| 排程 Agent | Human 是 `NOT_APPLICABLE`，這條路徑本來沒有登入者 | `ACCEPT` |
| 上游沒有傳 Workload 身分 | Workload 是 `UNKNOWN`，並記下原因 | `ACCEPT` |
| Human 委派卻漏掉整個 Workload 欄位 | 沒有值，也沒有說明缺口 | `REQUIRED_FIELD_MISSING` |

`UNKNOWN` 仍能通過資料檢查，因為這筆紀錄明確表示資訊缺失。它不會因此取得執行權限，真正的 policy 完全可以拒絕缺少 Workload 身分的請求。把缺口明寫出來的好處，是值班時可以直接篩出哪些 Agent 路徑丟了交接資訊，而不是靠人看空白猜原因。

## 用 Lab 檢查責任鏈有沒有寫完整

[Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r1/labs/02-identity-boundary/README.md) 使用合成的值班工程師、Agent 與 ServiceAccount，檢查這份資料契約是否能區分上述情境。在 repo root 執行：

```bash
make lab-02-up
make lab-02-delegation
```

下面是最能看出差異的四組結果。其餘負向案例與原始紀錄在 [Day 9 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r1/assets/screenshots/day-09/evidence.md)。

```text
human_delegated        ACCEPT
scheduled_service      ACCEPT
a2a_unknown_workload   ACCEPT
missing_workload_slot  REJECT  REQUIRED_FIELD_MISSING
```

![Delegation Context Lab 的七組實際 CLI 結果。Human delegated、排程與明確標示未知身分的案例通過。缺欄位、null、Agent 順序錯誤及 actor-only 紀錄被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-18-r1/assets/screenshots/day-09/01-delegation-context-results.png)

Lab 跑的是 JSON Schema 與語意檢查：必填欄位、Agent 委派順序、哪些角色不存在、哪些角色只是暫時未知。這已經能擋掉 `actor` 以外什麼都沒留的紀錄，也能讓後續查詢使用同一套欄位。合成請求沒有真的穿過 Gateway 或 Kubernetes，`ACCEPT` 也不表示授權成功。

## 誰填的欄位，會改變這份紀錄的用途

整理這份格式時，我最在意的不是 enum 要取什麼名字，而是誰能填它。Lab 的 Human 來自合成的已驗 Token，Agent 版本來自受控 metadata，Workload 來自合成 Pod 設定。這些欄位都能放進 Context，但不能因為排在同一個 JSON 裡，就當成經過同一種驗證。

例如 client 可以自己送出 `evidence_level="VERIFIED"`。Schema 會認得這個合法值，卻無法確認 Gateway 是否真的驗過 Token。若平台要用 Context 做正式稽核，Gateway 就必須掌握自己驗過的身分欄位。Agent 版本與 Workload 身分也要有明確的填寫來源，不能讓任意呼叫者替自己掛上可信標籤。這是平台在交接點要設計的寫入權限，公開 Lab 目前只做到資料格式。

Day 9 先解決的是「一次 Agent 動作該怎麼留下完整責任鏈」。但就算 Audit 能查到值班工程師、Investigator 與 Workload，下游 MCP 收到的仍可能只是值班工程師原來的 access token。Context 無法把那枚 Token 變成下游專用憑證。下一篇會讓同一枚 Token 走到兩個不同 resource，看看嚴格驗 audience 與直接放寬驗證各會留下什麼問題。

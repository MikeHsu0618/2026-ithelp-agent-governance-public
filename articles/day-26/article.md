# Day 26｜Agent 事件回放實戰：從 Trace ID 查回操作與授權證據

拿到一個 Trace ID，通常可以開始回答「這次請求經過哪幾個服務，時間花在哪裡」。如果調查的是一次可疑工具操作，接下來還會有人問：使用者原本要求什麼？Agent 提出哪個動作？誰放行？最後資源有沒有改動？這些答案不一定都在 Waterfall 裡。

事件回放，就是用保留下來的紀錄，重新建立這些動作和判斷的時間線。它不是把模型再跑一次，也不是讓模型替缺失資料寫出合理故事。調查者要能指出每個結論來自哪份資料，並說明有哪些問題當時根本沒有記下來。

本篇回看系列最初的安全示範：Agent 讀到混入操作指令的 Log，提出 `delete_demo_database`，工具只寫下 no-op 標記，沒有真的刪資料庫。這份歷史資料很適合練習回放，因為它能重建部分動作，也留下明確缺口。先看回放的方法，後段再對照當時的紀錄和後來的新觀測管線。

## 先確定正在調查哪個動作

一次 Agent 工作可能包含多個工具。查異常時，Agent 可能先查 Logs，再查 Metrics，最後整理回答。如果把整條 Trace 的最後狀態當成所有工具的結果，前面某個錯誤或危險操作就可能被後面的成功蓋掉。

本系列的歷史資料正好有這個情況。同一條 Trace 裡，Agent 先提出 `delete_demo_database`，後來又呼叫 `query_metrics`。第二個工具成功，並不能改變第一個工具已走到安全 Canary 分支的事實。Day 1 的 Summary Bug，就是在摘要時沒有維持這個動作粒度。

因此回放前要先選定目標動作，再找屬於它的提議、Policy Decision 和執行結果。共用的工作開始、工作結束事件可以提供時間範圍，其他工具的事件則不能拿來補目標動作的結果。

| 識別 | 要關聯的範圍 | 回放時的用途 |
| --- | --- | --- |
| `trace_id` | 一條技術執行路徑 | 找服務、呼叫關係與耗時 |
| `action_id` | 一個受治理的操作 | 對齊工具提議、授權與資源結果 |
| `event_id` | 一筆事件 | 識別哪份紀錄、處理重複寫入 |

這些 ID 需要在產生資料時有明確契約。舊紀錄只有 Trace ID 和 Span ID 時，今天的工具可以產生重建事件的識別，但不能把新 ID 說成當時已經存在的 Action ID。

## 一份證據能支持多強的結論

找到欄位，還要看它是怎麼取得的。Runtime 自行寫下 `ALLOW`，能說明它輸出過放行判斷。若另有可信的 Policy Decision Receipt，才可能再確認由哪個判斷點、依哪份規則簽發。兩者都可能有用，證據強度不同。

本篇用四種狀態標記這個差別。它們描述資料來源與適用性，調查者應連同原因一起讀：

- `VERIFIED`：本次回放能重新驗證某項性質，例如輸入檔符合鎖定的內容摘要。必須交代驗證的是什麼。
- `OBSERVED`：原始紀錄確實保存這個值，但沒有獨立來源確認它的內容。
- `UNKNOWN`：沒有足夠資料回答，不能把空白換成安全或未發生。
- `NOT_APPLICABLE`：依已知流程，這個欄位在此處不應產生。

例如 Policy 在執行前拒絕工具，原本就不會有工具修改結果，可以記為不適用。若 Policy 放行，卻找不到結果，則要記未知，繼續查工具端與儲存管線。兩種空白會導向不同調查工作。

HITL 的批准也一樣。沒有找到 Approval，可能是流程不需要，也可能需要但未留下紀錄。要判定不適用，必須先有當時的規則和流程依據，不能只因為檔案裡沒有這個欄位就推論沒有人工核准。

## 回放歷史操作的時間線

[Lab 05 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-26-r5/labs/05-incident-replay/README.md) 讀取鎖定的 Day 1、Day 3 Artifacts，包含 Manifest、JSONL 事件和 Canary 收據。這些都是當時的本機檔案。它們沒有證明那條舊 Trace 曾送進 Tempo 或 Loki，因此後段的新後端查詢另算一組證據。

下圖上方是歷史檔案到重建事件的路徑，下方是重新送出的現行請求。先分開它們的時間和來源，才能避免把今天查得到的資料放回舊事件。

![歷史 Artifact 產生重建治理事件，現行請求另驗證 LGTM 查詢能力。兩组資料屬於不同 Run。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-26-r5/assets/diagrams/day-26/replay-evidence-boundary.png)

Day 1 原始事件包含共用的開始、結束，以及兩組工具動作。目標工具的順序是：

```text
delete_demo_database
  model.tool_call -> policy.decision -> tool.executed

query_metrics
  model.tool_call -> policy.decision -> tool.executed
```

回放 `delete_demo_database` 時，只保留它的三筆 Action Events 和共用的 Run Events。`query_metrics` 用來確認同一工作還做了別的事，不加入刪除工具的結果。

重建事件為每個欄位保存 Value、Status、Sources 和 Reason，也就是值、證據狀態、來源與理由。原始 Action ID 不存在，就保留這個缺口。`evt-replay-*` 識別的是今天產生的 Projection，事件類型也標為 `RECONSTRUCTED_GOVERNANCE_EVENT`。

## 歷史資料留下的內容與缺口

原始 Manifest 和事件都記錄 Trace ID，工具提議、Policy 和執行事件也能互相對照。這讓我們知道模型提出哪個工具、Runtime 寫下什麼判斷，以及安全 Canary 是否觸發。它們仍不足以說明完整的發起者身分和執行產物。

| 回放問題 | 現有資料 | 證據狀態 |
| --- | --- | --- |
| 提出哪個工具？ | `delete_demo_database`，提議與執行紀錄可對照 | `OBSERVED` |
| Runtime 決定什麼？ | `ALLOW`，沒有獨立 Decision Receipt | `OBSERVED` |
| 工具留下什麼結果？ | `CANARY_TRIGGERED` 的 no-op Artifact | `OBSERVED` |
| 哪個可信主體發起？ | 缺經驗證的 Human／Service Principal | `UNKNOWN` |
| 實際跑哪份 Agent？ | 缺映像 Digest 或 Deployment Revision | `UNKNOWN` |
| 是否完成必要的批准？ | 缺足夠的 Approval 紀錄 | `UNKNOWN` |
| 當時是否保存到 Tempo？ | 缺舊 Trace 的 Backend Receipt | `UNKNOWN` |

回放工具能驗證輸入檔案符合 Repository Lock，但這不會把檔案中的所有欄位一起升成 `VERIFIED`。檔案內容沒變，和當時寫入者的身分可信，是兩種不同性質。

缺少 Principal 時，也不從 Username、Pod Name 或模型名稱猜出一個。這樣保留下來的事件可能不好看，卻能明確告訴下一次 Instrumentation：入口應記身分驗證來源，Runtime 應記執行版本，需要批准的流程應留下可對回動作的決定。

## 執行前拒絕的對照

Day 3 的相同危險工具提議，在 Tool Allowlist 做出 `DENY` 後，沒有走到 `tool.executed`，Canary 檔也為空。先前的 Keyword Guard 仍可能被混淆字串繞過，但執行前的工具控制確實終止了這條路徑。

這時修改結果應是 `NOT_APPLICABLE`。若強迫每個動作都交一份 Effect Receipt，實作者反而可能替沒有執行的工具補造結果。回放要按實際分支判斷需要哪些證據，才看得出控制在哪裡生效。

真正修改資源的工具則需要相應結果。建立工單可以保存後端回傳的 Ticket ID，修改 Kubernetes 資源可以核對 Revision 與後續狀態，資料操作需要對照交易或查詢結果。這些是設計例子，不能用本篇 no-op 收據證明它們已完成。HTTP 狀態和 Span 結束只能提供過程線索，資源結果要由能確認它的元件回報。

## 現行管線能保存什麼

歷史回放之外，Lab 另外送一筆新的 `normal-call`。它經 Client、agentgateway、Runtime 和 MCP Adapter，再將訊號送進 Alloy 和 LGTM。新請求有自己的 Action ID 和 Trace ID，用來檢查現行管線的查詢能力。

下圖是這次新請求的 Tempo Waterfall。可以沿 Runtime 的下游呼叫找到 MCP Adapter，確認工具端與入口仍在同一條路徑，而不只是各自有紀錄。

![現行請求的 Tempo 實拍：四個服務、八個 Span，能追到 MCP Adapter。這不是 Day 1 的歷史 Trace。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-26-r5/assets/screenshots/day-26/grafana-tempo-action-trace.png)

Tempo 查到四個 Service、八個 Span。Loki 找到四筆帶相同 `action_id` 的結構化事件，Prometheus 也收到 Gateway 聚合指標。三者分別提供路徑、事件內容與整體趨勢，沒有為回放把每筆操作 ID 加進 Metric Label。

這組結果讓我們知道今天的資料可以如何關聯，不能改善舊事件原本沒有寫下的欄位。即使現行 Waterfall 完整，還要另外檢查可信 Principal、Policy、Approval 和 Effect 是否有來源，才能做授權調查。

## 檔案一致性與保存完整性

歷史 Case Directory 的 `evidence-lock.json` 保存內容摘要。Replay 前會重新計算 Manifest、Events 和 Canary 的 SHA-256，任何差異都停止。這能讓文章、測試和後續重跑使用同一份輸入，避免素材隨編輯悄悄改變。

這份 Lock 不是事件發生當下的簽章，也不能證明一名有權修改 Repository 的人無法同時改檔案與 Lock。若組織需要防刪改或長期保存，應按具體要求檢查寫入權限、保存機制與存取紀錄。Git 版本可以追設定與素材變更，每次 Agent 執行仍需要自己的事件來源。

觀測資料也可能因 Sampling、Collector 故障或 Retention 而缺失。查不到工具事件時，先確認原本由誰寫入、管線是否送達、資料是否已過保存期，再決定能做什麼結論。沒有紀錄是一個調查狀態，不能單独當成沒有發生的證據。

完整欄位可對照 [Governance Event Schema v1](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-26-r5/labs/05-incident-replay/src/incident_replay/schemas/replay-event-v1.schema.json) 和 [Incident Replay 欄位指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-26-r5/articles/day-26/incident-replay-field-guide.md)。把來源和未知保留在事件裡，下一次審查才能分辨該補驗證、補 Instrumentation，還是補保存。

回放最後留下的問題，是每份證據原本由哪個系統負責提供。下一篇把身分、Runtime、Gateway、交付和觀測放回同一張產品地圖，讓缺口能對到具體的位置與維護者。

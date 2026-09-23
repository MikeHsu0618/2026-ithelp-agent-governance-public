# Agent Governance 能力盤點表

這份表給讀者拿自己的請求路徑填，不是作者的採購結論。先挑一筆具體行動，例如「值班者請 Agent 查 Loki」，再把每一站由誰提供、誰維護寫進去。沒有需求的項目可以留白，不必湊滿。

| 請求中的工作 | 在自己的環境先問什麼 | 可填入的系統或角色 | 容易漏掉的接縫 |
| --- | --- | --- | --- |
| 使用者登入 | 是 Human、Service，還是 Workload？ | 現有 IdP、應用、Runtime | Client Credentials 不直接識別 Pod |
| 共用流量入口 | 哪些 Agent 重複處理驗證、路由與政策？ | Gateway、Ingress、應用 | Ingress 與 AI Gateway 未必互相替代 |
| Agent 內部動作 | 誰決定呼叫 Tool、帶什麼參數？ | Agent Runtime、應用團隊 | Gateway 不知道業務意圖 |
| 資源存取 | Tool 實際用哪個帳號查詢或修改資料？ | MCP Server、Resource Server | 入口放行不等於資源授權 |
| Agent 交付 | 程式從哪裡發布，實際執行哪份映像？ | Git、CI、映像倉庫、Runtime | Tag 可變，需看實際 Digest |
| 目錄與部署 | 多個團隊要去哪裡找版本、提出部署？ | 現有目錄、Agent Registry、kagent | Catalog 標籤不等於執行時授權 |
| 觀測與調查 | 出事時能否沿同一筆請求找到 Tool 結果？ | Gateway Telemetry、Alloy、LGTM | 先分辨驗證過的欄位和自行填入的欄位 |
| 變更與執行紀錄 | 設定變更在哪裡查？每次 Agent 呼叫又在哪裡查？ | Git PR／Commit、部署紀錄、Gateway／Runtime Log、LGTM | Git history 不會記下每筆 Tool Call |
| 成本 | 是看趨勢，還是要向團隊正式分帳？ | Gateway Usage、Provider 帳單、FinOps | 估算與帳單不是同一件事 |

## 範例：唯讀的 Loki 調查

值班同仁用既有 IdP 登入，SRE Agent 由應用團隊維護，Grafana MCP 只拿到查詢必要資料的權限，Gateway 與 Alloy 將請求串進既有 LGTM。這條路徑先要確認的，是 MCP 查詢帳號的範圍、Gateway 的 Caller 欄位來源，以及 Tool 失敗時去哪裡查。若只有一個團隊使用，沒有跨團隊上架需求，就不需要為了完成表格增設 Registry。

當這支 Agent 開始替多個團隊服務，才回頭問上架、版本與部署由誰接手。若它進一步能修改正式環境，優先追問資源授權、人工核准與執行結果。需求一變，表格要補的不是更多產品名稱，而是新出現的接縫。

可下載的 [CSV 版本](capability-ledger.csv) 保留相同欄位，方便複製到試算表，填上你自己的系統、維護者與待釐清事項。

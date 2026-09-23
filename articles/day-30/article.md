# Day 30｜Agent Governance 最終章：三十天後，我們留下的參考架構

三十天前，Gemini 從一段混入操作指令的 Log 讀到 `delete_demo_database`，接著提出 Tool Call。Google ADK 把參數交給 Tool，open policy 也照設定回了 `ALLOW`。公開 Lab 沒有真的刪除資料庫，只留下 `CANARY_TRIGGERED` receipt。換成有副作用的 Resource Server，這條正常運作的 action path 就可能改到 production 資料。

三十天後，模型仍可能提出同一個 Tool Call。如果今天重新設計，我會先問這筆動作應在哪裡遇到決策點，執行後又該留下哪些可查證的結果。最後的參考架構，就是把這兩個問題放進一條能檢查的路徑，不再寄望模型突然變得永遠正確。

## 同一筆 Tool Call，前後差在哪裡

Day 1 的 Lab 留下了危險動作的安全標記，Day 3 則試出一個有效的執行前拒絕點。如果下一筆高風險 Action 真的要碰資源，還需要哪些控制？右欄是接下來的設計目標，和左欄已跑過的 Lab 分開看。

| 這一站 | 當時的公開 Lab | 下一筆高風險 Action 的設計目標 |
| --- | --- | --- |
| 讀到不可信內容 | Log 裡的指令進入模型 Context，模型提出危險 Tool | 把外部內容當資料，不讓它直接取得動作權限 |
| 執行前決策 | Open Policy 回 `ALLOW`。Day 3 另驗出 Tool Allowlist 可在執行前拒絕 | 共同入口與目標服務各守自己的授權邊界，並檢查 Resource／Arguments |
| 真正的執行結果 | Tool 只寫安全標記，沒有刪除資料庫 | Resource Server 回傳可對回同一筆 Action 的實際修改紀錄 |
| 事故發生後 | 能找回當時留下的 Event 與 Trace ID，卻缺可信發起者和執行映像 | 沿同一筆 Action 查回身分、政策、實際映像、必要的核准與結果 |

Day 3 用相同輸入做了放行與拒絕對照：換成 Tool Allowlist 後，危險 Function 沒有執行，Agent 仍改用 `query_metrics` 完成唯讀調查。這筆對照的回放資料留在 [Incident Replay Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-12-r3/labs/05-incident-replay/README.md)。

## Reference Architecture 的四條路徑

最後的圖只有一條主要動作路徑：呼叫者提出請求，Gateway 檢查共同規則，Agent Runtime 決定下一步，Tool 所屬的服務決定資源能否修改。另外兩條支線回答執行版本從哪裡來、事後資料送到哪裡。架構審查不用先背完產品名稱，先沿這筆 Action 問誰能拒絕、誰能批准、實際跑了什麼。

![一筆 action 由 Human 或 M2M caller 經 agentgateway、Google ADK Runtime 到 Tool 或 Resource Server。下方 Artifact 卡片標明完整 Agent Image Digest、批准及執行映像核對仍是待驗證的設計目標。Evidence 卡片區分 Alloy／LGTM 與尚待獨立驗證的 Audit 保存。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-12-r3/assets/diagrams/day-30/reference-architecture.png)

## Request Path：Identity、Gateway 與 Resource Authorization

Human 與 M2M 先走各自的登入／取 Token 流程，再把憑證帶進請求。Cognito 完成簽發後就退出資料面，業務流量不必穿過 IdP。前面已交代為什麼沒有為少數 AI 服務另建 Identity Center。在這張圖裡，重要的是兩種 Caller 都有明確的驗證入口，而不是再比較 IdP 功能。

帶著 Token 的 request 可以經過既有 Ingress，但那一層只保留成 optional pass-through edge。agentgateway 才是跨 Runtime 共用的 checkpoint，負責驗 issuer、audience、signature、route、rate limit 與最低共同 policy，也產生 gateway request ID、policy version 和 decision。它可以拒絕不符合共同規則的流量，卻不知道某張工單是否真的允許刪除指定資料庫。

Google ADK Runtime 接手 workflow、state、Tool schema、argument normalization、delegation 與 pause／resume。真正有副作用的 Tool／Resource Server 仍保留最後授權：它要看受信任 principal、current actor、目標 resource 與 normalized arguments，再依自己的 business rule 決定是否執行並回傳 effect receipt。Gateway 已經回 `ALLOW`，不代表任何 Tool 參數都合理。

### Context Rail：Principal、Policy、Artifact 與 Approval

Gateway 從驗過的 JWT 加入 principal／client 與 policy decision。Runtime 再加入 delegation、Tool、resource、normalized arguments、Artifact digest 和必要的 approval digest，Resource Server 最後補 effect receipt。Action ID 與 trace ID 負責把這些紀錄接回同一筆動作；每個欄位也保留來源，讓事故調查知道它是由哪一站寫入的。

高風險 action 若需要人工批准，Runtime 可以提供 pause／resume，平台可以提供 UI 與傳遞機制，Business Owner 則必須在完整 action context 下決定。一次批准要綁住 Tool、目標 resource 與參數摘要，並記下 approver、Artifact digest、policy version 與 expiry。任一內容改變，原本的批准就不能繼續使用。Day 18 跑通的是 pause／resume，包括 BYO Agent 的有限路徑。它沒有證明 approver 身分與授權，也沒有涵蓋所有跨 A2A／HITL 的 context 傳遞。這些不能因為畫面上有個「Approve」按鈕就算完成。

## Artifact Path：Desired State 與 Runtime Digest

Day 19 的 `approved` Catalog Tag 可以換掉 Image Reference。Day 18 固定的則是 BYO **基底映像** Digest。兩者的差異提醒我，架構圖不能只寫「版本已管理」。我們希望在 Git／OCI 交付時保存完整 Agent Image 的 Digest 與批准紀錄，部署時核對，事故事件再記錄實際執行版本。這條鏈尚未在公開 Lab 完成 Admission 與每個 Workload 的執行映像綁定，因此是下一步要驗證的設計，不是這三十天已交付的功能。

控制面說明「應該部署什麼」，執行中的 workload 則要證明「這次實際跑了什麼」。兩條路徑靠 Artifact digest 會合，事故發生後才不會只剩 deployment 宣告。

## Evidence Path：Operational Telemetry 與 Audit Integrity

既有 LGTM 是我們日常查 Log、Metric 與 Trace 的地方。Day 25 讓 SRE Agent 真的透過 Grafana MCP 查到 Loki。Day 26 再用另一筆新 Action 驗證 Tempo 的跨服務路徑、Loki 的事件和 Prometheus 的聚合資料。這些新紀錄能幫助調查今天的 Action，不能拿來補 Day 1 當時沒留下的資料。

在這張架構裡，設定與映像的變更先由 Git PR、Commit 和部署紀錄追溯，每次 Agent 呼叫則回到 Gateway、Runtime 與 LGTM 查。這已經能回答多數維運調查。若組織另有法遵要求，再檢查這些現有紀錄的存取與保存方式是否足夠；我們沒有因為 Agent 多建一套稽核儲存平台。

## 回到 Day 1 的 Tool Call

[去年寫 LLM Observability](https://ithelp.ithome.com.tw/articles/10380029) 時，我在意的是模型為什麼這樣回答、一次呼叫花了多少錢，以及 Prompt、Response、Token、Latency 能不能沿 trace 找回來。今年把 Agent 接上 Tool 後，問題往前移了一步：誰讓它做、它代表誰、跑的是哪份程式、哪一層有權拒絕，以及事後拿什麼證明。

執行前的 allowlist 可以拒絕危險 Tool，Agent 也不一定因此失去完成調查的能力；Day 3 已經跑過這個對照。難的是再往下追問：「誰准許這次操作？實際跑的是哪個版本？改動是否真的發生？」這三十天的其餘工作，就是把答案放回能作決定、能留下結果的地方。

這三十天裡，我最有感的不是把更多產品接進同一張圖，而是幾次「跑通後仍不採用」的決定。技術上能做，和組織有能力長期維護，是兩回事。產品可以隨條件更換，動作在哪裡被允許、被拒絕，以及事後如何查證，不能跟著模糊。

如果今天又有 Agent 讀到一段混著指令的 Log，模型仍可能提出危險 Tool Call。我希望不同的是，它會在碰到正式資料前遇到真正懂這個 Resource 的授權檢查。若仍獲准執行，值班的人能沿同一筆 Action 找到批准、版本和結果。這些要求有些已在 Lab 驗過，有些仍是我們明確留下的缺口。Day 1 的安全標記到最後沒有變成一場英雄救火，卻讓我們有機會在出事以前，把該由誰擋、誰准、誰查證問清楚。

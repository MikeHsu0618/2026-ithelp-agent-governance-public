# Day 30｜Agent Governance 最終章：三十天後，我們留下的參考架構

三十天前，Gemini 從一段混入操作指令的 Log 讀到 `delete_demo_database`，接著提出 Tool Call。Google ADK 把參數交給 Tool，open policy 也照設定回了 `ALLOW`。公開 Lab 沒有真的刪除資料庫，只留下 `CANARY_TRIGGERED` receipt。換成有副作用的 Resource Server，這條正常運作的 action path 就可能改到 production 資料。

三十天後，模型仍可能提出同一個 Tool Call。真正改變的是這筆 Action 現在會在哪裡遇到決策點，以及執行後能留下哪些證據。Reference Architecture 的工作，就是把兩者放進可檢查的路徑，不再寄望模型突然變得永遠正確。

## Day 1 留下的 Evidence Gap

`delete_demo_database` 的歷史紀錄不會因為三十天後畫出新架構，就自動補齊 principal、Artifact 或 approval。下面只使用已鎖定的 Day 1／3／26 資料，不拿今天的設計回頭改寫當年的事件。

| 要查的問題 | Day 1 目前能回答到哪裡 |
|---|---|
| 當時用了哪條 policy？ | 歷史 Artifact 記錄 `day-01-open-v1` 回 `ALLOW`，但沒有獨立的 decision receipt |
| Tool 有沒有真的執行？ | event 與 canary receipt 都記錄 `CANARY_TRIGGERED`。公開 Tool 是 no-op，不會連資料庫 |
| 能不能沿 trace 找回事件？ | trace ID 能連回已保存資料，但無法補回當時沒記錄的欄位 |
| repo 內的證據副本有沒有變？ | Day 26 重算 SHA-256，確認目前副本符合 lock。這不能證明 Day 1 之後從未被修改 |
| 誰以什麼身分發起？ | 當時沒有可信 token 與 delegation 紀錄，不能從任意 `user_id` 回推 |
| Runtime 跑的是哪份 Artifact？ | 找得到 Lab fixture，找不到當次執行映像的 immutable digest |
| 誰批准、紀錄能否防竄改？ | 當時沒有 action-bound approval，也沒有 tamper-evident Audit storage |

前四列有資料可以查，後三列只能停在「當時沒有留下」。即使一條 trace 能串起 Tool Call 與執行結果，也不能拿它推論當時是誰授權、跑了哪份程式。

Day 3 用改寫過的惡意 Log 做了另一組對照。兩次 live run 使用同一份輸入與模型設定，Gemini 都提出 `delete_demo_database`。全部放行時，安全標記增加一筆。換成 Tool allowlist，function 執行前就被拒絕，安全標記維持零。Agent 收到拒絕結果後，改用 `query_metrics` 完成原本的唯讀調查。這組結果只證明 Lab 裡的執行前拒絕點有效，沒有證明完整的企業授權已經到位。

完整事件與回放資料留在 [Incident Replay Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-22-r2/labs/05-incident-replay/README.md)。對下一筆真的有副作用的 action，架構還得補上可信身分、delegation、實際執行的 Artifact 與業務授權。執行後也要留下能對回同一筆 action 的 effect receipt。

## Reference Architecture 的四條路徑

三十天最後收斂成四條路徑。Request Path 安排每一層能做的決策，Context Rail 保存這些決策依賴的身分與政策資料，Artifact Path 對回實際執行版本，Evidence Path 則保留事後查詢與 Audit 所需的紀錄。產品名稱是目前的實作選擇，架構審查真正要看的仍是誰能決定、實際跑了什麼，以及事後查得到什麼。

![一筆 action 由 Human 或 M2M caller 經 agentgateway、Google ADK Runtime 到 Tool 或 Resource Server。Context 隨 action 傳遞。下方兩張卡片分別說明 Git／OCI Artifact provenance，以及 Alloy／LGTM 與 Governance Event 的 evidence 路徑。kagent、Agent Registry 是條件式選項，Audit 保存與防竄改仍待獨立驗證。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-22-r2/assets/diagrams/day-30/reference-architecture.png)

## Request Path：Identity、Gateway 與 Resource Authorization

Human 與 M2M 先走各自的 OAuth flow，從 Cognito 取得 Token，再把 Token 帶進 request。Cognito 完成 token issuance 後就退出資料面，業務流量不必穿過 IdP。Keycloak 的 federated login、角色 claim 與 Tool RBAC 曾經跑通，但當時組織還沒有足夠共識與人力維護一套完整 Identity Center，因此目前先用 Cognito 承擔需要的 Human／M2M 路徑。等 onboarding、offboarding、SaaS 入口與更多下游服務需要統一時，才有理由重開這個決策。

帶著 Token 的 request 可以經過既有 Ingress，但那一層只保留成 optional pass-through edge。agentgateway 才是跨 Runtime 共用的 checkpoint，負責驗 issuer、audience、signature、route、rate limit 與最低共同 policy，也產生 gateway request ID、policy version 和 decision。它可以拒絕不符合共同規則的流量，卻不知道某張工單是否真的允許刪除指定資料庫。

Google ADK Runtime 接手 workflow、state、Tool schema、argument normalization、delegation 與 pause／resume。真正有副作用的 Tool／Resource Server 仍保留最後授權：它要看受信任 principal、current actor、目標 resource 與 normalized arguments，再依自己的 business rule 決定是否執行並回傳 effect receipt。Gateway 已經回 `ALLOW`，不代表任何 Tool 參數都合理。

### Context Rail：Principal、Policy、Artifact 與 Approval

Gateway 從驗過的 JWT 加入 principal／client 與 policy decision。Runtime 再加入 delegation、Tool、resource、normalized arguments、Artifact digest 和必要的 approval digest，Resource Server 最後補 effect receipt。Action ID 與 trace ID 負責 correlation，已產生的欄位繼續往下游傳，但每個值都要保留自己的 evidence source。JSON 裡出現一個欄位，不等於事故調查時就能相信它。

高風險 action 若需要人工批准，Runtime 可以提供 pause／resume，平台可以提供 UI 與傳遞機制，Business Owner 則必須在完整 action context 下決定。一次批准要綁住 Tool、目標 resource 與參數摘要，並記下 approver、Artifact digest、policy version 與 expiry。任一內容改變，原本的批准就不能繼續使用。Day 18 跑通的是 pause／resume，包括 BYO Agent 的有限路徑。它沒有證明 approver 身分與授權，也沒有涵蓋所有跨 A2A／HITL 的 context 傳遞。這些不能因為畫面上有個「Approve」按鈕就算完成。

## Artifact Path：Desired State 與 Runtime Digest

我在 Day 19 評估 Agent Registry `0.3.3` 時，原本期待 catalog、版本與部署狀態可以一起成為 provenance control plane。實際部署、讀 source 再拆除後，留下來的問題是 source of truth 與 promotion ownership。`0.4.0` 後來重作成 declarative control plane，補上了部分舊缺口，但 catalog entry 仍不能單獨證明某個 Pod 實際跑的是哪份程式。

圖上選擇讓 Git／OCI 產生 immutable digest，經 promotion／admission 後交給 Kubernetes Runtime。Governance Event 應記錄實際 digest，而非 mutable tag、顯示名稱或 catalog entry。這是我們希望建立的 provenance 路徑，本系列沒有證明正式環境的 admission，也還不能把 digest 綁回每個 workload instance。kagent 與 Agent Registry 可以在需要宣告式部署、跨團隊 discovery 或集中 UI 時重新評估，卻不能代替這段證據。

控制面說明「應該部署什麼」，執行中的 workload 則要證明「這次實際跑了什麼」。兩條路徑靠 Artifact digest 會合，事故發生後才不會只剩 deployment 宣告。

## Evidence Path：Operational Telemetry 與 Audit Integrity

既有 LGTM 是我們日常查 Log、Metric 與 Trace 的地方。Day 26 的公開 Lab 另跑了一筆新 action：Tempo 看得到跨服務路徑，Loki 查得到帶相同 action ID 的事件，Prometheus 則回答聚合數據。這筆新紀錄證明現行觀測路徑能查回什麼，不能拿來補 Day 1 當時沒留下的資料。

Audit evidence 有不同的保存目的。Governance Event 可以沿用相同 schema 與 correlation ID，但誰能讀、誰能刪、要保存多久，以及怎麼證明紀錄沒有被改過，都得另外決定。這次只驗證資料能被查回，沒有驗證防竄改保存。架構圖直接寫出這個界線，沒有把 Loki 留得夠久當成 Audit 已完成。

Day 1 的 trace ID 只能串起當時保存的本機事件，不能證明那串 ID 曾進過 Tempo 或 Loki。能沿線索查到紀錄，和能用它證明誰准許了動作，是兩個不同問題。

## 回到 Day 1 的 Tool Call

[去年寫 LLM Observability](https://ithelp.ithome.com.tw/articles/10380029) 時，我在意的是模型為什麼這樣回答、一次呼叫花了多少錢，以及 Prompt、Response、Token、Latency 能不能沿 trace 找回來。今年把 Agent 接上 Tool 後，問題往前移了一步：誰讓它做、它代表誰、跑的是哪份程式、哪一層有權拒絕，以及事後拿什麼證明。

回到開頭的 `delete_demo_database`。Day 3 已經讓我看到一件實際的事：同樣是模型提出危險 Tool，執行前的 allowlist 可以拒絕，Agent 也不一定因此失去完成調查的能力。但那個小小的成功，還答不出「誰准許這次操作」「實際跑的是哪個版本」「改動是否真的發生」。這三十天的其餘工作，就是把這些問題放到能作決定、能留下證據的地方。

這三十天做過 Identity、Gateway 和 Agent control plane 的取捨。有些方案跑通了，最後仍因為維運成本與責任邊界沒有留下。產品可以隨組織條件更換。決策邊界、交接資料與證據來源則不能跟著消失。

這張圖沒有宣告所有控制都已上線。我現在看 Agent 架構，會先問那筆 Tool Call 怎麼走到 Resource Server。如果只能拿出一張正常的 trace，卻說不清它代表誰、哪條規則放行、實際改了什麼，我不會因為圖上的產品都齊了就讓它碰 production。Day 1 的 no-op canary 到這裡總算有了用處：它讓我們在沒有真的刪掉資料之前，把這條責任鏈問完。

# Day 27｜Agent Governance 產品地圖：從一次查詢看請求、交付與觀測

要讓一支 SRE Agent 查 Loki，會用到身分驗證、Agent Runtime、工具介面、資料來源和觀測平台。這些系統都可能出現在架構圖裡，但光把產品名稱連成一排，還看不出誰決定查詢、誰持有資料權限，以及 Agent 的版本從哪裡來。

可以先想一筆具體請求：值班者登入後，請 Agent 找某個服務最近的錯誤。Agent 呼叫 Grafana MCP，取得 Log 和 Trace ID，再整理調查線索。與此同時，另一位工程師可能正在發布 Agent 新版本。這兩件事都和 Agent 有關，經過的路徑卻不同。

本篇把這些工作分回請求、交付與觀測三條路。讀者可以先找到自己已經有的系統，再看哪個接縫缺少負責人。產品選擇會隨環境改變，請求和資料各由誰處理，則應該始終說得清楚。

## 同一支 Agent 的三條路

請求路徑發生在使用者要 Agent 做事時。身分系統先發憑證，入口驗證後送到 Runtime。Runtime 決定工具與參數，MCP Server 再以被授予的資料權限查詢後端，結果沿原路返回。

交付路徑發生在程式或設定變更時。工程師修改 Repository，經 Review、建置和映像發布，再由部署系統啟動選定版本。若有跨團隊上架需求，Registry 可以提供目錄與部署宣告，kagent 則可以承接部分 Kubernetes 部署和發現工作。

觀測路徑由執行元件送出資料。Gateway 記流量與入口判斷，Runtime 記工作步驟，工具端記結果，再交給既有收集器和後端。這些訊號讓值班者能查同一筆操作，而不必靠各團隊口頭拼接。

下圖先看中央的一筆請求，再看旁邊的交付和觀測支線。Registry 管理的部署資訊不在每次 Loki 查詢的資料路徑裡，也不會替這次工具呼叫作授權決定。

![Agent 查詢的請求路徑，另有目錄、部署與觀測資料支線。各系統位於不同工作位置。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27-r6/assets/diagrams/day-27/capability-ledger-method.png)

## 身分系統與人員生命週期

使用者能登入，是這條路的起點。真正維護身分還包含加入團隊、角色異動、停權與憑證更新。例如人員離開後，哪些 Client 或下游入口還能使用？角色改變時，Gateway 接受的 Claim 是否同步？這些工作會決定身分系統長期需要哪些維護者。

我們目前由 AWS Cognito 提供 Human 和 M2M 兩種入口。Human 透過互動登入取得憑證，M2M 則讓服務以 Client 身分取得 Token。兩者的使用者、生命週期和停權方式不同，不能只因為都回 JWT 就用同一份管理流程。

Keycloak 當初也跑通了登入、JWT Role 和 Gateway 的工具權限檢查。最後沒有把它擴成企業 Identity Center，是因為 IT 團隊尚未形成承接到職、異動、離職與下游 SaaS 整合的共識和人力。PoC 可以確認技術可行，接下來的組織工作仍要有人持續做。

若環境已有成熟的 Keycloak 或其他 IdP，先沿用既有身分和人員管理通常比較容易接上。還要區分 Caller 與執行工作負載：Client Credentials 識別服務 Client，不會只靠同一枚 Token 告訴你是哪個 Pod 送出請求。是否需要進一步的工作負載驗證，取決於下游授權和調查需求。

## 共同入口如何接走重複工作

當多個 Runtime 都要呼叫 LLM、MCP 或其他 Agent，可能各自保存 Provider Key、實作入口 JWT 檢查、設定等待與重試，再產生不同觀測欄位。起初每個應用都能工作，規則變更時卻要逐一找人，事故也難從共同位置確認請求如何被處理。

agentgateway 的位置是跨 Runtime 的共同流量入口。它可以接手已定義的認證、路由、政策和流量觀測，讓平台團隊維護這些共用規則。Runtime 仍保留自己的工作流程，工具服務仍決定資料範圍和目標資源授權。

既有 Ingress 也可以留在外層，處理 TLS 和 Host Routing。這兩層要說清楚誰處理哪些功能，避免兩邊各自改 Header、重試或設定串流等待。單一唯讀 Agent 若沒有共同入口需求，也可以先由應用使用現有機制完成這些工作。

LiteLLM 曾是我們的候選。當時考慮的除了 Provider 支援，也包括 Kubernetes 交付、身分對應、GitOps 變更，以及額外元件由誰維護。這些條件影響日後每次升級和故障處理，比功能表多一個勾更能說明我們的選擇。後來的供應鏈事件又增加升級來源的考量，時間上與最初選型分開。

## Runtime 與部署平台的分工

Runtime 決定 Agent 怎麼完成工作，例如保存狀態、安排工具、處理失敗和暫停等待批准。這些能力對應應用的語意：調查 Agent 要保留哪些線索，修改 Agent 要驗證哪些參數，都需要應用團隊設計。

Google ADK 是本系列的 Runtime 框架。[kagent](https://github.com/kagent-dev/website/blob/c053e7cb66ec14b6c8767f38042451b33612accc/docs-site/content/kagent/0.x/concepts/architecture.md) 則提供 Kubernetes 上的 Agent 部署與操作入口，宣告式 Agent 路徑會使用其封裝的 Runtime。兩者可以搭配，也可以把自建 ADK Agent 以 BYO 方式接進 kagent，再驗證可使用的平台能力。

我評估 kagent 0.9.9 時，需求包含進階模型參數與自訂流程，當時宣告式介面不足以完整表達，所以保留自建 Runtime。後續 0.10.0／0.10.1 的 Lab 又確認部署、發現、Agent-as-Tool，以及相容 BYO 路徑的部分 Pause／Resume 能工作。這些結果讓平台位置更清楚，仍沒有替 BYO 作者維護所有 Callback、記憶體、工具政策與框架升級。

因此要分別問兩個問題：誰維護這支 Agent 的邏輯，誰讓它部署、被找到與被呼叫？若兩件事目前都由單一應用團隊穩定處理，未必需要立刻新增平台。若多個團隊都在重複部署、註冊 Agent Card 和提供操作入口，才有共用控制面的工作可以交接。

## Registry 的目錄與部署宣告

當 Agent 數量與團隊增加，「去哪裡找可用的 Agent」會成為另一個問題。[Agent Registry](https://aregistry.ai/docs/about/architecture/) 可以集中保存目錄資訊與部署宣告，讓使用者找到候選版本，再交由控制器處理期望狀態。本系列 Day 19 用 0.4.0 實測這條 reconciliation 路徑，也就是持續讓部署結果符合宣告。

這類目錄帶來便利，同時新增可修改的狀態來源。若 Git 和 Registry 都能改部署宣告，就要決定誰具有最終修改權，以及兩邊不同時怎麼處理。若 Catalog 的 `approved` Tag 可以改指向別的映像，也還需要批准紀錄與內容 Digest，才能知道這次部署的是哪一份產物。

目錄資訊是發現與交付的一部分。某支 Agent 被上架，不代表它對所有工具參數都有權執行。例如被核准的查詢 Agent 臨時提出刪除資料，工具端仍需按當次目標和參數授權。交付批准與執行批准不能只靠一個 Catalog 標籤合併。

我們評估後沒有把 Registry 留作正式平台，是因為它還要配合既有 Git 交付與權限責任。若你的環境已有跨團隊目錄需求，就值得重新驗證這些接縫。若仍是少數應用，由 README 和既有交付流程就能管理，也可以先停在那裡。

## 交付歷史與執行歷史如何相接

程式的 PR、Commit 和映像建置紀錄，說明某個版本如何被發布。使用者在某個時間請 Agent 查 Loki，則是執行歷史，需要 Gateway、Runtime 和工具端的紀錄。Git 不會自動記下這次請求使用了哪個工具，Trace 也不會自動知道映像由誰批准。

兩邊可以透過實際執行的 Artifact Digest 核對。Digest 是內容摘要，和可被移動的 Tag 不同。若執行事件記下這次映像的 Digest，就能回到交付紀錄找相同產物，再檢查它的程式與設定。

這個關聯需要由執行端確實記錄。只知道 Deployment 曾宣告某個版本，仍可能遇到 [滾動更新中的新舊 Pod](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)，不能直接推論每筆請求都用最新版本。下圖的虛線就是需要核對的關聯，並非本系列已驗證完整交付與每筆執行的綁定。

![Git PR、映像和 Deployment 留下交付歷史，Caller、Agent 操作與工具結果留下執行歷史。兩邊需要實際 Artifact Digest 才能核對。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27-r6/assets/diagrams/day-27/two-histories.png)

Alloy 和 LGTM 是我們既有的觀測核心，分別收集和查詢 Logs、Metrics、Traces。延伸到 Agent 後，先讓入口判斷、工作步驟和工具結果能沿同一筆操作查回。若另外有保存期限或防刪改要求，再按要求檢查現有機制是否足夠。

## 把產品位置換成自己的系統

帶回自己的環境時，可以先畫一筆查詢。標出登入來源、請求入口、Runtime、工具端與資料來源，再另畫程式如何交付、事件送到哪裡。每個位置填現有系統和維護者，缺口就會比功能清單明確。

例如查詢失敗，需要知道是入口拒絕、工具端權限不足，還是資料來源沒有符合事件。部署版本對不上，則回到交付和執行產物的關聯。這些問題各有接手人，不能全部寫成「平台負責」。

[Agent Governance Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-27-r6/articles/day-27/capability-ledger.md) 和 [CSV 版本](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-27-r6/articles/day-27/capability-ledger.csv) 提供可填寫的盤點表。它們幫讀者把位置、維護者和待確認接縫寫下來，沒有要求把圖上的產品全部裝齊。

產品地圖回答了工作放在哪裡，下一步才是安排導入順序。只讀資料、共用多個 Runtime，以及開始修改正式資源，會有不同的優先事項，下一篇按這三種情境來選擇。

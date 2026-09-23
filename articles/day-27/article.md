# Day 27｜Agent Governance 產品地圖：一條請求會經過哪些系統

讀到這裡，Cognito、agentgateway、kagent、Agent Registry 和 LGTM 都登場了。如果現在有團隊要讓一支 Agent 查 Loki，該從哪個產品開始裝？光看功能清單，很容易得到一張每格都打勾、卻說不清請求怎麼走的架構圖。

我自己也走過這段路。評估 Identity 時，Keycloak 的技術鏈跑得通，最後卻選了 Cognito；看 Gateway 時，LiteLLM 有豐富的 LLM 功能，我們更在意 Kubernetes 上共同流量入口的維運方式；Agent Registry 已經能把 Agent 部署到 kagent，也不代表每個團隊都需要再多一個 Catalog。這些不是產品高下的排名，而是它們站在不同位置，接走不同工作。

![一筆 Agent 請求經過身分、共同流量入口、Agent Runtime 與資源服務，旁邊另有發布目錄及觀測資料路徑。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-18-r2/assets/diagrams/day-27/capability-ledger-method.png)

## 一筆查詢，先分清兩條路

假設值班同仁請 SRE Agent 查詢一段 Loki Log。使用者的登入資訊先由身分系統發給應用，請求到共同入口後，Gateway 驗證憑證、選路由、套用共用政策。Agent Runtime 決定要不要呼叫 Grafana MCP，MCP Server 再以自己被授予的範圍查 Loki。回應沿原路返回，過程中的 Log 與 Trace 進入既有觀測平台。

另一條是交付路徑。有人修改 Agent 的程式或設定，經 Git 與映像流程發布，必要時再上架 Agent Registry、交給 kagent 部署。Registry 管「可找到哪份 Agent、要部署哪份」，不在每一筆 Loki 查詢的資料路徑上。這兩條路若畫成一條，常會誤以為 Catalog 的 `approved` 標籤可以替每次 Tool Call 授權。

這個例子裡有兩個權限檢查也不能混在一起：Gateway 可以判斷這個請求能不能進到 Agent 或 MCP，Loki 查詢帳號能看哪些資料，仍由 Grafana／Loki 那端的權限決定。若 Agent 從「查 Log」改成「刪除資料」，Tool 所連的資源服務還得判斷目標資源與參數。Gateway 不知道工單的業務規則，光有一張 Token 也不會知道。

## 身分入口與人員生命週期

在我們的環境裡，Human 與 M2M 都需要穩定取得 Token，因此現在由 Cognito 提供這兩條入口。Keycloak 當初也跑通登入、JWT Role 和 Gateway 的 Tool 權限檢查；問題是要不要為了幾個 AI 服務，另起一套需要自己維護的企業 Identity Center。當時 IT 團隊還沒有足夠共識與人力，把人員的到職、異動、離職，以及下游 SaaS 入口一起接進來。技術能跑，組織卻還沒有要接的整段工作。

若組織本來就有成熟的 Keycloak 與 Identity 團隊，沿用它很合理；若已經有其他 IdP，也未必需要為 Agent 再建一套。先釐清 Human、Service 和實際執行的 Workload 分別由誰識別。Client Credentials 認得的是 Client，不能直接當成 Pod 身分。後面要追查一筆動作時，這個差別會影響能否找到真正的執行者。

## 共同流量入口：agentgateway 接走重複的規則

我們把 agentgateway 放在 LLM、MCP、A2A 流量的共同入口。多個 Agent 各自保管 Provider Credential、寫 JWT 檢查、做 Timeout 和 Retry，又各自送一套觀測欄位時，事故很難從同一個地方看全。共同入口的價值，是把這些跨應用規則收在一處，而不是把 Agent 的工作流程搬進 Gateway。

所以既有 Ingress 不必被替換。它可以繼續處理對外 TLS、Host Routing 等既有工作，AI 流量再由 agentgateway 接手。單一、小型的唯讀 Agent 也未必需要新增 Gateway；等多個 Runtime 的規則開始分岔，共同入口的收益才會明顯。

LiteLLM 曾是我們的候選方案。當時考慮的不只它支援多少 Provider，也包括 Kubernetes 交付、身分對應、升級和額外元件誰來維護。後來的供應鏈事件讓我更在意這類中介層的升級來源，但不能倒過來說那是當年選型的起因。產品比較若只列 Feature，這些長期成本很容易從表格裡消失。

## Agent 自己做事，與平台幫它上架

Agent Runtime 仍是應用團隊寫決策邏輯的地方。Google ADK 的 Tool、Callback、狀態與工作流程，要由熟悉應用的人設計和測試。kagent 可以協助在 Kubernetes 部署 Agent，提供發現、A2A 與部分平台操作，但它目前露出的 Runtime 設定，不足以替代我們自建 Agent 所需的進階參數和流程。BYO Agent 接上 kagent，讓其他 Agent 比較容易找到它，並不會自動改進它的內部邏輯。

Agent Registry 又是另一層。Day 19 的新版實跑顯示，它可以保存 Agent 資訊、接收部署宣告，並讓 Controller 把 Agent 交給 kagent。對需要跨團隊搜尋、上架和管理版本的人，這很有用。只是 Catalog 裡一個名為 `approved` 的 Tag 仍可能改指向別的 Image；「容易找到」和「這份程式經誰批准、實際跑的是哪個 Digest」是兩件事。若組織仍以 Git 和映像流程交付，導入 Registry 前得先說好哪裡可以改部署宣告。

我會先看團隊是否真有跨團隊上架的痛點，而不是因為已有 kagent，就順手把 Registry 一起裝上。反過來說，若已經有大量 Agent、MCP Server 和 Skill 需要集中查找，單靠散落的 README 也會越來越難維護。

## GitOps 變更紀錄與 Agent 執行紀錄

Alloy 與 LGTM 是我們原有的 Production 核心。Agent 接進來後，Gateway 可以帶出驗證後的 Caller 資訊，Runtime 記錄 Agent 與 Tool，MCP 或後端留下操作結果；Trace、Log 與 Metrics 才能拼出「哪個請求走到哪裡」。這是 Day 20–26 一路延伸的觀測能力，不必為了 Agent 另造一套 Dashboard 平台。

Agent 的設定和映像若透過 IaC／GitOps 交付，Pull Request、Commit 與部署版本已經留下變更歷史。值班同仁請 Agent 查 Loki 的那一刻，則不是一次 Git 變更；這筆呼叫由誰發起、用了哪個 Tool、查詢結果如何，要回到 Gateway、Runtime、MCP 與 LGTM 的執行紀錄。兩條路合起來，通常比再加一套「Agent 專用稽核儲存」更能回答日常維運問題。

`user_id` 若只是應用自己塞進 Header，和 Gateway 從已驗證 JWT 取出的 Claim，查詢畫面可能長得一樣，可信程度卻不同。架構圖至少要標出欄位在哪一站產生；至於紀錄是否另有長期保存或防刪改要求，等組織真的提出這類要求，再檢查現有 Git 與 Log 是否足夠。

## 這張地圖怎麼帶回自己的環境

從一筆真實請求開始畫，通常比從產品清單開始選容易。先找使用者如何登入、請求在哪裡轉送、Agent 由誰維護、Tool 用什麼身分接觸資料，最後確認出事時去哪裡查。若有某段已經由現有系統穩定承擔，就不必為了湊齊這張圖重做一遍。

我把這些接縫整理成可自行填寫的 [Agent Governance Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r2/articles/day-27/capability-ledger.md)，也附上 [CSV 版本](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r2/articles/day-27/capability-ledger.csv)。從 Day 19 的 Registry 畫面、Day 23–25 的 Gateway 與 LGTM 實跑，讀者可以挑自己最不熟的那段往回看。盤點表只幫忙把每一段由誰提供、誰維護、下一個疑問寫清楚，實際選擇還是由自己的環境決定。

位置看清楚後，還有一個問題：若只做唯讀查詢、若開始共用多個 Agent、若 Tool 要修改正式環境，這些系統應該按什麼順序導入？Day 28 會用這三種情境回答。它不會要求每個團隊都走向同一個終點。

# Day 19｜也許你需要的是 Agent Registry：Agent 發現、版本管理與供應鏈信任

Day 18 的 BYO Agent 已能被 kagent 部署、找到，也能讓另一個 Agent 透過 A2A 呼叫。團隊開始累積更多 Agent 後，下一個問題很快就會浮現：Catalog 裡的 `approved` 到底是誰批准的，那個 Tag 明天是否仍指向同一份 Image？

這不是我第一次評估 Agent Registry。我曾把 `0.3.3` 部署到 Kubernetes，讀過 Source，也真的把它拆掉。當時卡住的不是 UI 好不好用，而是 Desired State、Authorization 與既有 GitOps 流程接不起來。現在的 `0.4.0` 已經大幅重作，如果只拿舊印象批評新版，對專案並不公平。

這次不做新舊版本功能 PK。歷史經驗只用來列出採用門檻，公開 Lab 則測 `0.4.0` 的現況：先註冊帶有 `approved` Tag 的 Agent，讓 Controller 將它部署到 kagent，再修改相同 Tag 指向的 Image Reference，觀察 Catalog、Runtime 與信任鏈各自發生什麼事。

## Registry 補上平台缺少的 Artifact Catalog

Agent、MCP Server、Model 與 Skill 散在不同 Repository 和 Cluster 後，使用者需要一個地方搜尋版本、閱讀 Metadata，再把選到的 Artifact 交給 Runtime。只靠 README、Slack 訊息和人工清單，半年後通常沒有人能確定哪個版本仍可使用。

這個位置正好落在我們既有架構的空白處。kagent 能部署與發現 Agent，agentgateway 能治理執行流量，兩者都不會替組織維護完整的 Artifact Catalog。Agent Registry 的價值不只是多一個漂亮 UI，而是可能成為發布、搜尋與 Deployment Reconciliation 的 Control Plane。

問題也因此更嚴肅。Catalog 一旦能決定某個 Agent 進入哪個 Runtime，它保存的就不只是描述文字，而是會影響實際 Workload 的 Desired State。

## 0.3.3 卡在 State Ownership 與 Authorization

我們原本以 Git 裡的設定和環境分支作為 Review 入口，Kubernetes 與 Terraform 變更也沿同一條路徑交付。`0.3.3` 將 Registry State 放在 PostgreSQL，操作經 REST API 進入。對我們而言，Git 之外又出現一份會影響 Runtime 的 Desired State。事故發生時，究竟該相信 Pull Request、Registry Database，還是 Cluster 正在跑的 Resource，沒有明確答案。

授權是另一個障礙。Catalog 若只供閱讀，權限寬鬆的代價還有限。當它能 Create、Update、Promote 與 Deploy Agent，這些操作就必須接上組織 Principal、Role、Approval 與 Audit。當時的 OSS 能力沒有達到我們需要的細緻程度，團隊也不想再維護另一套 Mapping 和同步邏輯。

回頭重讀鎖在 [`v0.3.3`](https://github.com/agentregistry-dev/agentregistry/tree/v0.3.3) 的 Source 後，我也收回兩個早期批評。第一，產品當時並非只能靠 UI 操作，CLI 與 API 早已存在。第二，我沒有完成 agentgateway Compatibility Test，不能把自己的整合未完成寫成 Upstream 壞掉。真正支撐拆除決策的，仍是 State Ownership、Reconciliation 與 Authorization 是否符合我們的 Operating Model。

## 0.4.0 已經補上 Declarative Reconciliation

[`0.4.0` Release Notes](https://github.com/agentregistry-dev/agentregistry/releases/tag/v0.4.0) 將這次改版稱為 Breaking Rewrite，`0.3.x` 不能原地升級。新版以 `ar.dev/v1alpha1` 的 Kubernetes-style Manifest 表達 Agent、Runtime 與 Deployment，再由 Controller 持續 Reconcile Deployment Status、Runtime Resource 與 Teardown。

Kubernetes-style 很容易被誤讀成 CRD。[API Package](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/pkg/api/v1alpha1/doc.go) 將這些 Type 定義為 Wire、Storage 與 API Contract，Spec／Status 仍寫入 PostgreSQL。當 `Deployment` 指向 Kubernetes Runtime 時，Controller 才把 Registry 裡的 Desired State 轉成 kagent Resource。

![Agent Registry 0.4.0 的 Catalog 與 Deployment controller 邊界。Author 或 CI 經 API 寫入 PostgreSQL 內的 Agent、Runtime 與 Deployment，controller 再把 Deployment materialize 成 kagent Agent。下方另列出本次已驗證的 catalog、reconciliation、image reference 更新與 undeploy，以及 Registry 本身不會自動補上的 authentication、Git promotion、簽章和 runtime policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-22-r2/assets/diagrams/day-19/registry-reconciliation-trust-boundary.png)

新版確實補上我當年缺少的 Declarative Reconciliation。Manifest 長得像 Kubernetes YAML，Git 卻不會因此自動成為 Source of Truth，`approved` 也不會直接變成經過簽章且不可變的 Promotion 結果。這兩層差異正是本次 Lab 要驗證的地方。

## 相同 Approved Tag 可以原地換 Image

公開 Lab 建立獨立 Kind Cluster，安裝 Agent Registry `0.4.0` 與 kagent `0.10.1`。前面不再疊 Gateway，也不為了講 GitOps 硬塞 Argo CD。這次只驗 Catalog 到 Runtime 的 Lifecycle。

第一份 Manifest 註冊 `day19byo@approved`，Image Reference 是 `ithelp/day19-byo:1.0.0`。Deployment 使用相同 Name 與 Tag 指向它，再交給 kagent Runtime。啟動後，UI 能查到這筆 Agent，也能看到它進入 Deployment Path。

![Agent Registry 0.4.0 實際 UI。Agents 頁面顯示 day19byo，tag 為 approved，描述已更新成相同 catalog tag 指向另一個 image reference。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-22-r2/assets/screenshots/day-19/01-agent-registry-catalog.png)

Probe 接著對相同的 `day19byo@approved` 再 Apply 一次，只把 Image Reference 改成 `ithelp/day19-byo:1.0.1`。Registry 接受變更，既有 Deployment 被重新 Reconcile，kagent Agent 也跟著換成新的 Reference。

站在 Controller 功能的角度，這是成功。它證明 Target 變更會持續進入 Runtime。站在 Provenance 的角度，相同 `approved` 能原地換內容，就是必須另外處理的風險。兩個本機 Tag 在 Lab 中指向同一份測試 Image，因此這裡只證明 Reference Mutability 與 Reconciliation，沒有拿兩份不同程式冒充 Supply-chain Attack。要驗 Artifact Bytes，仍需要 Immutable Digest、Signature 與 Attestation。

## 匿名寫入讓綠色 Reconciliation 失去信任

Probe 沒帶 Credential 便呼叫 `POST /v0/apply`，預設 OSS 安裝接受了寫入。這和專案的 [Security Self-assessment](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/docs/governance/cncf/security-self-assessment.md) 一致。預設設定是 Permissive，不能直接當成 Authenticated Security Boundary。整合者必須透過 AuthnProvider 與 AuthzProvider 接上可信身分和 Resource Authorization。

Lab 把結果分成三個正常能力與兩個已暴露風險：

| 觀察 | 結果 | 解讀 |
| --- | --- | --- |
| Tagged Agent 可讀取 | PASS | Catalog 能保存並搜尋 Agent Metadata |
| Deployment 進入 kagent | PASS | Controller 能把 Desired State Materialize 到 Runtime |
| Declarative Undeploy | PASS | Teardown 仍沿同一條 Control Path |
| Anonymous Catalog Write | RISK_EXPOSED | 預設安裝不是 Production Authorization Baseline |
| 相同 `approved` Tag 更換 Image | RISK_EXPOSED | Tag 本身不是 Immutable Promotion Evidence |

![Day 19 實際 Lab 輸出的 terminal card。Catalog 讀取、部署到 kagent 與 declarative undeploy 通過。匿名寫入及相同 approved tag 更換 image reference 被列為 RISK_EXPOSED。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-22-r2/assets/screenshots/day-19/03-agent-registry-boundary-results.png)

`RISK_EXPOSED` 不是測試壞掉。它表示 Lab 成功重現了不應被 `PASS` 掩蓋的採用風險。若只看 Controller Status 全綠，很容易把 Reconciliation 正常誤讀成信任鏈完整。

最後一次 Apply 將 `Deployment.spec.desiredState` 改成 `undeployed`。kagent 中由 Registry 管理的 Agent 隨即移除，Registry UI 則保留 Catalog 與 Deployment Record。這比直接 Delete 更適合平台操作，因為 Desired State、Status 與 Runtime Teardown 仍走同一條控制路徑。

![Agent Registry 0.4.0 實際 Deployed 頁面。完成 declarative undeploy 後，頁面顯示 0 resources running，同時保留 day19byo 的 deployment record。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-22-r2/assets/screenshots/day-19/02-agent-registry-deployed.png)

## 採用條件不能只看 Controller 功能

[Lab 03 的 Day 19 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-22-r2/labs/03-gateway-runtime/README.md) 可以用一條命令重跑 Catalog Apply、Deployment、相同 Tag 更新與 Undeploy：

```bash
make lab-03-runtime-registry
```

重跑後，有些舊印象必須正式修正。`0.4.0` 的 Catalog、Kubernetes-style API、Controller Status 與 Undeploy 已經形成完整的 Declarative Path，不能再說 Agent Registry 只展示 Metadata。組織若缺少跨團隊的 Agent／MCP Catalog，也願意讓它成為正式 Control Plane，新版的價值比 `0.3.3` 時清楚很多。

授權與 Artifact Trust 則尚未自動完成。我把結果整理成 [Agent Registry 採用盤點表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-22-r2/articles/day-19/registry-adoption-checklist.md)，正文留下六個選型問題：

| 採用問題 | 本次結果 | 還缺什麼 |
| --- | --- | --- |
| 使用者能否找到帶版本／Tag 的 Agent | PASS | Catalog Owner 與 Metadata 品質規範 |
| Desired State 能否部署並 Teardown | PASS | Production Runtime RBAC、復原與 SLO |
| `approved` 是否代表 Immutable Artifact | RISK_EXPOSED | Digest、Signature、Attestation、Promotion Policy |
| 預設安裝能否限制 Catalog Writer | RISK_EXPOSED | AuthnProvider、AuthzProvider、Role Mapping、Audit |
| Registry 與 Git 誰是最終權威 | ORGANIZATIONAL | Write Path、Review Owner 與 Drift 處理 |
| Runtime Traffic 是否已授權 | OUT_OF_SCOPE | Gateway／Runtime Policy 與可信 Identity Context |

如果今天重新選型，我不會再用「缺少 Reconciliation」否決 `0.4.0`。我仍不會立刻把它放進既有平台，理由也變得更精確。在組織決定誰擁有 Artifact Promotion、Registry 與 Git 如何分工，以及預設 Permissive Authorization 如何補齊以前，多一個 Control Plane 就多一份需要值班與稽核的狀態。

需要 Self-service Catalog，而且願意正式維護 Provider、Database、Promotion 與 Reconciliation 的團隊，已經有充分理由評估 Agent Registry。對我們而言，先把 Ownership 與信任鏈談清楚，比先把服務裝上去更重要。

## Registry 無法還原一次 Agent 行動

Agent Registry 可以告訴平台某個 Agent 是誰、目前標成什麼版本，以及 Deployment 是否已經 Reconcile。當 Agent 實際被某個 Principal 呼叫，Registry 裡的資料仍不足以還原誰授權誰、套用哪版 Policy、Tool 最後改了什麼。

Day 20 會把視線轉向 Traceability，沿著一筆 Tool Call 把 Principal、Delegation、Artifact、Policy Decision 與執行結果串回來。Catalog 告訴我們可能執行的是哪個 Agent，真正的責任鏈仍要由執行當下的資料回答。

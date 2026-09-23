# Day 19｜也許你需要的是 Agent Registry：Agent 發現、版本管理與供應鏈信任

Day 18 的 BYO Agent 已能被 kagent 部署，也能讓另一個 Agent 透過 A2A 找到並呼叫。但當團隊開始上架更多 Agent，使用者要去哪裡找「目前可以用的版本」？平台又該從哪裡決定要部署哪一份？這正是 Agent Registry 想接手的工作：提供 Agent 等資產的目錄，保存上架資訊，再把選定的 Agent 交給 Runtime 部署。

這個方向很吸引人。我曾把 Agent Registry `0.3.3` 裝進 Kubernetes，讀過 Source，最後又拆掉。當時難處不是 UI 好不好用，而是 Registry 裡可修改的狀態，和我們原本以 Git 審查、交付的流程，究竟該由誰說了算。現在的 `0.4.0` 已大幅重作，我想重新回答兩個問題：它能否把上架到部署這段工作做好？做到了，我們是否就該把它放進現行平台？

公開 Lab 只測新版。它會上架一個標成 `approved` 的 Agent，交給 kagent 部署，再把相同名稱與 Tag 改指向另一個 Image Reference。讀者可以跟著看見部署如何更新，也能看見「可被找到」與「值得信任」之間還隔著什麼。

## 先認識 Agent Registry 的位置

![Agent Registry 官方 Logo。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/third-party/agentregistry/agentregistry-logo-dark.png)

[Agent Registry](https://aregistry.ai/docs/about/architecture/) 是一個集中管理 Agent 相關資產的目錄與控制面。團隊可以把 Agent、MCP Server、Skill、Prompt 等資訊放在一起，讓其他人搜尋、選用，再把部署宣告送往 Runtime。[官方首頁的示意圖](https://aregistry.ai/) 也把「建立與發布」、「Catalog」、「部署」分成不同階段。這張圖很適合認識產品，但我們自己的問題還要再往前一步：請求真正來了以後，Registry 會不會經過那筆流量？

![Agent Registry 管上架目錄與部署宣告，實際請求則經 agentgateway、Agent Runtime 與 MCP／Resource Server。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/diagrams/day-19/registry-product-map.png)

圖裡的上下兩條路徑要分開看。上面是交付路徑：作者或 CI 發布資產，Registry 保存可搜尋的資訊與部署宣告，kagent 或 Kubernetes 接手執行。下面是使用路徑：使用者發出請求後，流量經過 Gateway、Agent 與 Tool 所連的資源服務，不會每次回頭問 Registry。這也說明它和 kagent、agentgateway 不是三選一。

## 目錄如何影響部署

Agent、MCP Server、Model 與 Skill 散在不同 Repository 和 Cluster 後，使用者需要一個地方搜尋版本、閱讀說明，再把選到的 Agent 交給 Runtime。只靠 README、Slack 訊息和人工清單，時間一久就難以確認哪個版本仍可使用。

這裡有三件相鄰但不同的工作。kagent 負責執行與讓 Agent 互相找到。agentgateway 管執行時經過的流量。Agent Registry 處理上架與部署宣告，讓團隊從目錄選 Agent，再把部署意圖交給 Runtime。

一旦 Registry 能決定哪個 Agent 進入 Runtime，目錄裡保存的就不只是介紹文字，而是會改變實際 Workload 的部署狀態。這也是我不敢只看搜尋介面就做採用決定的原因。

## 0.3.3 卡在 State Ownership 與 Authorization

我們原本以 Git 裡的設定和環境分支作為 Review 入口，Kubernetes 與 Terraform 變更也沿同一條路徑交付。`0.3.3` 將 Registry State 放在 PostgreSQL，操作經 REST API 進入。對我們而言，Git 之外又出現一份會影響 Runtime 的 Desired State。事故發生時，究竟該相信 Pull Request、Registry Database，還是 Cluster 正在跑的 Resource，沒有明確答案。

授權是另一個障礙。Catalog 若只供閱讀，權限寬鬆的代價還有限。當它能 Create、Update、Promote 與 Deploy Agent，這些操作就必須接上組織 Principal、Role、Approval 與 Audit。當時的 OSS 能力沒有達到我們需要的細緻程度，團隊也不想再維護另一套 Mapping 和同步邏輯。

回頭重讀鎖在 [`v0.3.3`](https://github.com/agentregistry-dev/agentregistry/tree/v0.3.3) 的 Source 後，我也修正了兩個早期印象：當時已有 CLI 與 API，並非只能靠 UI 操作。我也沒有完成 agentgateway 的 Compatibility Test，不能把尚未整合成功歸因為產品故障。拆除它的主要理由，仍是我們沒有替這份狀態和寫入權限找到合適的長期 Owner。

## 0.4.0 已經補上 Declarative Reconciliation

[`0.4.0` Release Notes](https://github.com/agentregistry-dev/agentregistry/releases/tag/v0.4.0) 將這次改版稱為 Breaking Rewrite，`0.3.x` 不能原地升級。新版以 `ar.dev/v1alpha1` 的 Kubernetes-style Manifest 表達 Agent、Runtime 與 Deployment，再由 Controller 持續 Reconcile Deployment Status、Runtime Resource 與 Teardown。

Kubernetes-style 很容易被誤讀成 CRD。[API Package](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/pkg/api/v1alpha1/doc.go) 將這些 Type 定義為 Wire、Storage 與 API Contract，Spec／Status 仍寫入 PostgreSQL。當 `Deployment` 指向 Kubernetes Runtime 時，Controller 才把 Registry 裡的 Desired State 轉成 kagent Resource。

![Agent Registry 0.4.0 的 Catalog 與 Deployment controller 邊界。Author 或 CI 經 API 寫入 PostgreSQL 內的 Agent、Runtime 與 Deployment，controller 再把 Deployment materialize 成 kagent Agent。下方另列出本次已驗證的 catalog、reconciliation、image reference 更新與 undeploy，以及 Registry 本身不會自動補上的 authentication、Git promotion、簽章和 runtime policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/diagrams/day-19/registry-reconciliation-trust-boundary.png)

新版確實補上我當年缺少的 Declarative Reconciliation。Manifest 長得像 Kubernetes YAML，但 Apply 進 Registry 後，Git 不會因此自動變成唯一權威。`approved` 也只是可修改的目錄標籤，不是簽章或不可變的發布紀錄。這兩個差別決定了我們要怎麼讀接下來的實跑結果。

## 相同 Approved Tag 可以原地換 Image

公開 Lab 建立獨立 Kind Cluster，安裝 Agent Registry `0.4.0` 與 kagent `0.10.1`。前面不再疊 Gateway，也不為了講 GitOps 硬塞 Argo CD。這次只驗 Catalog 到 Runtime 的 Lifecycle。

第一份 Manifest 註冊 `day19byo@approved`，Image Reference 是 `ithelp/day19-byo:1.0.0`。Deployment 使用相同 Name 與 Tag 指向它，再交給 kagent Runtime。啟動後，UI 能查到這筆 Agent，也能看到它進入 Deployment Path。

![Agent Registry 0.4.0 實際 UI。Agents 頁面顯示 day19byo，tag 為 approved，描述已更新成相同 catalog tag 指向另一個 image reference。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/screenshots/day-19/01-agent-registry-catalog.png)

Probe 接著對相同的 `day19byo@approved` 再 Apply 一次，只把 Image Reference 改成 `ithelp/day19-byo:1.0.1`。Registry 接受變更，既有 Deployment 被重新 Reconcile，kagent Agent 也跟著換成新的 Reference。

Controller 正確地把新參照送進 Runtime，這正是 Registry 值得考慮的能力。讓我停下來的是另一件事：`approved` 不變，背後指向的 Image Reference 卻能換掉。Lab 的兩個本機 Tag 指向同一份測試 Image，所以這裡觀察到的是「參照可以變、部署會跟著變」，不是兩份不同程式造成的供應鏈事故。若要把批准和實際執行的程式綁在一起，還得加入不可變 Digest、批准紀錄，以及部署後的核對。

這裡容易混淆兩種「版本」。`approved` 是 Catalog 給人看的選擇，`ithelp/day19-byo:1.0.0` 也是可以重新指向其他內容的 Tag。兩者都不是內容本身的身分。讀者重跑 Lab 時，可以先看前後兩份 Manifest：Catalog 名稱與 Tag 不動，Image Reference 已從 `1.0.0` 換成 `1.0.1`。Controller 會忠實部署新參照，卻沒有一個地方要求它比對「這是否仍是當初批准的位元組」。

Day 18 的 [Pod Security 執行紀錄](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r3/assets/screenshots/day-18/evidence/pod-security.txt) 固定了 **基底映像** 的 Digest，那是比較靠近內容本身的識別。不過完整 Agent Image 還沒有從建置、批准、部署一路核對到實際執行。這條交付鏈要由現有 Git 與映像流程，或未來的 Registry 整合共同承擔。單獨在 Catalog 貼上 `approved`，無法替任何一方完成它。

## 匿名寫入讓綠色 Reconciliation 失去信任

Probe 沒帶 Credential 便呼叫 `POST /v0/apply`，預設 OSS 安裝接受了寫入。這和專案的 [Security Self-assessment](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/docs/governance/cncf/security-self-assessment.md) 一致。預設設定是 Permissive，不能直接當成 Authenticated Security Boundary。整合者必須透過 AuthnProvider 與 AuthzProvider 接上可信身分和 Resource Authorization。

Lab 跑完後，我最在意的是功能和採用風險同時成立：

| 觀察 | 結果 | 解讀 |
| --- | --- | --- |
| Tagged Agent 可讀取 | PASS | Catalog 能保存並搜尋 Agent Metadata |
| Deployment 進入 kagent | PASS | Controller 能把 Desired State Materialize 到 Runtime |
| Declarative Undeploy | PASS | Teardown 仍沿同一條 Control Path |
| Anonymous Catalog Write | RISK_EXPOSED | 預設安裝不是 Production Authorization Baseline |
| 相同 `approved` Tag 更換 Image | RISK_EXPOSED | Tag 本身不是 Immutable Promotion Evidence |

![Day 19 實際 Lab 輸出的 terminal card。Catalog 讀取、部署到 kagent 與 declarative undeploy 通過。匿名寫入及相同 approved tag 更換 image reference 被列為 RISK_EXPOSED。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/screenshots/day-19/03-agent-registry-boundary-results.png)

畫面裡的部署狀態是綠的，但 `approved` 可改、預設寫入又沒有身分限制。若只看 Controller Status，很容易把「部署程序正常」讀成「上架的 Agent 已被組織核准」。

最後一次 Apply 將 `Deployment.spec.desiredState` 改成 `undeployed`。kagent 中由 Registry 管理的 Agent 隨即移除，Registry UI 則保留 Catalog 與 Deployment Record。這比直接 Delete 更適合平台操作，因為 Desired State、Status 與 Runtime Teardown 仍走同一條控制路徑。

![Agent Registry 0.4.0 實際 Deployed 頁面。完成 declarative undeploy 後，頁面顯示 0 resources running，同時保留 day19byo 的 deployment record。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/screenshots/day-19/02-agent-registry-deployed.png)

## 採用條件不能只看 Controller 功能

[Lab 03 的 Day 19 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r3/labs/03-gateway-runtime/README.md) 可以用一條命令重跑 Catalog Apply、Deployment、相同 Tag 更新與 Undeploy：

```bash
make lab-03-runtime-registry
```

`0.4.0` 的 Catalog、Kubernetes-style API、Controller Status 與 Undeploy，已經能串成完整的上架與部署路徑。我不能再沿用「它只是展示 Metadata」的舊印象。需要跨團隊 Agent／MCP Catalog 的組織，確實有理由重新評估它。

我把完整採用問題留在 [Agent Registry 採用盤點表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r3/articles/day-19/registry-adoption-checklist.md)。這篇最影響我們決定的只有三件：誰可以改 Catalog 裡的 `approved`、誰負責讓批准紀錄對上實際 Image，以及 Registry Database 和 Git 對同一個 Deployment 意見不同時，值班的人該聽誰的。

所以今天重新選型，我不會再用「缺少 Reconciliation」否決它。但在上架權限、Image Promotion 和 Git／Registry 分工有 Owner 以前，也不會把它放進現行平台。多一個能改變 Deployment 的 Control Plane，就多一份需要值班與稽核的狀態。

如果一個團隊已經需要 Self-service Catalog，也願意維護 Provider、Database、Promotion 與 Reconciliation，這筆交換可能很划算。對我們而言，先把誰能上架、誰能批准和哪份狀態有權改動 Runtime 談清楚，比先把服務裝上去更重要。

## Registry 無法還原一次 Agent 行動

Agent Registry 可以告訴平台某個 Agent 是誰、目前標成什麼版本，以及 Deployment 是否已經 Reconcile。當 Agent 實際被某個 Principal 呼叫，Registry 裡的資料仍不足以還原誰授權誰、套用哪版 Policy、Tool 最後改了什麼。

Day 20 會把視線轉向 Traceability，沿著一筆 Tool Call 把 Principal、Delegation、Artifact、Policy Decision 與執行結果串回來。Catalog 告訴我們可能執行的是哪個 Agent，真正的責任鏈仍要由執行當下的資料回答。

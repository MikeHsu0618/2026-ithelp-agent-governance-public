# Day 19｜Agent Registry 選型回顧：從拆除 0.3.3 到重測 0.4.0

Day 18 的 BYO Agent 已經能被 kagent 部署、找到，也能讓另一個 Agent 透過 A2A 呼叫。當團隊開始累積更多 Agent，下一個麻煩很快就會出現：大家看到的 `approved` 到底是誰批准的，那個 tag 又能不能保證明天仍指向同一份 image？

這不是我第一次評估 Agent Registry。我曾經把 `0.3.3` 部署到 Kubernetes，實際讀過 source，也真的把它拆掉。當時的結論跟產品好不好用沒有太大關係，而是它保存 desired state 的方式、授權邊界與我們既有的 GitOps 流程接不起來。現在的 `0.4.0` 已經大幅重作，如果只拿舊印象批評新版，對專案並不公平。

所以這次不重建兩套舊新版本做功能 PK。歷史經驗只用來列出採用門檻，公開 Lab 則只測 `0.4.0`：先註冊一個帶有 `approved` tag 的 Agent，讓 controller 把它部署到 kagent，再測同一個 tag 換掉 image reference 後會發生什麼事。

## Agent Registry 進入候選的原因

Agent Registry 想解的問題很實際。Agent、MCP Server、Model 與 Skill 散在不同 repository 和 cluster 後，使用者需要一個地方搜尋版本、閱讀 metadata，再把選到的 Artifact 交給 Runtime。若只靠 README、Slack 訊息和一張人工維護的清單，半年後通常沒有人能確定哪個版本還能用。

這個定位也正好落在我們當時缺少的位置。kagent 能部署與發現 Agent，agentgateway 能治理執行流量，但兩者都不會替組織維護一份完整的 Artifact catalog。Agent Registry 因此不是為了多一個漂亮 UI，而是可能成為發布、搜尋與 deployment reconciliation 的 control plane。

## 0.3.3 的拆除理由

我們原本的 application delivery 以 Git 裡的設定和環境分支為 review 入口，Kubernetes 與 Terraform 的變更也沿著同一套流程交付。`0.3.3` 當時把 Registry state 放在 PostgreSQL，操作則經 REST API 進入。對我們而言，這等於在 Git 之外又出現一份會影響 Runtime 的 desired state。PostgreSQL 本身沒有問題，麻煩出在事故發生時，大家究竟該相信 pull request、Registry database，還是 cluster 裡正在跑的資源。

另一個障礙是授權。Catalog 一旦只供閱讀，權限寬鬆的代價還不算大。若它能決定某個 Agent 是否進入 Runtime，create、update、promotion 與 deployment 就必須接上組織的 principal、role 與 audit。當時的 OSS 能力沒有達到我們需要的細緻程度，而團隊也不想為了少數服務再維護一套額外的授權與同步邏輯。

回頭重讀鎖在 [`v0.3.3`](https://github.com/agentregistry-dev/agentregistry/tree/v0.3.3) 的 source 後，有兩個早期批評應該收回。第一，產品並不是只能靠 UI 操作，CLI 與 API 路徑早已存在。第二，我當時沒有完成 agentgateway compatibility test，不能因為自己的整合沒有走完，就把它寫成 upstream integration 壞掉。留下來影響拆除決策的，仍是 state ownership、reconciliation 與 authz 是否符合我們的 operating model。

## 0.4.0 的控制面重作

[`0.4.0` release notes](https://github.com/agentregistry-dev/agentregistry/releases/tag/v0.4.0) 把這次改版稱為 breaking rewrite，也明確說明不能從 `0.3.x` 原地升級，必須使用新的 database。新版用 `ar.dev/v1alpha1` 的 Kubernetes-style manifests 表達 Agent、Runtime 與 Deployment，並由 controller 持續 reconcile deployment status、runtime resource 與 teardown。

這裡的 Kubernetes-style 很容易被看成 CRD，兩者其實不是同一件事。[API package 的說明](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/pkg/api/v1alpha1/doc.go)把這些 type 定義成 wire、storage 與 API contract，Registry 仍將 spec／status 寫入 PostgreSQL。當 `Deployment` 指向 Kubernetes Runtime 時，[deployment controller](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/internal/registry/controller/deployment.go)才把 Registry 裡的 desired state 轉成 kagent 的 Kubernetes resource。

![Agent Registry 0.4.0 的 Catalog 與 Deployment controller 邊界。Author 或 CI 經 API 寫入 PostgreSQL 內的 Agent、Runtime 與 Deployment，controller 再把 Deployment materialize 成 kagent Agent。下方另列出本次已驗證的 catalog、reconciliation、image reference 更新與 undeploy，以及 Registry 本身不會自動補上的 authentication、Git promotion、簽章和 runtime policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/diagrams/day-19/registry-reconciliation-trust-boundary.png)

新版補上的是我當年缺少的 declarative reconciliation。Manifest 雖然長得像 Kubernetes YAML，Git 卻不會因此自動成為 source of truth，`approved` 也不會直接變成經過簽章且不可變的 promotion 結果。

## Lab：同一個 approved tag 換成另一個 image

公開 Lab 另外建立一個 `ithelp-day19` kind cluster，安裝 Agent Registry `0.4.0` 與 kagent `0.10.1`。前面沒有再疊 Gateway，也沒有為了講 GitOps 硬塞 Argo CD。這次只驗 catalog 到 Runtime 的生命週期，kagent 也不呼叫外部 LLM。

第一份 manifest 註冊 `day19byo@approved`，image reference 是 `1.0.0`。`Deployment` 再用同一個 name 和 tag 指向它，Runtime 則指定由 kagent 承接。以下節錄會影響這次實驗的兩個資源：

```yaml
apiVersion: ar.dev/v1alpha1
kind: Agent
metadata:
  namespace: day19-lab
  name: day19byo
  tag: approved
spec:
  source:
    image: ithelp/day19-byo:1.0.0
---
apiVersion: ar.dev/v1alpha1
kind: Deployment
metadata:
  namespace: day19-lab
  name: day19-agent
spec:
  targetRef:
    kind: Agent
    name: day19byo
    tag: approved
  runtimeRef:
    kind: Runtime
    name: day19-kubernetes
```

啟動後，UI 能查到這筆帶有 `approved` tag 的 Agent。這張畫面來自 Lab cluster，不是照著文件重畫的 mock。

![Agent Registry 0.4.0 實際 UI。Agents 頁面顯示 day19byo，tag 為 approved，描述已更新成相同 catalog tag 指向另一個 image reference。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-19/01-agent-registry-catalog.png)

接著，Probe 對同一個 `day19byo@approved` 再做一次 apply，只把 image reference 改成 `ithelp/day19-byo:1.0.1`。Registry 接受變更，既有 Deployment 也被 controller 重新 reconcile，kagent Agent 最後跟著換成新的 reference。這證明新版 controller 會追蹤 target 的變更，功能上是成功的。站在 provenance 的角度，同一個 `approved` 可以原地換內容，卻也是必須另外處理的風險。

本次兩個本機 tag 指向同一份測試 image，因此 Lab 證明的是「desired image reference 可變，而且變更會進入 Runtime」，並沒有拿兩份不同程式冒充 supply-chain attack。要驗 Artifact 的實際 bytes，還需要 immutable digest、signature 與 attestation，不能只看 tag 字串。

## 五個觀察裡有兩個風險

Probe 沒帶 credential 就呼叫 `POST /v0/apply`，預設 OSS 安裝接受了寫入。這跟專案自己的 [security self-assessment](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/docs/governance/cncf/security-self-assessment.md)一致：預設設定是 permissive，不能當成 authenticated security boundary。整合者要透過 AuthnProvider 與 AuthzProvider 接上可信的身分和資源授權。

完整執行結果如下。`RISK_EXPOSED` 不是測試失敗，而是 Lab 成功重現了不該被 `PASS` 掩蓋的採用風險。這樣標記也能避免 reconciliation 全綠時，讀者誤以為信任鏈已經完成：

```text
DAY 19 / AGENT REGISTRY BOUNDARY

Anonymous catalog write                  RISK_EXPOSED
Tagged Agent readable                    PASS
Deployment reached kagent                PASS
Same approved tag changed image          RISK_EXPOSED
Declarative undeploy removed Agent       PASS

catalog-tag=approved
image-before=ithelp/day19-byo:1.0.0
image-after=ithelp/day19-byo:1.0.1
observed=5/5
risk-findings=2
```

![Day 19 實際 Lab 輸出的 terminal card。Catalog 讀取、部署到 kagent 與 declarative undeploy 通過。匿名寫入及相同 approved tag 更換 image reference 被列為 RISK_EXPOSED。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-19/03-agent-registry-boundary-results.png)

最後一次 apply 把 `Deployment.spec.desiredState` 改成 `undeployed`。kagent 裡由 Registry 管理的 Agent 隨即被移除，Registry UI 則保留 catalog 與 deployment record，顯示目前沒有任何 resource running。這個結果比單純執行 delete 更適合平台操作，因為 desired state、status 和 runtime teardown 仍在同一條控制路徑上。

![Agent Registry 0.4.0 實際 Deployed 頁面。完成 declarative undeploy 後，頁面顯示 0 resources running，同時保留 day19byo 的 deployment record。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-19/02-agent-registry-deployed.png)

## 公開 Lab 的執行方式

[Lab 03 的 Day 19 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20/labs/03-gateway-runtime/README.md)會建立獨立 kind cluster，安裝兩個 controller，再依序執行 catalog apply、deployment、相同 tag 更新與 undeploy。環境需要 Docker Engine、Helm、kind `0.30.0`、kubectl `1.34.x` 與 uv，完整流程只要一條命令：

```bash
make lab-03-runtime-registry
```

若想先開 UI 觀察 catalog 與 deployment status，可以把建立環境和 probe 拆開執行。兩個 target 使用同一份 context guard，不會讀取目前桌面上其他 Kubernetes context：

```bash
make lab-03-runtime-registry-up
make lab-03-runtime-registry-run
```

完成後，使用 Lab 自己的 cleanup target 刪除 `ithelp-day19` cluster：

```bash
make lab-03-runtime-registry-down
```

## 採用條件不能只看 reconciliation

實際跑完後，有些舊印象必須修正。`0.4.0` 的 catalog、Kubernetes-style API、controller status 與 undeploy 已經能形成一條完整的 declarative path，不能再說 Agent Registry 只負責展示 metadata。若組織正缺一個跨團隊的 Agent／MCP catalog，也願意讓它成為正式 control plane，新版的價值比 `0.3.3` 時清楚許多。

授權的結果就沒這麼樂觀。[OSS authorization matrix](https://github.com/agentregistry-dev/agentregistry/blob/v0.4.0/docs/auth/authz-matrix.md)裡的 public provider 允許所有操作，Lab 也真的以匿名請求改掉 `approved` Agent。產品提供了接入 authentication 的介面，但 production owner 必須在上線前把 provider、role、審批與 audit 接好，不能把預設 Helm install 當成安全基線。

我把重測結果整理成一份 [Agent Registry 採用盤點表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20/articles/day-19/registry-adoption-checklist.md)。它刻意把產品能力與組織責任拆成兩欄，避免看到 API 或 controller 存在，就直接把採用條件勾成完成。目前最直接的判斷如下：

| 採用問題 | 本次結果 | 還缺什麼 |
| --- | --- | --- |
| 使用者能否找到帶版本／tag 的 Agent | `PASS` | Catalog owner 與 metadata 品質規範 |
| Desired state 能否進入 kagent 並完成 teardown | `PASS` | Production Runtime RBAC、失敗復原與 SLO |
| `approved` 是否代表不可變 Artifact | `RISK_EXPOSED` | Digest、signature、attestation 與 promotion policy |
| 預設安裝能否限制誰改 catalog | `RISK_EXPOSED` | AuthnProvider、AuthzProvider、role mapping 與 audit |
| Registry 與 Git 誰是最終權威 | `ORGANIZATIONAL` | 明確的 write path、review owner 與 drift 處理方式 |
| Runtime traffic 是否已被授權 | `OUT_OF_SCOPE` | Gateway／Runtime policy 與可信 identity context |

如果今天重新做選型，我不會再用「缺少 reconciliation」否決 `0.4.0`。我仍不會立刻把它放進既有平台，原因也變得更精確：在組織決定誰擁有 Artifact promotion、Registry 與 Git 如何分工，以及預設 permissive auth 如何補齊以前，多一個控制面只會多一份需要值班與稽核的狀態。

這個結論不是所有團隊都該拆掉 Agent Registry。若團隊需要 self-service catalog，也願意正式維護 provider、database、promotion 與 reconciliation，它已經是值得重新評估的方案。對我們而言，先把 ownership 與信任鏈談清楚，比先把服務裝上去更重要。

Agent Registry 可以告訴平台某個 Agent 是誰、目前標成什麼版本，以及 Deployment 是否已經 reconcile。當這個 Agent 實際被某個 principal 呼叫，Registry 裡的資料仍不足以還原「誰授權誰、套用哪版 policy、Tool 最後改了什麼」。Day 20 會把視線轉向 Traceability，沿著同一個 action 把 principal、delegation、Artifact、policy decision 與執行結果串回來。

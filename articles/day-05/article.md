# Day 5｜Agent Governance 四問：用一條 Action Path 盤點治理缺口

Day 4 用兩筆 `query_metrics` 說明了 name-based allowlist 的限制。Tool 名稱相同，查詢目標卻可能已經超出值班工程師原本授權的範圍。就算補上 principal、resource 和 delegation scope，我仍然不敢把整條 Agent path 標成「已受治理」。事故發生時，我們還得知道執行的是哪一版 Agent、哪裡能在副作用前拒絕，以及事後能不能按照原始順序重建。

這些問題散落在 IdP、Agent runtime、Gateway、Tool server 與觀測系統之間，單看任何一個產品都看不完整。於是我把一筆具體動作放到桌上，固定追四件事：誰在行動、執行的是哪一版、哪裡能拒絕、事後能不能重建。後文用 Identity、Provenance、Enforcement、Traceability 稱呼它們，每一題最後都要拿出證據。

## 先選一筆真的會發生的動作

這次沿用前一篇的唯讀查詢：

```text
synthetic-user-sre-oncaller
  → sre_investigation_agent
  → runtime workload
  → query_metrics(service="payments-api")
  → synthetic metrics result
```

這條 Lab 路徑只會回傳固定的合成指標，`synthetic-user-sre-oncaller` 也只是 session label。環境很小，哪些證據真的存在、哪些只是名稱，看得反而更清楚。

如果一開始就評估「整個 AI 平台」，幾乎每個答案都只能寫成「視情況而定」。限定到這筆 request 後，問題就具體了：這個 session label 是否經過驗證、執行時載入哪一版 Agent、`query_metrics` 在哪裡能被拒絕，以及 Tool result 能否和前面的模型提案、政策判斷串回同一條事件。

## 產品架構圖看不到的接縫

我最初也按照產品分類。身分系統負責登入，Gateway 負責 routing 和 policy，Agent Registry 管 metadata，Grafana LGTM 收 logs、metrics 和 traces。圖上的每個方框都有名字，也很容易分配 owner。

拿事故問題去問時，這張圖卻答不出來。身分系統認得值班工程師，下游事件不一定還保留他的身分。Registry 找得到 Agent，也不能證明這次 runtime 載入的就是已核准版本。Gateway 留下一筆 `ALLOW` 或 `DENY`，仍然不能取代資源端的授權。Trace 收得很完整，如果事件缺少 Agent revision 和 policy version，最後只能重播一段無法歸責的流程。

這是我開始沿 Action Path 做 Review 的原因。產品負責提供能力，治理 Review 要確認證據有沒有跟著 request 穿過產品接縫。

## 這條 Action Path 的盤點結果

把 Day 1–4 的實際 evidence 放回 `query_metrics` 這條路徑後，目前得到的是：

| Review 問題 | 現在拿得出的證據 | 仍然回答不了什麼 | 狀態 |
| --- | --- | --- | --- |
| 誰在行動（Identity） | Session label、Agent name | Human 是否已驗證、哪個 workload 拿 credential 執行 | `PARTIAL` |
| 執行的是哪一版（Provenance） | Repo 裡有 Agent 與 Tool source | 這次執行綁定哪個 revision、digest 與 approval | `UNKNOWN` |
| 哪裡能拒絕（Enforcement） | ADK callback 能在 Tool 前回覆 `DENY` | 只看 Tool name，無法判斷 principal 與 resource | `PARTIAL` |
| 事後能否重建（Traceability） | Trace ID、ordered events、replay | 缺 actor、artifact 與下游授權事件 | `PARTIAL` |

`PARTIAL` 表示已經有一部分可驗證結果，但仍缺少欄位或邊界。`UNKNOWN` 只表示目前沒有 runtime evidence，先保留空白，別用推測補滿。

Provenance 最容易被 source repository 誤導。Repo 裡看得到 Agent 定義，只能證明這份程式碼存在，不能證明某次 request 跑的就是這一版。要回答事故當下執行了什麼，至少得把 revision 或 artifact digest 綁進 deployment，再把同一個識別資料寫進執行事件。否則程式碼 review 得再完整，事件和受審版本之間仍然接不起來。

Enforcement 和 Traceability 也不能互相代替。Callback 成功擋過 `delete_demo_database`，證明副作用前存在一個拒絕點，但沒有補上 principal-aware authorization。Ordered events 能重播模型提案、policy decision 和 Tool result，也無法憑空還原沒有記錄的 workload identity 或 Agent revision。

![值班工程師的 session label 經 SRE Agent、runtime workload 與 Tool policy 呼叫 query_metrics。盤點結果顯示 Identity、Enforcement、Traceability 都有部分證據，Provenance 則缺少能綁定本次執行的版本證據。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19-r1/assets/diagrams/day-05/reference-architecture-v0.1.png)

## Checklist 最後要留下的，是下一個工作

我把這套 Review 整理成 [Agent Governance 四問 Checklist](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19-r1/articles/day-05/governance-four-question-checklist.md)。使用時先選一個 action，再為每一題附上實際 request、事件、設定或 deployment 證據。文件只寫「支援」時，最多算 `DOCS ONLY`。完全找不到資料就保留 `UNKNOWN`。

最後不要把四個狀態平均成一個分數。唯讀 Metrics Agent 缺少 workload identity，和能修改 Kubernetes Deployment 的 Agent 缺少同一項證據，修補順序不會一樣。Review 應該選出一個最小缺口，指定 owner，並寫清楚怎樣才算驗收通過。

以這次 Lab 為例，Provenance 是 `UNKNOWN`，但下一步未必先建 Agent Registry。眼前的 policy 連 Human 都還沒有驗證，後續所有 principal-aware 規則都無法落地。先補 verified principal，會比先替 synthetic Agent 建完整供應鏈獲得更直接的風險改善。

NIST AI RMF 1.0 的 [Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) 用 Govern、Map、Measure、Manage 涵蓋更廣的組織與 AI lifecycle 風險，[Playbook](https://airc.nist.gov/airmf-resources/playbook/) 也明確說明建議不是必須逐項完成的 checklist。這裡的四問只用來檢查一筆 Agent action，不能取代法遵、模型品質、組織風險容忍度或完整 AI 治理框架。

## 第一個缺口落在可驗證身分

Day 5 沒有新增防護，而是把前四天的結果放進同一份 Review。對 `query_metrics` 這條路徑來說，下一個實驗已經很明確：把 `synthetic-user-sre-oncaller` 換成下游可以驗證的 principal，並定義 Gateway 與 MCP 都能理解的 issuer、audience、role 和 scope。

當時我們已經用 Keycloak 跑通企業 IdP、JWT role 與 Gateway 到 MCP 的 Tool RBAC。技術驗收成功後，接下來要決定的是團隊準備承接企業級 Identity Center，還是先替少數 AI 服務提供一個較小的 identity bridge。Day 6 會從這個組織邊界開始。

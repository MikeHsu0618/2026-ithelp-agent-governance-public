# Day 5｜Agent Governance 四問：用一條 Action Path 盤點治理缺口

Day 4 用兩筆 `query_metrics` 說明了 name-based allowlist 的限制。Tool 名稱相同，查詢目標卻可能已經超出值班工程師原本授權的範圍。就算補上 principal、resource 和 delegation scope，我仍然不敢把整條 Agent path 標成「已受治理」。事故發生時，我們還得知道執行的是哪一版 Agent、哪裡能在副作用前拒絕，以及事後能不能按照原始順序重建。

這些問題散落在 IdP、Agent runtime、Gateway、Tool server 與觀測系統之間，單看任何一個產品都看不完整。於是我把一筆具體動作放到桌上，固定追四件事：誰在行動、執行的是哪一版、哪裡能拒絕、事後能不能重建。後文會用 Identity、Provenance、Enforcement、Traceability 當作這四個問題的簡稱。

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

我最初也按照產品分類。身分系統負責登入，Gateway 負責 routing 和 policy，版本目錄記錄有哪些 Agent，Grafana LGTM 收 logs、metrics 和 traces。圖上的每個方框都有名字，也很容易分配 owner。

拿事故問題去問時，這張圖卻答不出來。身分系統認得值班工程師，下游事件不一定還保留他的身分。版本目錄找得到 Agent，執行時載入的程式卻可能已經換了。Gateway 留下一筆 `ALLOW` 或 `DENY`，仍然不能取代資源端的授權。Trace 若沒有 Agent revision 和 policy version，值班的人也很難對回當時的決定。

所以我不再先問「平台有沒有某個產品」，而是沿著同一筆 request 問：它經過每個元件時，原本知道的身分、版本和決定還剩下多少？

## 這條 Action Path 的盤點結果

把 Day 1–4 的結果放回 `query_metrics` 這條路徑後，四個問題並沒有一起得到答案：

| Review 問題 | 現在拿得出的證據 | 仍然回答不了什麼 | 狀態 |
| --- | --- | --- | --- |
| 誰在行動（Identity） | Session label、Agent name | Human 是否已驗證。若呼叫下游，當前憑證代表誰 | `PARTIAL` |
| 執行的是哪一版（Provenance） | Repo 裡有 Agent 與 Tool source | 這次執行綁定哪個 revision、digest 與 approval | `UNKNOWN` |
| 哪裡能拒絕（Enforcement） | ADK callback 能在 Tool 前回覆 `DENY` | 只看 Tool name，無法判斷 principal 與 resource | `PARTIAL` |
| 事後能否重建（Traceability） | Trace ID、ordered events、replay | 缺 actor、artifact 與下游授權事件 | `PARTIAL` |

表中的 `PARTIAL` 是「目前能回答一部分」，`UNKNOWN` 是「這次執行沒有留下答案」。代碼方便填 Checklist。排工作順序時，我們還是得回到具體動作，判斷哪個缺口最可能讓它失控。

Provenance 最容易被 source repository 誤導。Repo 裡看得到 Agent 定義，只能證明這份程式碼存在，不能證明某次 request 跑的就是這一版。要回答事故當下執行了什麼，至少得把 revision 或 artifact digest 綁進 deployment，再把同一個識別資料寫進執行事件。否則程式碼 review 得再完整，事件和受審版本之間仍然接不起來。

Enforcement 和 Traceability 也不能互相代替。Callback 成功擋過 `delete_demo_database`，說明副作用前有拒絕點，但沒有補上按呼叫者與目標資源決定權限的能力。Ordered events 能重播模型提案、policy decision 和 Tool result。若當時沒記下 Agent revision 或下游憑證，事後也無法憑空補回。

![值班工程師的 session label 經 SRE Agent、runtime workload 與 Tool policy 呼叫 query_metrics。盤點結果顯示 Identity、Enforcement、Traceability 都有部分證據，Provenance 則缺少能綁定本次執行的版本證據。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-05-r4/assets/diagrams/day-05/reference-architecture-v0.1.png)

## 從四個缺口選下一個工作

我把這四個問題整理成 [Agent Governance 四問 Checklist](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-05-r4/articles/day-05/governance-four-question-checklist.md)。拿自己的 Agent 使用時，先挑一個實際會做的動作，再查它在每個邊界留下什麼。完整狀態代碼和填寫方式放在 Checklist，正文先用這筆查詢決定下一步。

四格不能平均成一個治理分數。唯讀 Metrics Agent 先要處理查詢範圍與呼叫者歸屬。能修改 Kubernetes Deployment 的 Agent，還得確認它用哪個憑證、對哪個資源執行變更。兩種動作的優先順序不會一樣。

這次我會先補呼叫者身分。Agent 版本還沒和執行事件綁定，確實是缺口。不過眼前的 policy 連 Human 是誰都無法驗證，`query_metrics` 因此無法按人與目標資源授權。先把身分接進這條路徑，比先建立完整的 Agent 版本目錄更能改變當下的判斷。

`synthetic-user-sre-oncaller` 目前只是 session label。要讓 Gateway 和 MCP 根據呼叫者做決定，下一步得換成可驗證的 principal，再說清楚 issuer、audience、role 和 scope 各在哪一站使用。

當時我們已經用 Keycloak 跑通企業 IdP、JWT role 與 Gateway 到 MCP 的 Tool RBAC。技術驗收成功後，接下來要決定的是團隊準備承接企業級 Identity Center，還是先替少數 AI 服務提供一個較小的 identity bridge。Day 6 會從這個組織邊界開始。

# Day 9｜Agent 交辦另一支 Agent：Delegation Context 如何留下請求來源

值班工程師請 SRE Copilot 查昨晚的登入錯誤。Copilot 把查詢交給 Investigator Agent，後者選了 MCP 的 `query_logs`。假如查詢範圍出了問題，MCP 的紀錄只寫 `actor=user/sre-oncaller`，看起來就像工程師親手呼叫了 Tool。只寫最後一跳的服務帳號，又看不出這筆工作是誰交辦、哪版 Agent 選的 Tool。

這是用來拆解責任的合成情境，不是一次真實事故。前兩篇談了人工交辦與排程任務的差別，也談過入口如何驗 JWT。接下來的難題是：請求經過兩支 Agent 後，最初的來由要怎麼留到最後一次 Tool Call？

## 交辦資訊在哪一跳消失

入口驗過值班工程師的 Token，就知道誰發起調查。Copilot 知道自己把工作交給 Investigator，後者知道自己選了 `query_logs` 和查詢目標。然而，MCP 收到的是最後一跳的請求，不會自動知道前面兩支 Agent 做過什麼。光靠 `trace_id` 可以把幾筆事件串在一起，卻不能補回根本沒記下的交辦者與 Agent 版本。

![值班工程師交辦 Copilot，Copilot 交辦 Investigator，後者呼叫 MCP。下方分開呈現請求來源、Agent 交接、目前憑證與操作目標。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09-r3/assets/diagrams/day-09/delegation-sequence.png)

我把這份交接紀錄稱為 Delegation Context。它不是另一枚 Token，也不是讓下游無條件相信上游的通行證。它要回答的是「這次動作從哪裡來、由哪版 Agent 接手、最後打算做什麼」。如果值班的人發現查錯資料，可以先看工程師原本指定的範圍，再看 Copilot 的交辦內容、Investigator 的版本與 Tool 參數，而不是只拿著一個 `actor` 猜責任落在哪裡。

例如工程師只要求調查登入錯誤，Copilot 卻把任務改寫成「查所有 production error」，問題就發生在交辦時。如果交辦內容沒變，Investigator 最後卻把查詢範圍擴大，該看的是它的 Tool 選擇與參數。兩種狀況在 MCP 都可能只顯示一次成功的 `query_logs`。交辦紀錄不能替我們做判決，但能讓調查先找到差異出現的位置。

這也解釋了為什麼 Pod 名稱或 Kubernetes ServiceAccount 不適合當這篇的主角。Pod 資訊有助於定位程式在哪裡執行。ServiceAccount 是 Kubernetes 的工作負載身分。它們都無法單獨說明誰發起這次調查，也不表示 MCP 已經驗過那個 Kubernetes 身分。[Kubernetes 的 ServiceAccount 文件](https://kubernetes.io/docs/concepts/security/service-accounts/)描述的是叢集內的非人類身分。外部服務是否接受它，還要看實際送出的憑證和驗證設定。

## 一筆紀錄先回答三個問題

公開 Lab 的 [Human delegated 範例](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09-r3/assets/screenshots/day-09/evidence/demo-context-human-delegated.json) 是一份合成的 JSON。完整格式收在 [Delegation Context Field Guide](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09-r3/articles/day-09/delegation-context-field-guide.md)，正文只取出調查時最先要看的部分：誰發起、Agent 怎麼交辦、最後要呼叫什麼。

在 repo root 執行：

```bash
jq -r '[
  .actor_chain.human.principal,
  (.actor_chain.agents | map(.principal + "@" + .version) | join(" -> ")),
  .target.action
] | @tsv' assets/screenshots/day-09/evidence/demo-context-human-delegated.json
```

```text
user/sre-oncaller  agent/sre-copilot@v1 -> agent/sre-investigator@v1  query_logs
```

比起只記一個 `actor`，這行資料保留了交辦順序。`target` 裡還有要查的 resource。`event_id` 和 `trace_id` 能把它接回其他事件。至於這一跳到底用哪枚憑證、MCP 驗過誰，則要看 `credential` 與下游的驗證紀錄，不能從 `human.principal` 直接推斷。

範例 JSON 另外填了一個合成的 Kubernetes ServiceAccount，來源標為 `ASSERTED`。這是資料格式示範，不是 MCP 驗證過的下游 caller，也不是每套 Agent 都必須使用 Kubernetes 的意思。真正要保留的是交辦路徑。執行位置和當前憑證可依實際部署另行關聯。

## 沒有登入者，和交辦者遺失了，不是一回事

排程 Agent 從一開始就沒有互動式使用者，Human 欄位可以記 `NOT_APPLICABLE`。若這原本是人工發起的調查，上游交辦時卻沒帶來請求來源，則不能假裝是排程，也不能補一個猜測的使用者。本 Lab 的 `HUMAN_DELEGATED` contract 會拒絕沒有 Human 的事件。實際系統則應把交接失敗另外記下來，查是哪一跳漏掉。`UNKNOWN` 可用於允許缺值的欄位，例如合成 fixture 裡未取得的 Workload metadata，但不能繞過這條 Human 必填規則。

資料格式可以幫忙區分這兩種狀況，卻不替 Tool 做授權。尤其 `VERIFIED` 這類標記不能由任意 client 自己填完，就當作 Gateway 真的驗過。入口要記自己驗到的登入者。Agent runtime 要記交辦與執行版本。下游仍須依眼前的憑證、動作和目標做決定。這三段紀錄能關聯，才有機會重建一次請求。

## 用 Lab 看交接紀錄長什麼樣

[Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09-r3/labs/02-identity-boundary/README.md) 提供人工交辦、排程以及欄位遺失的合成案例。想看資料格式如何區分它們，可以在 repo root 執行：

```bash
make lab-02-up
make lab-02-delegation
```

![Delegation Context Lab 的 CLI 結果，顯示人工交辦、排程與欄位缺失等案例。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09-r3/assets/screenshots/day-09/01-delegation-context-results.png)

結果中的 `ACCEPT` 只表示紀錄符合這份資料契約，並不是 Tool 已獲准執行。這個 Lab 沒有真的讓請求走過 Gateway、兩支 Agent 和 MCP。它讓我們先試清楚「交辦資訊要留哪些」，網路上每一跳該用什麼憑證則是另一個問題。

下一篇就從這裡接著看。即使紀錄已能還原值班工程師交辦 Investigator 的過程，如果 Agent 仍把工程師原來的 Access Token 原封不動送給 MCP，下游看到的 caller 和可用權限又會如何變化？

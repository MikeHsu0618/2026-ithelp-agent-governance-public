# Day 4｜Agent 拿誰的權限做事：Tool Allowlist 沒回答的身分問題

Day 3 的 [Google ADK Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-28-r1/labs/01-unsafe-agent/README.md) 成功擋下了 `delete_demo_database`。當時看到 `POLICY_DENIED`，我以為執行前授權已經有了不錯的起點。回頭看 callback，我才發現授權判斷只收到 Tool name：

```python
decision = policy.authorize(tool.name)
```

像 `delete_demo_database` 這種名稱，本來就很適合用 allowlist 拒絕。可是真正難處理的，通常不是一看就危險的 Tool，而是 `query_metrics` 這類每天都會使用的正常功能。同一個 Tool，有時應該放行，有時卻不該碰到目標資源。只看名稱的 policy 分不出來。

## 同一個 query_metrics，答案可以完全不同

假設值班工程師正在調查 `payments-api` 的延遲。Agent 呼叫：

```text
query_metrics(service="payments-api")
```

這筆請求符合原本的調查目的，應該放行。另一條路徑仍由同一位工程師發起，但 Agent 讀到的外部 Log 夾帶指令，把查詢目標帶往另一個團隊的 production service：

```text
query_metrics(service="another-team-api")
```

第二筆不是工程師原本要查的範圍，也沒有額外核准。問題是目前的 policy 對兩筆請求看到的內容完全相同：

```text
authorize("query_metrics") → ALLOW
```

| 授權需要知道的事 | 原本的調查 | 被外部內容帶偏後 |
| --- | --- | --- |
| 誰提出目的 | 值班工程師 | 仍是同一位值班工程師 |
| Agent 選了什麼動作 | `query_metrics` | `query_metrics` |
| 實際查詢目標 | `payments-api` | `another-team-api` |
| 預期結果 | `ALLOW` | `DENY` |
| 現有 allowlist 結果 | `ALLOW` | `ALLOW` |

Lab 裡的 `query_metrics` 只會回傳固定的合成指標，不會真的連到 Grafana。這裡使用它現有的 `service` argument 做 threat model，目的是把授權缺口攤開來看，而不是宣稱第二筆查詢真的碰過 production。

## Allowlist 其實只看見一個字串

ADK 的 callback 不只拿得到 Tool name，也拿得到 arguments。現有程式甚至把 `args` 寫進 `policy.decision` 事件：

```python
decision = policy.authorize(tool.name)

store.record(
    "policy.decision",
    tool_name=tool.name,
    tool_arguments=args,
    decision="ALLOW" if decision.allowed else "DENY",
)
```

這段程式很容易讓人誤會成「授權資料都有記錄」。但事件裡有 `tool_arguments`，不等於 policy 做決定時看過它。Session 裡的 `synthetic-user-sre-oncaller` 和 Agent 名稱 `sre_investigation_agent` 也是同樣情況。它們有值，卻沒有進入 `authorize()`。

更麻煩的是，session label 沒有 issuer 或 credential 可以證明它是哪位使用者，Agent 名稱也只是受控 metadata，不能代表真正拿 credential 送出 request 的 workload。資料存在、來源可信、policy 看得到，這三件事不能混在一起。

## 這種權限錯置早在 Agent 出現前就存在

1988 年，Norm Hardy 在〈[The Confused Deputy](https://dl.acm.org/doi/10.1145/54289.871709)〉描述了一個 Compiler。Compiler 必須用自己的權限寫入計費檔案，同時也允許使用者指定編譯輸出的檔名。當使用者把輸出位置指向計費檔案時，真正覆寫檔案的不是使用者，而是握有合法權限的 Compiler。

這類問題後來被稱為 Confused Deputy。Deputy 本身有權執行動作，卻把自己的權限用在呼叫者不該要求的目標上。

換回 Agent 場景，Agent runtime 就可能是那個 Deputy。它握有查詢 production metrics 的 credential，`query_metrics` 也在 allowlist 裡。外部 Log 只要成功改變查詢目標，runtime 就可能拿自己的真實權限完成一筆偏離原始任務的操作。

Prompt Injection 是造成這種偏離的一種方式，但不是 Confused Deputy 的定義。即使系統裡沒有 LLM，只要低信任輸入能控制目標，而受信任程式又拿自己的權限照做，同樣的問題就會出現。

![同一位值班工程師透過相同 Agent 呼叫 query_metrics。原始調查查詢 payments-api，外部 Log 則把另一筆請求帶往另一個團隊的服務。現有 policy 兩次都只收到 query_metrics，因此都回覆 ALLOW，但第二筆預期應為 DENY。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-28-r1/assets/diagrams/day-04/confused-deputy-sequence.png)

## 授權至少要回答三件事

Tool allowlist 已經提供 action。要分辨前面兩筆 `query_metrics`，policy 還得知道經過驗證的呼叫者，以及這次真正要碰的目標資源：

```text
authorize(
  principal = verified caller,
  action    = query_metrics,
  resource  = service/payments-api,
  scope     = this incident
)
```

`principal` 不一定是坐在瀏覽器前的人。排程任務可能使用 service principal，互動式 Agent 則可能需要保留 Human delegation。無論是哪一條路徑，policy 都不能用 Agent 名稱假裝成 Human，也不能用 requested argument 直接當成已驗證的 resource。

`scope` 則用來回答「這次受託範圍到哪裡」。值班工程師可以查 production metrics，不表示 Agent 得到一張可任意查詢所有服務的通行證。實際要保存哪些欄位，會依 Tool 風險與資源類型而變，但決策至少要能把呼叫者、動作與目標對起來。

## 有資料、可信、Policy 可見是三回事

把 Day 3 的實際事件攤開後，目前能確認的是：

| 資料 | Lab 裡有什麼 | 能直接當成授權證據嗎 | 現有 policy 看得到嗎 |
| --- | --- | --- | --- |
| Human | `synthetic-user-sre-oncaller` session label | 不能，沒有 IdP 驗證 | 否 |
| Agent | `sre_investigation_agent` metadata | 只能識別定義，不能代表執行者 | 否 |
| Workload | 沒有 workload identity event | 沒有證據 | 否 |
| Action | Tool name | 可以作為 action | 是 |
| Resource | Tool arguments 裡的 requested target | 還要由資源端解析與驗證 | 否 |

完整版本放在 [Agent Delegation Decision Table](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-28-r1/articles/day-04/delegation-decision-table.md)。這份表把「欄位有值」「由誰證明」和「policy 是否真的使用」分開，適合拿去檢查其他 Agent action。它不是要逼每一個 checkpoint 吞下所有欄位，而是防止架構圖上明明畫了 Identity，實際決策卻只收到一個 Tool 名稱。

Policy 做決定時只需要當下可驗證的欄位，Audit 則要保存較完整的責任鏈，讓事後能查出誰提出目的、哪個 Agent 做了選擇，以及哪個 workload 真正送出 request。兩者使用的資料有交集，但用途不同。

## 下一步，把缺口放回完整治理地圖

Day 4 先把「合法 Tool 為什麼仍可能用錯權限」說清楚。現在已經知道 policy 缺少 verified caller、target resource 與 delegation scope，但這還只是整條 Agent action path 的一部分。

下一篇會把同一筆動作從 Human、Agent、Workload 一路追到 Tool，檢查 Identity 之外，執行版本是否可信、哪裡能拒絕，以及事後能不能重建。等這四個問題放到同一張圖裡，才適合討論 Gateway、Registry 與可觀測性各自該負責哪一段。

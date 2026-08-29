# Day 4｜當 Agent 拿自己的權限替人做事：Confused Deputy 與 Delegation 缺口

前一天的 Lab 裡，SRE Agent 讀到一段藏在外部 Log 裡的惡意指令。Gemini 提出了 `delete_demo_database`，Keyword guard 沒攔住改寫過的內容，Tool allowlist 最後回傳 `DENY`。Safe canary 沒有增加，表示危險動作確實停在 Tool function 之前。

從 `canary_delta=0` 看，Day 3 的控制達成了預期，但實際的 policy call 還暴露了另一個沒測到的缺口：

```python
decision = policy.authorize(tool.name)
```

`decision = policy.authorize(tool.name)` 這行其實已經把授權輸入寫死了。同一個 callback 明明拿得到 Tool arguments，卻只把它們寫進事件，沒有交給 policy 判斷：

```python
store.record(
    "policy.decision",
    tool_name=tool.name,
    tool_arguments=args,
    decision="ALLOW" if decision.allowed else "DENY",
)
```

所以 Day 3 只能證明「不在 allowlist 裡的 Tool 會被拒絕」。如果某個 Tool 本來就在清單裡，這段 policy 分不出是誰要求、哪個 Agent 代辦、哪個 workload 拿著 credential 執行，也不知道 action 最後要落到哪個 resource。

> `Lab` Day 4 沿用前一天的 [Google ADK Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r1/labs/01-unsafe-agent/README.md) 與 attack scenario，不另造一套 runtime。檢查焦點從模型是否犯錯，移到現有證據走到 policy 前還剩多少。

## Day 3 的 Policy 只收到 Tool 名稱

ADK runner 建立 session 時放進了一個合成 caller ID：

```python
user_id = "synthetic-user-sre-oncaller"
```

Agent 定義也有名稱，Tool arguments 裡還帶著 requested target。把 source 與 event 裡的值並排後會是：

```text
agent_definition.name        = sre_investigation_agent
tool_call.name               = delete_demo_database
tool_call.arguments.database = payments-demo
```

`synthetic-user-sre-oncaller` 是 ADK runner 建立 session 時放進去的 label，event 裡沒有 issuer、authentication method 或 credential 能證明它對應到哪位使用者。`sre_investigation_agent` 來自載入的 Agent 定義，不是實際送出 request 的 workload identity。`payments-demo` 也只是模型放進 Tool argument 的 requested target，policy 還沒驗證過。三個欄位都不空白，但可信度和用途完全不同。

如果因此把它們全部標成 `UNKNOWN`，又會把三種不同狀態混在一起：值已經出現在流程裡但來源不夠可信、值可以留在 audit 卻沒有進 policy，以及真正沒有任何 evidence。目前完全沒有證據的，只有 executing workload 與 credential context。

真的沒有資料時，得由 IdP、runtime 或 workload identity 補上。資料已經存在卻沒送進授權判斷時，該改的是 policy contract。把兩種缺口拆開後，後面的修法才不會全部變成「再多記一點 Log」。

## Confused Deputy：從 Compiler 留下來的權限陷阱

Norm Hardy 在 1988 年的〈[The Confused Deputy](https://dl.acm.org/doi/10.1145/54289.871709)〉裡，就用 Compiler 描述過這種權限錯置。案例裡的 Compiler 為了維護統計資料，握有一般 User 沒有的檔案權限，User 又能指定 debug output 的檔名。Compiler 沒有分清楚這次寫檔引用的是哪一份 authority，結果可能拿自己的權限替 User 覆寫不該碰的檔案。

換成這次的 Agent Lab，角色雖然不同，權限問題很接近：

| 1988 年的案例 | SRE Agent Lab |
| --- | --- |
| User 要求 Compiler 工作 | 值班工程師要求 Agent 調查 latency |
| User 提供 debug output 名稱 | Agent 讀到帶有惡意指令的外部 Log |
| Compiler 解讀輸入 | Agent 將 Log 放進 model context |
| Compiler 使用自己的檔案權限 | Runtime 使用已掛載的 Tool capability |
| 敏感檔案可能被覆寫 | `delete_demo_database` safe canary 可能被觸發 |

Hardy 的案例和這次 Lab 不能做一對一的角色映射，因為前者的惡意意圖直接來自呼叫 Compiler 的 User，後者的值班工程師只要求調查，惡意內容則來自外部 Log。發生 Prompt Injection 不代表 Human principal 就是攻擊者，這裡的低信任輸入是 Log，值班工程師仍是調查的發起者。

這次 Lab 只重現 authority path，沒有真的連到資料庫。`delete_demo_database` 只會在 artifact 目錄追加一筆 canary event，用來表示 Agent 接住一個人的調查目的後，被另一份輸入帶偏，最後嘗試使用 runtime 已經持有的 capability。

## Human、Agent、Workload 與 Target

下面這張圖沿著 action 走到 policy checkpoint，檢查四個位置是否一起進入 decision。Tool action 寫在箭頭上，`payments-demo` 只代表 requested target，Lab 的實際結果仍是 safe canary。

![值班工程師要求 SRE Agent 調查 latency。Agent 讀到惡意 Log 後提出 delete_demo_database，Runtime workload 在呼叫 requested target 前經過 Policy checkpoint。現有 policy 只收到 Tool name。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r1/assets/diagrams/day-04/confused-deputy-sequence.png)

後面的文章會固定用四個位置描述一筆 Agent action：

| 位置 | 要回答的事 | 目前證據 |
| --- | --- | --- |
| human principal | 誰提出或核准這次目的？ | session 有合成 ID，尚未驗證 |
| delegating agent | 哪套 Agent 邏輯解讀意圖並選擇下一步？ | Agent 名稱已知，沒有進 policy |
| executing workload | 哪個 process、Pod 或 external service 真正拿 credential？ | `UNKNOWN` |
| target resource | action 要落在哪個 object 與 environment？ | argument 有值，沒有進 policy |

`delegating agent` 和 `executing workload` 很容易被壓成同一個 `agent_id`，實際部署後卻不一定是同一件事。一份 Agent 定義可以有多個 replicas，也可能透過 A2A 把工作交給另一個 runtime。只記 Agent 名稱，無法知道哪個 workload 真正送出了 request。

只留下 workload identity 也會丟掉另一半脈絡。Kubernetes ServiceAccount 可以指出哪個 Pod 送出 request，卻無法說明這個 Pod 正在替某位使用者工作，還是在執行自己的排程。

## Human identity 與 Workload identity

我一開始也把這題想得太簡單，覺得兩邊都有 JWT 就能串起來。實際整理 Human 與 M2M 存取後，我們當時使用的路徑最後拆成兩套 client 與 flow：互動式 caller 使用 public client 加 Authorization Code／PKCE，無人 workload 使用 confidential client 加 Client Credentials。

Public client + Authorization Code／PKCE 與 confidential client + Client Credentials，是我們當時採用的兩條路徑。放到這次的 policy 問題裡，兩種 token 能證明的內容不同：

- Human path 從互動式 principal 與授權流程開始，claim 內容仍取決於 IdP 與 client 設定。
- M2M path 證明 client 或 workload 自己的身分，以及它被授予的存取範圍。

當 Agent 替 Human 工作，下游往往得同時知道委派者與實際執行者。只看到 Client Credentials token 時，request 可能完全合法，發起調查的人卻會從 audit 裡消失。把入口收到的 Human bearer token 原封不動傳到所有下游，則會混掉 workload identity、audience boundary 與 credential exposure。

為了避免 policy 和 audit 最後只剩一個誰也說不清的 `actor`，至少要把三件事分開：

```text
identity    哪個 principal 通過驗證？
delegation  它被允許代表誰做哪件事？
execution   最後是哪個 workload 使用哪份 credential？
```

Day 4 先把 policy 與 audit 需要的位置留對，等 Day 7–12 實作這幾條 flow 時，才不會在選完 IdP 後，仍然只替一個混在一起的 `agent_id` 簽 token。

## Decision Table：分開記錄證據狀態

我把現有 Lab 填進 [Agent Delegation Decision Table](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r1/articles/day-04/delegation-decision-table.md)。這次不只寫值，還要標明證據狀態，以及 policy 現在是否看得到：

| Decision input | 現有值 | 證據狀態 | Policy 看得到嗎 |
| --- | --- | --- | --- |
| human principal | `synthetic-user-sre-oncaller` | session label，未驗證 | 否 |
| delegating agent | `sre_investigation_agent` | Agent metadata | 否 |
| executing workload | `UNKNOWN` | 沒有 workload identity event | 否 |
| credential subject／audience | `UNKNOWN` | Lab 沒有 access token | 否 |
| action | `delete_demo_database` | ADK Tool Call | **是** |
| requested target | `payments-demo` | Tool argument，未驗證 | 否 |
| approval context | `UNKNOWN` | 沒有 approval event | 否 |

表裡只有 executing workload、credential context 與 approval context 保留 `UNKNOWN`，因為這次 Lab 根本沒有相關 evidence。Session label、Agent metadata 與 Tool argument 則照實保留各自的值和來源，再分別標示是否經過驗證、policy 看不看得到。這樣做 design review 時，才不會被一句「我們都有記 Log」帶過，最後漏掉 policy 其實只收到 `tool_name`。

完整表格另外保留「誰簽發或觀察」「Policy 是否驗證」「Audit 是否保存」與「缺值時怎麼處理」。同一個欄位可以適合 audit，卻不適合直接授權。整條 chain 也不必全部塞進 JWT 或 metrics label。

## RFC 8693 的 subject／actor 語意

[RFC 8693 OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693.html) 提供了一套可參考的語意：`subject_token` 表示 request 是替誰提出，`actor_token` 表示目前 acting party。JWT 的 `act` claim 可以保留 actor。

```json
{
  "sub": "user/sre-oncaller",
  "act": {
    "sub": "client/sre-agent-runtime"
  },
  "aud": "metrics-tool",
  "scope": "metrics.read"
}
```

這段 JSON 是概念範例，不是本系列的 production token schema。RFC 8693 沒有替每個 deployment 決定 trust model、token profile 或 proof-of-possession。它還明定，巢狀 `act` 裡較早的 actor 只作資訊紀錄。Access-control decision 只看 top-level claims 與 current actor。

我在 Day 4 只借用 RFC 8693 的 subject／actor 語意，沒有因此決定導入 Token Exchange。要不要真的交換 token，還得一起評估 IdP 能力、audience boundary 與 credential flow。

## Policy 需要 Principal、Action 與 Resource

如果把 Day 3 的 policy contract 往前推一步，decision 不會再只是：

```text
ALLOW if tool_name in allowlist
```

它至少要能表達：

```text
verified human principal user/sre-oncaller
  經由 sre_investigation_agent
  委派給已驗證的 runtime workload
  對 payments-demo
  執行 query_metrics
  是否符合 policy vN？
```

為了測出 principal 與 target 是否真的會改變 decision，範例改用原本就可能被允許的 `query_metrics`。`delete_demo_database` 很容易靠 Tool name 直接拒絕，棘手的是合法 Tool 對不同 principal、target 或 environment 是否仍該得到同一個答案。

Enforcement point 可以放在 Agent callback、Gateway、MCP Server 或最後的 resource server。敏感 action 也可能需要兩層判斷。Gateway 的 `ALLOW` 只表示 request 可以繼續走，不代表資料庫、Kubernetes API 或 Grafana datasource 應該放棄自己的授權。

Day 3 的 allowlist 先擋住不該執行的 Tool，這一篇再把 policy 需要的 human principal、delegating agent、executing workload 與 target resource 分開，並在 Decision Table 裡區分「有值」「可信」和「policy 可見」。

做到這裡，action path 還少了 Agent／Tool artifact 的可信來源、Policy checkpoint 的位置，以及事後需要保存的證據。Day 5 會把 Identity、Provenance、Enforcement 與 Traceability 放到同一張治理圖上，看看前四天究竟補到了哪裡。

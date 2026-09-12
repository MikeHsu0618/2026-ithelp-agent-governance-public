# Day 20｜從 LLM Observability 到 Agent Traceability：一筆 Tool Call 還缺哪些責任資料

Day 19 把 Agent Registry 的邊界停在一個很現實的位置：平台可以知道某個 Agent 已經進入 Runtime，卻還不知道它被誰叫起來、代表誰行動，以及最後改了什麼。這些問題只有等到 Agent 真的執行，答案才會出現在 traffic、trace、policy decision 與 Tool receipt 裡。

沿用系列前面的案例，假設 `user/sre-oncaller` 請 `sre-investigation-agent` 呼叫 `delete_demo_database`。產品介面留下「Tool Call 成功」，Tempo 也畫出 Agent span 底下接著一個 Tool span。兩份資料都是真的，但事故調查若要確認 principal 是否經過驗證、Agent 代表誰、執行哪份 Artifact、哪版 policy 放行，以及資料庫究竟刪了幾筆，光靠這兩份紀錄仍然答不完整。Day 20 要補的不是另一排 Dashboard panel，而是一份能跟著 action 跨過多個元件的責任資料。

## 去年觀察 LLM，今年追到動作結果

我在 2025 年鐵人賽寫的是 [LLM 可觀測性](https://ithelp.ithome.com.tw/articles/10380029)。Prompt、Response、Token、Latency、Cost、Evaluation 與 Trace 到現在仍然重要，尤其模型品質、費用與應用流程出問題時，這些資料依然是調查起點。

現在的 Agent telemetry 早已超過 Token 和 Latency。以 [Claude Code Monitoring](https://code.claude.com/docs/en/monitoring-usage) 為例，官方輸出已涵蓋 metrics、events 與 beta traces，也包含 Tool decision、Tool result、permission、MCP、hook、skill 與 subagent 等活動。真正的缺口落在元件之間：每個 producer 各自知道一部分，組織還得想辦法把這些片段拼成同一條責任鏈。

這段差異也是我最近做 [`grafana-claudestats-app`](https://github.com/MikeHsu0618/grafana-claudestats-app) 時最有感的地方。我把 Claude Code 與 Codex 的 OpenTelemetry 接進同一套 LGTM，畫面不只看 Token 和 Cost，還拆出 Tools、Skills、Traces、Activity 與 Audit。做到後面，真正花時間的反而是 vendor semantics、PII、cardinality，以及哪些 event 可以被聚合、哪些必須保留原始因果關係。

Overview 先讓我用 team、team member 和 model 切換觀察角度，再回頭看 Cost、Token 與 Session。這比只做一張總量圖麻煩不少，卻能在成本突然上升時，把問題縮小到使用者、模型與時間範圍，而不是看著一條尖峰猜原因。

![grafana-claudestats-app 的實際 Overview 畫面，包含 Cost、Token、Session、模型與 Team Member 等切分維度。畫面使用可公開的測試資料。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-20/claude-code-stats-overview.png)

Activity 頁面則把 Code Lines Touched、Commit、Pull Request 與 Claude Active Time 放在同一個時間軸。這些數字不能直接拿來替工程師打績效，但在調查 Agent session 是否真的走到修改、提交與 PR 階段時，會比單看 Token 消耗多一層操作脈絡。

![grafana-claudestats-app 的實際 Activity 畫面，顯示程式碼增刪、Commit、Pull Request 與 Claude Active Time。畫面使用可公開的測試資料。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-20/claude-code-stats-activity.png)

這段 Claude Code 經驗提供的是個人實作證據，並沒有替 Day 20 增加第二套架構。Code Agent 常見的是使用者透過 OAuth 操作開發工具，再由工具連 MCP。本系列主線則是 ADK／kagent Agent 經 agentgateway 呼叫 MCP。兩條 traffic path 要分開看，前者在這裡只支撐一個較小的結論：單一 producer 即使送出很豐富的 telemetry，跨 Runtime、Gateway 與 Tool 的治理責任仍然要另外對齊。

## 同一筆 action 分成三種資料

我把 Day 20 的資料拆成 Application Record、Operational Telemetry 與 Governance Event。三者用 `action_id` 串接，Trace 與 Governance Event 再共用 trace context。它們不應被塞成一種萬用紀錄，因為使用者、保存時間、查詢方式與權限都不相同。

![同一筆 Agent action 分成 Application Record、Operational Telemetry 與 Governance Event。Application Record 保存產品脈絡，Operational Telemetry 保存執行路徑與健康狀態，Governance Event 保存 verified principal、delegation、Artifact、policy 與 effect。三者用 action ID 關聯，trace ID 只連接 trace 與治理事件。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/diagrams/day-20/traceability-data-boundary.png)

Application Record 服務的是產品介面與使用歷程，因此 session、generation、模型、Tool 摘要都很合理。它也可能知道畫面上的使用者是 `user/sre-oncaller`，但那個值若只從前端 session 或 request body 而來，就只能叫 `actor_hint`。把欄位改名成 `principal` 不會讓它突然具備驗證證據。

Operational Telemetry 的工作則是說明系統怎麼跑。Trace 很適合保存父子 span、延遲、錯誤、service、route 與有限的 correlation attributes，metrics 用來看整體率與趨勢，logs 則補充離散事件。這些訊號能帶 identity 投影，卻不該因為某個 span 上出現 `user.id`，就直接宣告完整 Audit 已經完成。

Governance Event 面對的是另一組讀者。資安、稽核、事件調查與平台 owner 需要知道 principal 的 assurance 和來源、delegation chain、executing workload、Agent Artifact digest、目標 resource、policy ID／version／decision、approval，以及 Tool 回報的 effect。這份資料通常要有更嚴格的寫入權限、保存期與完整性要求，也不適合把 raw prompt 或完整 Tool output 全部塞進去。

| 資料 | 主要回答 | 本次保留的例子 | 不能單獨證明 |
| --- | --- | --- | --- |
| Application Record | 使用者在產品裡做了什麼 | session、generation、`actor_hint`、Tool 摘要 | Verified identity、policy、真實副作用 |
| Operational Telemetry | 系統在哪一跳花時間或失敗 | trace／span、call graph、latency、error | 完整 delegation 與長期 Audit integrity |
| Governance Event | 誰代表誰，以哪版規則對什麼資源做了什麼 | principal、actor chain、Artifact digest、policy、approval、effect | 所有原始內容與完整操作細節 |

## Day 20 的 Lab 刻意拿掉模型不確定性

Day 1 已經用 Google ADK 與 Gemini live run 證明模型會讀取混有惡意指令的資料，接著選到危險 Tool。今天不需要再花一次 API 呼叫證明同一件事，否則模型輸出變化反而會干擾欄位契約測試。

因此 Lab 04 固定執行一筆 deterministic no-op canary。Tool 名稱仍叫 `delete_demo_database`，但程式不會連資料庫、shell、Kubernetes 或外部 API，只寫出 `CANARY_TRIGGERED` receipt，`side_effects` 固定為 `0`。這個切法也讓讀者能在沒有 Gemini key 的環境重現 Day 20。

先啟動 digest-pinned 的 Alloy 與 OTEL-LGTM，再執行 action：

```bash
make lab-04-up
make lab-04-check
make lab-04-run
```

Runner 產生 Application Record、Operational Trace、Governance Event 與 Tool receipt，並把 trace 和 event 透過 OTLP/HTTP 送進 Alloy。驗證程式會再向 Tempo 和 Loki 查詢，確認兩邊都找得到同一個 `action_id`：

```text
action_id=act-day20-a669406b17ca
trace_id=8e5bb2f2e7cd96e9f5fd0fd4fa30aebb
tempo_trace=PASS
loki_governance_event=PASS
correlation=PASS
result=CANARY_TRIGGERED
side_effects=0
```

Tempo 裡有兩個 spans。上層是 `invoke_agent sre-investigation-agent`，下層才是 `execute_tool delete_demo_database`。下圖是 Grafana 從本次 Lab backend 查到的實際 waterfall，原始 trace summary 也一起保留在 evidence。

![Grafana Tempo 實際查到的 Day 20 trace。根 span 是 invoke_agent sre-investigation-agent，child span 是 execute_tool delete_demo_database，兩者共用 trace ID。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-20/tempo-agent-tool-trace.png)

## Trace 說明執行路徑，責任欄位另外補齊

這筆 trace 已經能說明 Agent 呼叫 Tool 的順序與耗時。若系統只想除錯「為什麼慢」或「哪一跳失敗」，它已經很有用。事故調查想知道當時的授權依據，還得回到 Governance Event。

本次事件使用 `Governed Action Field Set v0.1` 驗證，以下只節錄責任鏈最重要的部分：

```json
{
  "action_id": "act-day20-a669406b17ca",
  "correlation": {
    "trace_id": "8e5bb2f2e7cd96e9f5fd0fd4fa30aebb",
    "span_id": "533266dd93540f1e"
  },
  "principal": {
    "id": "user/sre-oncaller",
    "kind": "human",
    "assurance": "VERIFIED",
    "source": "lab-fixture-idp"
  },
  "delegation": {
    "on_behalf_of": "user/sre-oncaller",
    "actor_chain": [
      "user/sre-oncaller",
      "agent/sre-investigation-agent",
      "workload/sre-investigation-agent"
    ]
  },
  "agent": {
    "name": "sre-investigation-agent",
    "version": "day20-fixture",
    "artifact_digest": "sha256:d20a..."
  },
  "policy": {
    "id": "tool-boundary",
    "version": "v3",
    "decision": "ALLOW",
    "enforcement_point": "lab-authorizer"
  }
}
```

Lab 裡的 Human principal 來自 fixture IdP，所以 assurance 可以標成 `VERIFIED`。Workload 只有 Runtime fixture 自己聲明，尚未接 SPIFFE、雲端 workload identity 或其他可驗證來源，因此刻意標為 `ASSERTED`。如果把兩者都寫成 `VERIFIED`，畫面會比較漂亮，證據卻變差了。

Loki 保存的是同一份完整事件。公開截圖的 LogQL 只移除 Python SDK 自動附加的本機 source path，沒有刪掉 principal、delegation、policy、result、trace ID 或 action ID。

![Grafana Loki 實際查到的 Day 20 governance event。事件包含 action ID、Agent Artifact digest、trace/span correlation、Human 到 Agent 與 Workload 的 actor chain、policy version 與 principal assurance。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-20/loki-governance-event.png)

## Tool 回成功，還要再看 effect

Agent 系統很容易把多層結果壓成一個 `success=true`。Gateway 收到 `200`、MCP 回了一個合法 result、Runtime 完成 workflow，以及下游資源真的被改動，這四件事其實可以同時有不同答案。

本次 receipt 的 `status` 是 `CANARY_TRIGGERED`，代表 Tool adapter 確實走到預定的 canary 分支。Governance Event 的 `effect` 則清楚記錄 `NO_OP_CANARY`、`SIMULATED` 與 `count=0`，不會因為流程正常就把沒有發生的刪除寫成成功副作用。

```json
{
  "result": {
    "status": "CANARY_TRIGGERED",
    "effect": {
      "kind": "NO_OP_CANARY",
      "status": "SIMULATED",
      "count": 0
    }
  }
}
```

這個欄位分法會一路用到 Day 25。到時同樣是 HTTP `200`，內容可能是 HTML、合法但資訊不足的 MCP result，或真的沒有產生預期 effect。現在先把 transport、workflow result 與 domain effect 分開，後面才不會拿一個綠色狀態蓋掉三種不同問題。

## 缺少 policy version 的事件直接拒收

欄位表若只放在文章裡，很快就會變成「有空再補」。Lab 把它做成 JSON Schema，所有治理事件在送出前都要經過驗證。負向測試刻意刪掉 `policy.version`，執行結果如下：

```bash
make lab-04-negative
```

```json
{
  "case": "missing-policy-version",
  "reason": "policy: 'version' is a required property",
  "result": "REJECTED"
}
```

只有 `decision=ALLOW` 不足以重建事故。Policy 可能在隔天被修改，如果事件沒有保存 version 或其他不可變 reference，調查者只能拿目前規則猜測當時發生什麼。這就是我寧可在 ingestion 前拒收，也不想讓一筆看似完整、實際無法重建的 Audit Event 悄悄進庫。

完整欄位、來源與建議放置位置整理在 [Governed Action Field Set v0.1 放置指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20/articles/day-20/governed-action-field-guide.md)。Machine-readable schema 與實際 run evidence 也都保留在公開 Repo，讀者可以直接修改 fixture，看哪一個缺口會被擋下。

## OpenTelemetry 負責搬運，不替組織定義責任

[OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) 已能用 trace／span context 關聯 log，也能透過 `EventName` 表達離散事件。這些能力足以承載 Day 20 的 Governance Event，不需要為了 Audit 另造一套完全無法和 trace 連接的 transport。

欄位語意仍要保持邊界。[OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) 目前仍標示為 Development，Lab 只在 span 上使用適合的 `gen_ai.operation.name`、`gen_ai.agent.*` 與 `gen_ai.tool.*`。`principal.assurance`、delegation、policy version 和 effect 等欄位是本系列的作者定義，在 span attribute 上一律使用 `ithelp.governance.*` prefix，文章也不會把它們冒充成官方標準。

同樣地，Application Record、trace 與 Governance Event 共用 ID，不等於三份資料一定要放在同一個 backend 或使用同一個 retention。正式環境還要處理寫入者可信度、redaction、存取控制、保存期限與防竄改。Day 20 只先確定「要保存什麼」與「哪一種資料負責回答」，完整 Audit 的差距會在 Day 26 收斂。

## 下一步把各個 producer 接進同一條管線

Lab 04 到目前只驗一筆 deterministic action 與兩種 backend 訊號，沒有假裝自己已經部署完整的 ADK／kagent、agentgateway 與 MCP 路徑。這是刻意的切分：先讓欄位契約穩定，再增加 producer，才看得出哪一跳真的有送資料、哪一欄只是後端猜出來的。

Day 21 會把範圍擴大到完整 telemetry pipeline。Agent Gateway 能看到 data plane traffic，Runtime 知道 Agent 內部步驟，MCP adapter 才可能拿到 Tool result 與 effect。這些訊號會一起經過 Alloy 進入 Tempo、Loki 與 metrics backend，並用固定情境檢查 correlation 是否真的跨過每一跳，而不是只在單一 process 裡看起來很完整。

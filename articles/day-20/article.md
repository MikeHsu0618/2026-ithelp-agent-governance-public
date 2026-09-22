# Day 20｜從 LLM Observability 到 Agent Traceability：一筆 Tool Call 需要哪些觀測資料

Day 19 把 Agent Registry 的邊界停在很現實的位置。平台可以知道某個 Agent 已經進入 Runtime，卻不知道它被誰叫起來、代表誰行動，以及最後改了什麼。這些答案只有等 Agent 真正執行後，才會出現在 Traffic、Trace、Policy Decision 與 Tool Receipt 裡。

沿用系列前面的案例，假設 `user/sre-oncaller` 請 `sre-investigation-agent` 呼叫 `delete_demo_database`。產品介面留下「Tool Call 成功」，Tempo 也畫出 Agent Span 底下接著 Tool Span。兩份資料都是真的，事故調查若要確認 Principal 是否經過驗證、Agent 代表誰、執行哪份 Artifact、哪版 Policy 放行，以及資料庫究竟刪了幾筆，仍然答不完整。

Day 20 要補的不是另一排 Dashboard Panel，而是一份能跟著 Action 跨過多個元件的責任資料。

## 從模型狀態追到 Agent 行動

我在 2025 年鐵人賽寫的是 [LLM 可觀測性](https://ithelp.ithome.com.tw/articles/10380029)。Prompt、Response、Token、Latency、Cost、Evaluation 與 Trace 到現在依然重要，尤其在模型品質、費用或應用流程出問題時，這些資料仍是調查起點。

Agent Telemetry 已經多出另一層問題。以 [Claude Code Monitoring](https://code.claude.com/docs/en/monitoring-usage) 為例，官方輸出涵蓋 Metrics、Events 與 Beta Traces，也包含 Tool Decision、Tool Result、Permission、MCP、Hook、Skill 與 Subagent 等活動。每個 Producer 各自知道一部分，組織仍要把這些片段拼成同一條責任鏈。

這也是我做 [`grafana-claudestats-app`](https://github.com/MikeHsu0618/grafana-claudestats-app) 時最有感的地方。我把 Claude Code 與 Codex 的 OpenTelemetry 接進同一套 LGTM，不只看 Token 和 Cost，也拆出 Tool、Skill、Trace、Activity 與 Audit。做到後面，真正花時間的是 Vendor Semantics、PII、Cardinality，以及哪些 Event 可以聚合、哪些必須保留原始因果關係。

![grafana-claudestats-app 的實際 Overview 畫面，包含 Cost、Token、Session、模型與 Team Member 等切分維度。畫面使用可公開的測試資料。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r1/assets/screenshots/day-20/claude-code-stats-overview.png)

Activity 頁面則把 Code Lines Touched、Commit、Pull Request 與 Active Time 放在同一條時間軸。這些數字不適合拿來替工程師打績效，但在調查 Agent Session 是否真的走到修改、提交與 PR 階段時，比單看 Token 消耗多一層操作脈絡。

![grafana-claudestats-app 的實際 Activity 畫面，顯示程式碼增刪、Commit、Pull Request 與 Claude Active Time。畫面使用可公開的測試資料。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r1/assets/screenshots/day-20/claude-code-stats-activity.png)

這段 Code Agent 經驗只支撐一個結論：單一 Producer 即使送出很豐富的 Telemetry，跨 Runtime、Gateway 與 Tool 的治理責任仍要另外對齊。它和本系列的 ADK／kagent → agentgateway → MCP Traffic Path 不會混成同一套架構。

## 一筆 Action 需要三種不同資料

我把 Day 20 的資料分成 Application Record、Operational Telemetry 與 Governance Event。三者以 `action_id` 關聯，Trace 與 Governance Event 另外共用 Trace Context。它們不該被塞進同一種萬用紀錄，因為使用者、保存時間、查詢方式與存取權限都不同。

![同一筆 Agent action 分成 Application Record、Operational Telemetry 與 Governance Event。Application Record 保存產品脈絡，Operational Telemetry 保存執行路徑與健康狀態，Governance Event 保存 verified principal、delegation、Artifact、policy 與 effect。三者用 action ID 關聯，trace ID 只連接 trace 與治理事件。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r1/assets/diagrams/day-20/traceability-data-boundary.png)

**Application Record** 服務產品介面與使用歷程，Session、Generation、Model、Tool 摘要都很合理。它也可能知道畫面上的使用者是 `user/sre-oncaller`。這個值若只來自 Frontend Session 或 Request Body，就只能叫 `actor_hint`。把欄位重新命名為 `principal`，不會讓它突然具備驗證證據。

**Operational Telemetry** 說明系統如何執行。Trace 保存父子 Span、Latency、Error、Service 與 Route，Metrics 觀察整體趨勢，Logs 補充離散事件。這些訊號可以投影有限的 Identity Attribute，卻不能因為 Span 上出現 `user.id`，就宣告完整 Audit 已經完成。

**Governance Event** 面向資安、稽核、事件調查與平台 Owner。它需要 Principal 的 Assurance 和來源、Delegation Chain、Executing Workload、Agent Artifact Digest、Target Resource、Policy ID／Version／Decision、Approval，以及 Tool 回報的 Effect。這份資料通常有更嚴格的寫入權限、保存期與完整性要求，也不適合把 Raw Prompt 或完整 Tool Output 全部塞進去。

| 資料 | 主要回答 | 不能單獨證明 |
| --- | --- | --- |
| Application Record | 使用者在產品裡做了什麼 | Verified Identity、Policy、真實副作用 |
| Operational Telemetry | 系統在哪一跳花時間或失敗 | 完整 Delegation 與長期 Audit Integrity |
| Governance Event | 誰代表誰，以哪版規則對什麼資源做了什麼 | 所有原始內容與完整操作細節 |

## Deterministic Lab 固定欄位，不再重演模型失誤

Day 1 已用 Google ADK 與 Gemini Live Run 證明模型可能讀取混有惡意指令的資料，再選到危險 Tool。今天不需要再花一次 API 呼叫證明同一件事，否則模型輸出變化反而會干擾欄位 Contract。

Lab 04 固定執行一筆 Deterministic No-op Canary。Tool 名稱仍是 `delete_demo_database`，程式不會連資料庫、Shell、Kubernetes 或外部 API，只寫出 `CANARY_TRIGGERED` Receipt，`side_effects` 固定為 `0`。讀者不需要 Gemini Key，也能重現同一筆 Action。

```bash
make lab-04-up
make lab-04-check
make lab-04-run
```

Runner 產生 Application Record、Operational Trace、Governance Event 與 Tool Receipt，Trace 和 Event 再透過 OTLP/HTTP 送進 Alloy。驗證程式向 Tempo 和 Loki 查詢，確認兩邊都找得到相同 `action_id` 與 `trace_id`。

Tempo 裡有兩個 Span。上層是 `invoke_agent sre-investigation-agent`，下層才是 `execute_tool delete_demo_database`。這張 Grafana Waterfall 來自 Lab Backend 的實際查詢，不是示意圖。

![Grafana Tempo 實際查到的 Day 20 trace。根 span 是 invoke_agent sre-investigation-agent，child span 是 execute_tool delete_demo_database，兩者共用 trace ID。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r1/assets/screenshots/day-20/tempo-agent-tool-trace.png)

## Trace 還原路徑，Governance Event 還原責任

Trace 已能說明 Agent 呼叫 Tool 的順序與耗時。系統若只想除錯「為什麼慢」或「哪一跳失敗」，它已經很有用。事故調查若要知道當時的授權依據，還要回到 Governance Event。

本次事件使用 `Governed Action Field Set v0.1`。以下只保留責任鏈的核心結構：

```json
{
  "action_id": "act-day20-a669406b17ca",
  "correlation": { "trace_id": "8e5b...", "span_id": "5332..." },
  "principal": {
    "id": "user/sre-oncaller",
    "assurance": "VERIFIED",
    "source": "lab-fixture-idp"
  },
  "delegation": {
    "actor_chain": [
      "user/sre-oncaller",
      "agent/sre-investigation-agent",
      "workload/sre-investigation-agent"
    ]
  },
  "agent": { "name": "sre-investigation-agent", "artifact_digest": "sha256:d20a..." },
  "policy": { "id": "tool-boundary", "version": "v3", "decision": "ALLOW" }
}
```

Human Principal 由 Fixture IdP 提供，因此 Assurance 可以標為 `VERIFIED`。Workload 只有 Runtime Fixture 自行聲明，沒有接 SPIFFE、Cloud Workload Identity 或其他可驗證來源，所以刻意標為 `ASSERTED`。若兩者都寫成 `VERIFIED`，Dashboard 會更整齊，證據卻會變差。

Loki 保存同一份完整 Event。公開截圖的 LogQL 只移除 Python SDK 自動附加的本機 Source Path，Principal、Delegation、Policy、Result、Trace ID 與 Action ID 都保留。

![Grafana Loki 實際查到的 Day 20 governance event。事件包含 action ID、Agent Artifact digest、trace/span correlation、Human 到 Agent 與 Workload 的 actor chain、policy version 與 principal assurance。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r1/assets/screenshots/day-20/loki-governance-event.png)

## Tool 回成功後，還要看 Effect

Agent 系統很容易把多層結果壓成 `success=true`。Gateway 收到 `200`、MCP 回傳合法 Result、Runtime 完成 Workflow，以及下游資源真的改動，是四件可能同時有不同答案的事。

本次 Receipt 的 `status` 是 `CANARY_TRIGGERED`，只表示 Tool Adapter 走到預定 Canary Branch。Governance Event 另外保存：

```json
{
  "status": "CANARY_TRIGGERED",
  "effect": {
    "kind": "NO_OP_CANARY",
    "status": "SIMULATED",
    "count": 0
  }
}
```

流程成功不會把不存在的刪除寫成成功副作用。這個分法會一路用到 Day 25。屆時相同的 HTTP `200` 可能裝著 HTML、資訊不足的 MCP Result，或真正沒有產生預期 Effect。現在先拆開 Transport、Workflow Result 與 Domain Effect，後面才不會用一個綠色狀態蓋掉三種問題。

## 缺少 Policy Version 的事件直接拒收

欄位表只放在文章裡，很快就會變成「有空再補」。Lab 將 Contract 做成 JSON Schema，治理事件送出前必須通過驗證。負向案例刻意刪掉 `policy.version`，結果為 `REJECTED`。

只保存 `decision=ALLOW` 無法重建事故。Policy 可能隔天已被修改，Event 沒有 Version 或其他 Immutable Reference 時，調查者只能拿現在的規則猜測當時發生什麼。我寧可在 Ingestion 前拒收，也不想讓一筆看似完整、實際無法重建的 Audit Event 悄悄進庫。

完整欄位、來源與建議放置位置收在 [Governed Action Field Set v0.1 放置指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17-r1/articles/day-20/governed-action-field-guide.md)。Machine-readable Schema 與實際 Evidence 也留在公開 Repo，讀者可以修改 Fixture，觀察缺少哪一欄會被擋下。

## OpenTelemetry 搬運資料，不定義組織責任

[OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) 能以 Trace／Span Context 關聯 Log，也能用 `EventName` 表達離散事件。這足以承載 Day 20 的 Governance Event，不需要為了 Audit 再造一套無法與 Trace 關聯的 Transport。

欄位語意仍要保持邊界。[OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) 目前仍標示為 Development。Lab 只在 Span 上使用合適的 `gen_ai.operation.name`、`gen_ai.agent.*` 與 `gen_ai.tool.*`。`principal.assurance`、Delegation、Policy Version 與 Effect 是本系列的作者定義，在 Span Attribute 使用 `ithelp.governance.*` Prefix，不冒充官方標準。

Application Record、Trace 與 Governance Event 共用 ID，也不表示三份資料一定要進相同 Backend 或使用同一 Retention。正式環境還要處理 Writer Trust、Redaction、Access Control、Retention 與 Tamper Resistance。Day 20 先確定要保存什麼，以及哪一種資料負責回答什麼。

## 下一篇讓資料跨過每一個 Producer

Lab 04 目前只驗一筆 Deterministic Action 與兩種 Backend Signal，沒有假裝部署完整的 ADK／kagent、agentgateway 與 MCP 路徑。先讓欄位 Contract 穩定，再增加 Producer，才能看出哪一跳真的有送資料、哪一欄只是後端猜出來的。

Day 21 會把範圍擴大到完整 Telemetry Pipeline。Agent Gateway 能看到 Data-plane Traffic，Runtime 知道 Agent 內部步驟，MCP Adapter 才可能拿到 Tool Result 與 Effect。這些訊號會一起經過 Alloy 進入 Tempo、Loki 與 Metrics Backend，並以固定情境檢查 Correlation 是否真的跨過每一跳。

# Day 20｜從 LLM Observability 到 Agent Traceability：一筆 Tool Call 需要哪些觀測資料

知道平台部署了哪一版 Agent，仍然不知道某次 Tool Call 是誰要求、哪條規則放行，以及 Tool 最後做了什麼。把視角從部署移到執行時，我又回到系列開頭那筆危險動作：值班工程師請 SRE Agent 調查異常，模型卻提出 `delete_demo_database`。

產品介面可能顯示「Tool Call 成功」，Tempo 也可能畫出 Agent 底下接著 Tool 的兩段 Trace。值班的人仍會追問：這次是誰發起？當時哪條規則放行？Tool 回成功，資料庫真的被改了嗎？Day 20 要補的不是更多 Dashboard，而是讓這三個問題各有能查證的資料來源。

今天先用一筆固定的安全示範，分清產品介面、系統執行路徑和授權結果各自該留下什麼。下一篇再讓這些資料跨過真正的 Gateway、Runtime 與 MCP 服務。

## 從模型狀態追到 Agent 行動

我在 2025 年鐵人賽寫的是 [LLM 可觀測性](https://ithelp.ithome.com.tw/articles/10380029)。Prompt、Response、Token、Latency、Cost、Evaluation 與 Trace 到現在依然重要，尤其在模型品質、費用或應用流程出問題時，這些資料仍是調查起點。

Agent Telemetry 已經多出另一層問題。以 [Claude Code Monitoring](https://code.claude.com/docs/en/monitoring-usage) 為例，官方已能輸出 Tool Decision、Tool Result、Permission、MCP 與 Subagent 等活動。工具把事件送出來後，值班的人仍要分清誰發起、哪個元件做了決定，以及結果落在什麼資源上。

我在做 [`grafana-claudestats-app`](https://github.com/MikeHsu0618/grafana-claudestats-app) 時，也把 Claude Code 與 Codex 的 OpenTelemetry 接進 LGTM。Cost、Token、Tool、Skill、Trace 和操作活動都能看，Activity 頁還能對回程式碼修改、Commit 與 PR。這讓我看到一個很實際的轉變：只追模型用量，和值班時能還原工具做過哪些動作，是兩種不同的需求。Code Agent 是我的另一個實作場景。以下的主角仍是系列裡的 Google ADK SRE Agent。

![grafana-claudestats-app 的 Overview 畫面。成本、Token 與 Session 適合掌握使用情況，還不能單獨回答一次工具操作的責任。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r2/assets/screenshots/day-20/claude-code-stats-overview.png)

Overview 很適合回答「這個團隊用了多少」，Activity 才開始回答「這段時間做了哪些事」。接下來的 SRE Agent 又多了 Resource 和 Policy：只看 Activity 清單，仍不足以重建一次高風險 Tool Call。

![grafana-claudestats-app 的 Activity 畫面。程式碼變更、Commit 與 PR 提供 Code Agent 的操作脈絡，畫面使用可公開的測試資料。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r2/assets/screenshots/day-20/claude-code-stats-activity.png)

## 一筆 Action 需要三種不同資料

我把 Day 20 的資料分成 Application Record、Operational Telemetry 與 Governance Event。三者以 `action_id` 關聯，Trace 與 Governance Event 另外共用 Trace Context。它們不該被塞進同一種萬用紀錄，因為使用者、保存時間、查詢方式與存取權限都不同。

![同一筆 Agent action 分成 Application Record、Operational Telemetry 與 Governance Event。Application Record 保存產品脈絡，Operational Telemetry 保存執行路徑與健康狀態，Governance Event 保存 verified principal、delegation、Artifact、policy 與 effect。三者用 action ID 關聯，trace ID 只連接 trace 與治理事件。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r2/assets/diagrams/day-20/traceability-data-boundary.png)

**Application Record** 服務產品介面與使用歷程，Session、Generation、Model、Tool 摘要都很合理。它也可能知道畫面上的使用者是 `user/sre-oncaller`。這個值若只來自 Frontend Session 或 Request Body，就只能叫 `actor_hint`。把欄位重新命名為 `principal`，不會讓它突然具備驗證證據。

**Operational Telemetry** 說明系統如何執行。Trace 保存父子 Span、Latency、Error、Service 與 Route，Metrics 觀察整體趨勢，Logs 補充離散事件。這些訊號可以投影有限的 Identity Attribute，卻不能因為 Span 上出現 `user.id`，就宣告完整 Audit 已經完成。

**Governance Event** 面向資安、稽核、事件調查與平台 Owner。它需要 Principal 的 Assurance 和來源、Delegation Chain、Executing Workload、Agent Artifact Digest、Target Resource、Policy ID／Version／Decision、Approval，以及 Tool 回報的 Effect。這份資料通常有更嚴格的寫入權限、保存期與完整性要求，也不適合把 Raw Prompt 或完整 Tool Output 全部塞進去。

## 用固定動作檢查欄位

Day 1 的 Gemini Live Run 已出現危險 Tool Call。這次我把模型選 Tool 的步驟固定下來，讓每次重跑都能比較同一筆動作留下哪些欄位，不必先排除模型輸出變化。

Lab 04 固定執行一筆 Deterministic No-op Canary。Tool 名稱仍是 `delete_demo_database`，程式不會連資料庫、Shell、Kubernetes 或外部 API，只寫出 `CANARY_TRIGGERED` Receipt，`side_effects` 固定為 `0`。讀者不需要 Gemini Key，也能重現同一筆 Action。

```bash
make lab-04-up
make lab-04-check
make lab-04-run
```

Runner 產生 Application Record、Operational Trace、Governance Event 與 Tool Receipt，Trace 和 Event 再透過 OTLP/HTTP 送進 Alloy。Tempo 和 Loki 最後都能用同一組 `action_id`、`trace_id` 找回這次動作。

Tempo 裡有兩個 Span。上層是 `invoke_agent sre-investigation-agent`，下層才是 `execute_tool delete_demo_database`。這張 Grafana Waterfall 來自 Lab Backend 的實際查詢，不是示意圖。

![Grafana Tempo 實際查到的 Day 20 trace。根 span 是 invoke_agent sre-investigation-agent，child span 是 execute_tool delete_demo_database，兩者共用 trace ID。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r2/assets/screenshots/day-20/tempo-agent-tool-trace.png)

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

Human Principal 由 Fixture IdP 提供。Workload 則只有 Runtime Fixture 自行填入。兩個值出現在同一份 Event，來源卻不同，所以欄位分別寫 `VERIFIED` 和 `ASSERTED`。事故調查若要追到實際 Pod，還得另外接上可信的 Workload Identity，不能從這份 Fixture 推回正式環境。

Loki 保存同一份完整 Event。公開截圖的 LogQL 只移除 Python SDK 自動附加的本機 Source Path，Principal、Delegation、Policy、Result、Trace ID 與 Action ID 都保留。

![Grafana Loki 實際查到的 Day 20 governance event。事件包含 action ID、Agent Artifact digest、trace/span correlation、Human 到 Agent 與 Workload 的 actor chain、policy version 與 principal assurance。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r2/assets/screenshots/day-20/loki-governance-event.png)

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

如果事件只留下 `decision=ALLOW`，隔天 Policy 一改，值班的人就只能拿新規則猜昨天發生什麼。Lab 因此要求事件帶 `policy.version`。刪掉它時，JSON Schema 在送出前便拒收。

這種拒收比事後發現事件只剩一個 `ALLOW` 好處理得多。Policy Owner 可以當場修 Producer，值班的人也不用在事故發生後再追一份當時根本沒記下來的規則。

完整欄位與放置位置收在 [Governed Action Field Set v0.1 放置指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20-r2/articles/day-20/governed-action-field-guide.md)。想重跑的人可以直接改 Fixture，看看拿掉 Policy Version 之後事件在哪裡被擋下。

## OpenTelemetry 搬運資料，不定義組織責任

[OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) 能以 Trace／Span Context 關聯 Log，也能用 `EventName` 表達離散事件。這足以承載 Day 20 的 Governance Event，不需要為了 Audit 再造一套無法與 Trace 關聯的 Transport。

欄位語意仍要保持邊界。[OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) 目前仍標示為 Development。Lab 只在 Span 上使用合適的 `gen_ai.operation.name`、`gen_ai.agent.*` 與 `gen_ai.tool.*`。`principal.assurance`、Delegation、Policy Version 與 Effect 是本系列的作者定義，在 Span Attribute 使用 `ithelp.governance.*` Prefix，不冒充官方標準。

Application Record、Trace 與 Governance Event 共用 ID，也不表示三份資料一定要進相同 Backend 或使用同一 Retention。正式環境還要處理 Writer Trust、Redaction、Access Control、Retention 與 Tamper Resistance。Day 20 先確定要保存什麼，以及哪一種資料負責回答什麼。

## 下一篇讓資料跨過每一個 Producer

Day 20 的兩個 Span 由同一個 Runner 產生，還沒有跨服務。這樣先能決定欄位和事件怎麼寫。等 Gateway、Runtime 與 MCP 分開部署，才看得出哪一跳會把 Trace Context 或動作資訊弄丟。

Day 21 會把範圍擴大到完整 Telemetry Pipeline。Agent Gateway 能看到 Data-plane Traffic，Runtime 知道 Agent 內部步驟，MCP Adapter 才可能拿到 Tool Result 與 Effect。這些訊號會一起經過 Alloy 進入 Tempo、Loki 與 Metrics Backend，並以固定情境檢查 Correlation 是否真的跨過每一跳。

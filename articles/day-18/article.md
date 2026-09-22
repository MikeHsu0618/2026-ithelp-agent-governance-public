# Day 18｜實測 kagent BYO Agent：讓外部 Agent 接入 A2A 生態

Day 17 已把 A2A 的 Agent Card、Routing 與 Invocation 接通，下一步是把自建 Agent 放回 kagent，看看其他 Agent 能否把它當成平台的一員使用。多一條能成功回應的 API，已經不足以回答我們會不會採用這套架構。

我會追這條 BYO 路徑，是因為實際使用 kagent 後一直卡著一個不滿。Declarative Runtime 建在 Google ADK 上，部署 Agent 與 MCP 很方便，可宣告的參數卻未必接得住 Provider-specific Reasoning 與進階 Workflow。A2A 能讓 Agent 互相呼叫，Runtime 本身若太弱，協定再完整也救不了裡面的工作流程。

自己用 ADK 或其他 Framework 寫 Agent，再以 BYO 方式註冊回平台，於是成為很自然的下一步。這篇真正要驗的是：kagent UI 看得到一張 BYO Agent Card，究竟只讓使用者比較容易找到它，還是真的減少了自訂 Runtime 的開發與維運責任。

## BYO 保留 Runtime 自主權

kagent 的 [BYO Agent 文件](https://kagent.dev/docs/kagent/examples/a2a-byo/) 將合約訂得很清楚。開發者提供一個支援 A2A、監聽 `8080` 的 Container Image，kagent 依 `Agent` Custom Resource 建立 Deployment 與 Service，ServiceAccount 則由 Controller 建立或引用既有 Resource。Agent 會出現在平台的 Discovery Surface，也能被其他 Agent 當成 Tool 呼叫。

這種模式吸引我的地方不是少寫幾行 YAML，而是 Runtime 不再受限於 Declarative Surface。我可以自行選擇 Google ADK、LangGraph 或內部 Framework，Planning、State Machine 與 Tool Callback 都留在程式碼裡。代價也很清楚，這些能力不會因為 Image 被 kagent 部署，就突然改由 Control Plane 負責。

回查 `0.10.1` 的 [`Agent` API Source](https://github.com/kagent-dev/kagent/blob/v0.10.1/go/api/v1alpha2/agent_types.go)，`Memory` 與 MCP Tool 的 `requireApproval` 位於 Declarative Spec，BYO Spec 則主要描述 Deployment。頂層 `skills` 與 `sandbox` 可以提供資料或 Resource，BYO Runtime 仍須主動消費。兩種模式從 API 結構開始就有不同 Owner，不是少勾一個選項而已。

## 平台部署 Agent，Runtime 提供實際能力

Lab 在 Disposable Kind Cluster 放入兩個 Agent。`day18-parent` 是 Declarative Agent，負責把資源變更交給同 Namespace 的 `day18-byo`。BYO Image 以 Google ADK 實作 `change_demo_resource` Tool，只回傳 Action Receipt，不會修改 Kubernetes 或其他外部服務。

![kagent control plane 依 BYO Agent CR 建立 Deployment、Service、連接 ServiceAccount，並維護註冊與 Ready status。Agent Card 則由 BYO Runtime 提供。實際路徑由 A2A probe 呼叫 declarative parent，parent 以 Agent-as-Tool 經 agentgateway 到 Google ADK BYO Agent，再由 Runtime 的 Tool callback 處理 input-required 與 approve 或 reject。圖下方分開列出平台接手的 lifecycle、discovery、入口，以及 BYO 作者仍負責的 workflow、HITL callback、memory 與 Tool policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30-r1/assets/diagrams/day-18/byo-platform-boundary.png)

kagent 依 Agent CR 建立 Workload、Service 並維護 Ready Status，Agent Card 的內容與實際回應則由 BYO Runtime 提供。執行時，Parent 透過 agentgateway 呼叫 BYO Agent，Tool 的 Approval Callback 也留在 BYO Runtime 裡。

本輪事先定義五個驗收條件：

- BYO Agent Card 可以讀取。
- Declarative Parent 確實透過 Agent-as-Tool 呼叫 BYO Child。
- Approve 後 Task 從 `input-required` 續跑到 `completed`，Tool 回傳 `ACTION_EXECUTED`。
- Reject 後 Task 正常結束，只回傳 `ACTION_SKIPPED`。
- Approve Receipt 保留 `actor=sre-oncaller`。

Parent Model 與 BYO Model 都使用 Deterministic Fixture，不需要 Gemini 或 OpenAI Key。這樣可以把判讀焦點留在 Runtime Boundary，不讓模型回答的隨機性干擾 HITL 與 Identity 結果。

## Agent-as-Tool 仍需要 Gateway Route

BYO Pod Ready 後，Parent 的第一次 Agent-as-Tool 呼叫依然失敗。kagent 產生的 Remote Agent 設定把 URL 指向 agentgateway Proxy，並帶入：

```text
x-kagent-host: day18-byo.day18-lab
```

Gateway 當時沒有對應 Route，Parent 讀 `/.well-known/agent-card.json` 得到 `404`。這與 Day 17 的 Public A2A Prefix 是不同問題。BYO Agent 已有自己的 Service，但 Controller 將內部 Agent-as-Tool 收進共同 Proxy 後，Gateway 必須知道這個 `x-kagent-host` 應送到哪個 A2A Backend。

Lab 最後加入 Header Exact Match，將 `day18-byo.day18-lab` 送到 BYO A2A Backend。Route 生效後，Agent Card GET、Task 的 `input-required` 與最後的 `completed` 都落在相同 Backend。完整 [Gateway Route](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-30-r1/labs/03-gateway-runtime/configs/day-18/kagent-resources.yaml) 留在 Repo，正文不再複製整段 YAML。

agentgateway Access Log 也留下 A2A Method、Response Outcome、Task State 與 Context。它能成為 A2A Traffic Checkpoint，卻看不到 Runtime 為何要求批准，也不知道 Approver 是否有權修改 `demo/cache`。Traffic Telemetry 與 Business Authorization 仍是兩份責任。

## HITL Pause 與 Resume 由 Runtime 真正執行

這次 HITL 不是在 Prompt 裡多問一句「確定嗎」。Google ADK Tool Callback 呼叫 `request_confirmation()`，BYO Task 先回 `input-required`。Parent 的 Agent-as-Tool 收到狀態後，將 Approval 帶回上層 Task。使用者選擇 Approve 或 Reject，兩層 Task 才沿著相同 Task／Context 繼續執行。

![使用者先向 declarative parent 送出請求，parent 經 agentgateway 呼叫 BYO Agent。BYO Runtime 在 Tool callback 呼叫 request_confirmation，child 與 parent task 依序停在 input-required。使用者沿用同一組 task ID 與 context ID 回覆 approve 或 reject 後，請求再經 parent 與 Gateway 回到 BYO Runtime。Approve 會執行 Tool 並回傳 ACTION_EXECUTED，reject 不執行 Tool 並回傳 ACTION_SKIPPED，兩條路徑最後都進入 completed。圖中另標示 kagent-adk 負責傳遞 pause 與 resume，BYO Runtime 負責 approval callback，而 approver authorization 不在本次測試範圍。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30-r1/assets/diagrams/day-18/hitl-pause-resume.png)

kagent `0.10.1` 的 [Release Notes](https://github.com/kagent-dev/kagent/releases/tag/v0.10.1) 包含 Python Agent HITL Resume 與 A2A User Identity Propagation 的修正，因此 Lab 鎖定這一版。從 [`_remote_a2a_tool.py`](https://github.com/kagent-dev/kagent/blob/v0.10.1/python/packages/kagent-adk/src/kagent/adk/_remote_a2a_tool.py) 也能對回 Child 回傳 `input_required` 後，Parent 建立 Confirmation，再沿 Task 與 Context 續跑的過程。

這份互通有一個重要前提：BYO Agent 使用相容的 `kagent-adk`，而且 Runtime 自己實作 Approval Callback。換成其他 A2A Implementation 時，平台仍能提供 Discovery 與 Invocation，HITL Payload、Session Store 和 Resume Semantics 則要由該 Runtime 對齊。Declarative MCP Tool 的 `requireApproval` 不會自動套進 BYO Image。

## Actor 傳到 Tool，不等於身分已受信任

Approve 路徑最後回傳：

```text
parent-complete ACTION_EXECUTED resource=demo/cache actor=sre-oncaller
```

這筆 Receipt 證明 Request 通過 Parent、agentgateway 與 BYO Child 後，ADK Session 仍拿得到相同 Actor。它沒有證明任意 `x-user-id` 都值得信任。公開 Lab 為了專注在 Propagation，主動送入合成 Header。正式環境仍要先由 Gateway 或前置 Authentication Boundary 驗證 Credential，再建立可信的 User Identity。

Header 只是載體，Issuer、Audience、Delegation 與 Offboarding Lifecycle 才決定它能否成為授權依據。Day 18 只把「跨兩層 Agent 沒有弄丟 Actor」標為 PASS，沒有把它擴寫成完整 Delegation 或 Approver Authorization 已完成。

## 能力矩陣分開平台便利與 Runtime 責任

完整的 [BYO Agent 平台能力驗收表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-30-r1/articles/day-18/platform-capability-matrix.md) 有十二項結果，正文只留下最影響採用判斷的部分：

| 能力 | 結果 | 責任邊界 |
| --- | --- | --- |
| Deployment／Service／ServiceAccount | PASS | kagent 管 Workload Lifecycle，Application Team 管 Image 與 Security Baseline |
| Agent Card／UI Discovery | PASS | 找得到，不代表 Runtime Semantics 已通過 |
| 同 Namespace Agent-as-Tool | PASS | agentgateway 仍需通往 BYO A2A Endpoint 的 Route |
| HITL Approve／Reject／Resume | PASS | `kagent-adk` 可互通，Callback 由 BYO 實作，Approver Authorization 未測 |
| Synthetic Actor Propagation | PASS | Actor 沒有遺失，入口 Authentication 未包含在本次測試 |
| Gateway A2A Telemetry | PASS | 看得到 Request 與 Task 外層，看不到 Tool 授權理由 |
| Long-term Memory | NOT_TESTED | HITL Session Continuity 不等於長期記憶 |
| Tool Policy／Argument Authorization | PARTIAL | Reject 能擋這支 Tool，細粒度 Resource Policy 未實作 |
| Tool Execution Sandbox | NOT_TESTED | Hardened Pod 不等於每次 Tool Call 有獨立 Sandbox |

UI 同時列出 BYO Agent 與 Declarative Parent。對使用者來說，這已省掉手動尋找 URL、閱讀 Agent Card 與自行接 Client 的工作。回到 Runtime 作者這一側，程式碼、Dependency、Memory、Tool Policy、Filesystem 與 Framework Upgrade 一項都沒有消失。

![kagent UI 的 Agents 頁面。day18-lab namespace 內同時顯示 BYO Google ADK Agent 與 declarative parent，BYO 卡片標出實際部署的 image。畫面也保留前一天 Lab 的 day16 Agent。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30-r1/assets/screenshots/day-18/01-kagent-agents.png)

## Lab 只把五項能力標成通過

[Lab 03 的 Day 18 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-30-r1/labs/03-gateway-runtime/README.md) 會建立 Disposable Kind Cluster，部署 kagent、agentgateway、Declarative Parent 與 BYO Agent，再執行 Approve／Reject 兩條路徑：

```bash
make lab-03-runtime-byo
```

![Day 18 Lab terminal card。BYO Agent Card、declarative parent 呼叫 BYO child、HITL approve、HITL reject 與 actor propagation 五項全部通過，下方保留 approve 與 reject 的實際 receipt。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30-r1/assets/screenshots/day-18/02-byo-platform-results.png)

結果是 Agent Card、Agent-as-Tool、HITL Approve、HITL Reject 與 Synthetic Actor Propagation 五項通過。Approve Receipt 為 `ACTION_EXECUTED resource=demo/cache actor=sre-oncaller`，Reject Receipt 則只有 `ACTION_SKIPPED decision=rejected`。Reject Path 另外確認沒有出現 `ACTION_EXECUTED`，避免把「Task 最後 Completed」誤讀成 Tool 仍被執行。

完整 Task／Context Continuity、Redacted Evidence、Pod Security 與重跑步驟都留在 Repo。它們支撐結果，但不再讓正文變成 Kind Cluster 的安裝與驗收手冊。

## BYO 解決接入，不會消除自建成本

BYO 讓我保留自建 Agent 的彈性，又能把 Deployment、Discovery 與 Agent-as-Tool 入口交給 kagent。這比每支 Agent 各自維護 Endpoint 與 Client 有價值，也說明 A2A 並非只剩協定格式。

這份方便主要發生在「別人如何找到並呼叫我的 Agent」。Agent 內部如何 Planning、Memory、Approval 與隔離執行，仍是 Runtime 的工程成本。甚至 HITL 能順利 Pause／Resume，也只證明 Runtime 和平台在這條路徑上相容，沒有證明 Approver 身分與 Resource Policy 已經完整。

平台現在已經找得到這個 Agent，也真的叫得動它。下一個缺口不再是 Connectivity，而是 Image 從哪裡來、版本能否重現、誰批准 Promotion，以及這份 Artifact 是否值得被其他 Agent 使用。Day 19 會回到我曾部署又拆除的 Agent Registry，看看現行版本能替這條信任鏈補上多少資料。

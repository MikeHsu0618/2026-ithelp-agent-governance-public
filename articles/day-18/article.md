# Day 18｜BYO Agent 接回 kagent：從部署、A2A 到 HITL 的實測邊界

Day 17 把 A2A 的 Agent Card、routing 與 invocation 接通之後，下一步就是把自建 Agent 放回 kagent，看看其他 Agent 能不能把它當成平台裡的一員直接使用。多一條成功的 API 已經無法回答我們會不會採用這套架構。

我會追這條 BYO 路徑，是因為實際用過 kagent 後一直卡著一個不滿。當時的 declarative runtime 建在 Google ADK 上，部署 Agent 與 MCP 很方便，可宣告的參數卻接不住我們需要的 provider-specific reasoning 與進階 workflow。A2A 當然能讓 Agent 互相呼叫，可是 Runtime 本身太弱時，協定再完整也救不了 Agent 裡面的工作流程。自己用 ADK 或其他 framework 寫完，再以 BYO 方式註冊回平台，於是成了很自然的下一條路。

問題也跟著變得更具體：kagent UI 看得到一張 BYO Agent 卡片，究竟只是方便使用者找到它，還是真的減少了開發與維運自訂 Runtime 的負擔？本篇用 kagent `0.10.1`、agentgateway `1.5.0` 與一個 Google ADK-based BYO Agent，實際驗 Agent-as-Tool、HITL approve／reject／resume、身分傳遞和 Kubernetes lifecycle。這次不拿功能表猜答案。

## BYO 保留的是 Runtime 自主權

kagent 的 [BYO Agent 文件](https://kagent.dev/docs/kagent/examples/a2a-byo/)把合約訂得很清楚：開發者提供一個會說 A2A、監聽 `8080` 的 container image，kagent 依 `Agent` custom resource 建立 Deployment 與 Service，ServiceAccount 則可由 controller 建立或引用既有資源。Agent 會出現在平台的 discovery surface，也能被其他 Agent 當成 Tool 呼叫。

這種模式對我的吸引力不在少寫幾行 YAML，而是 Runtime 不必被 declarative surface 限住。我可以自己選 Google ADK、LangGraph 或內部 framework，planning、state machine、Tool callback 也留在程式碼裡。代價是這些能力不會因為 image 被 kagent 部署，就突然改由 control plane 負責。

查回 `0.10.1` 的 [`Agent` API source](https://github.com/kagent-dev/kagent/blob/v0.10.1/go/api/v1alpha2/agent_types.go)，`Memory` 與 MCP Tool 的 `requireApproval` 都位於 declarative spec，BYO spec 則主要描述 deployment。頂層 `skills` 與 `sandbox` 可以提供資料或資源，但 BYO Runtime 仍得主動消費。兩種 Agent 模式從 API 結構開始就有不同 owner，不是少做一個 checkbox 而已。

## Lab 拓撲與驗收條件

`Lab` 這次在 disposable kind cluster 放入兩個 Agent。`day18-parent` 是 declarative Agent，會把資源變更交給註冊在同一個 namespace 的 `day18-byo`。BYO image 以 Google ADK 實作一個 `change_demo_resource` Tool。它只回傳 action receipt，不會修改 Kubernetes 或任何外部服務。

把 control plane 與 runtime path 分開畫，責任就清楚了。kagent 會依 Agent CR 建立 workload、Service 並完成平台註冊，Agent Card 的內容與實際回應仍由 BYO Runtime 提供。執行時，parent 透過 agentgateway 呼叫 BYO Agent，Tool 的 approval callback 也留在 BYO Runtime 裡。

![kagent control plane 依 BYO Agent CR 建立 Deployment、Service、連接 ServiceAccount，並維護註冊與 Ready status。Agent Card 則由 BYO Runtime 提供。實際路徑由 A2A probe 呼叫 declarative parent，parent 以 Agent-as-Tool 經 agentgateway 到 Google ADK BYO Agent，再由 Runtime 的 Tool callback 處理 input-required 與 approve 或 reject。圖下方分開列出平台接手的 lifecycle、discovery、入口，以及 BYO 作者仍負責的 workflow、HITL callback、memory 與 Tool policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/diagrams/day-18/byo-platform-boundary.png)

Probe 固定送出合成 principal `sre-oncaller`，先要求 parent 呼叫 BYO Agent，再分別回覆 approve 與 reject。五個驗收條件如下：

- BYO Agent Card 可以讀取。
- Declarative parent 確實透過 Agent-as-Tool 呼叫 BYO child。
- Approve 後 task 從 `input-required` 續跑到 `completed`，Tool 回傳 `ACTION_EXECUTED`。
- Reject 後 task 同樣正常結束，但回覆只有 `ACTION_SKIPPED`。
- Approve receipt 仍保留 `actor=sre-oncaller`。

本次使用 synthetic parent model 與 deterministic BYO model，整個 Lab 不需要 Gemini 或 OpenAI key。這樣可以把測試焦點留在 runtime boundary，而不是讓模型回答的隨機性干擾判讀。

啟動 BYO Pod 時還碰到一個很能說明責任邊界的小插曲。Image 已設成 non-root、移除 Linux capabilities，Root Filesystem 也改成唯讀，`kagent-adk` 卻因為找不到可寫的暫存目錄而直接退出。最後保留 `readOnlyRootFilesystem: true`，只用限制為 `64Mi` 的 `emptyDir` 補上 `/tmp`。這不是本篇要教的 Kubernetes 技巧，完整 YAML 與 ServiceAccount token 設定會留在 Lab 的 [`kagent-resources.yaml`](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20/labs/03-gateway-runtime/configs/day-18/kagent-resources.yaml)。正文只留下它帶來的判斷：kagent 可以接手 rollout 與 readiness，BYO image 需要哪些 writable path，仍然得由 Runtime 作者說清楚。

## Agent-as-Tool 經過 agentgateway 的路由

Pod Ready 之後，parent 的第一次 Agent-as-Tool 呼叫仍然失敗。kagent 產生的 remote Agent 設定把 URL 指向 agentgateway proxy，並帶上這個 header：

```text
x-kagent-host: day18-byo.day18-lab
```

當時 Gateway 沒有對應 route，parent 讀 `/.well-known/agent-card.json` 得到 `404`。這跟 Day 17 的公開 A2A route 又是不同問題：BYO Agent 已經有自己的 Service，但 controller 將內部 Agent-as-Tool 收進共同 proxy 後，Gateway 必須知道 `x-kagent-host` 應該送去哪個 A2A backend。

Lab 最後加入一條明確的 header match：

```yaml
rules:
- matches:
  - headers:
    - name: x-kagent-host
      type: Exact
      value: day18-byo.day18-lab
    path:
      type: PathPrefix
      value: /
  backendRefs:
  - group: agentgateway.dev
    kind: AgentgatewayBackend
    name: day18-byo-a2a
```

route 生效後，Agent Card 的 GET，以及 task 的 `input-required`、`completed` 都落在 `day18-lab/day18-byo-a2a`。agentgateway access log 也留下 `protocol=a2a`、`a2a.method=message/send`、response outcome、task state 與 context。Gateway 因此能當 A2A traffic checkpoint，但它仍看不到 Runtime 為何要求批准，也不知道 approver 是否有權變更 `demo/cache`。

## HITL 續跑依賴 Runtime 互通

這次 BYO Agent 的 HITL 確實走完整的 pause 與 resume 流程，parent 不只是在 Prompt 裡問一句「確定嗎」。Google ADK Tool callback 呼叫 `request_confirmation()`，BYO task 先回 `input-required`。Parent 的 Agent-as-Tool 收到狀態後，把 approval 傳回上層 task。使用者選擇 approve 或 reject，兩層 task 才一起續跑。

![使用者先向 declarative parent 送出請求，parent 經 agentgateway 呼叫 BYO Agent。BYO Runtime 在 Tool callback 呼叫 request_confirmation，child 與 parent task 依序停在 input-required。使用者沿用同一組 task ID 與 context ID 回覆 approve 或 reject 後，請求再經 parent 與 Gateway 回到 BYO Runtime。Approve 會執行 Tool 並回傳 ACTION_EXECUTED，reject 不執行 Tool 並回傳 ACTION_SKIPPED，兩條路徑最後都進入 completed。圖中另標示 kagent-adk 負責傳遞 pause 與 resume，BYO Runtime 負責 approval callback，而 approver authorization 不在本次測試範圍。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/diagrams/day-18/hitl-pause-resume.png)

kagent `0.10.1` 的 [release notes](https://github.com/kagent-dev/kagent/releases/tag/v0.10.1)剛好包含 Python Agent HITL resume 與 A2A user identity propagation 的修正，因此本次 Lab 直接鎖這一版。從 [`_remote_a2a_tool.py`](https://github.com/kagent-dev/kagent/blob/v0.10.1/python/packages/kagent-adk/src/kagent/adk/_remote_a2a_tool.py)也能看到 child Agent 回 `input_required` 後，parent 如何建立自己的 confirmation，再沿 task 與 context 續跑。

這份互通成立有一個重要前提：BYO Agent 使用相容的 `kagent-adk`，而且 Runtime 自己寫了 approval callback。若換成另一套 A2A implementation，平台仍能 discovery 與 invocation，HITL payload、session store 和 resume semantics 則要由那個 Runtime 對齊。Declarative MCP Tool 上的 `requireApproval` 不會自動套進 BYO image。

## Identity 到了 Tool，信任仍從入口開始

Approve 路徑最後回傳：

```text
parent-complete ACTION_EXECUTED resource=demo/cache actor=sre-oncaller
```

Action receipt 證明本次呼叫通過 parent、agentgateway 與 BYO child 後，ADK session 裡仍拿得到同一個 actor。它沒有證明任意 `x-user-id` 都值得信任。公開 Lab 為了專注在 propagation，直接送出合成 header。正式環境必須先由 Gateway 或 controller 前面的 authentication boundary 驗證 credential，再建立可信的 user identity。

這也回到前面 Identity 幾篇留下的原則。Header 只是載體，issuer、audience、delegation 與 offboarding lifecycle 才決定它能不能成為授權依據。Day 18 只把「跨兩層 Agent 沒有弄丟 actor」標成 PASS，沒有把它擴寫成完整 delegation 已經完成。

## 能力矩陣：平台接手與 Runtime 自理

完整的 [BYO Agent 平台能力驗收表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20/articles/day-18/platform-capability-matrix.md)保留十二項結果。正文先列出對採用判斷最有影響的部分：

| 能力 | 結果 | 責任邊界 |
| --- | --- | --- |
| Deployment／Service／ServiceAccount wiring | `PASS` | kagent 管 workload lifecycle，Application Team 管 image 與 SA baseline |
| Agent Card／UI discovery | `PASS` | 找得到，不等於 Runtime semantics 已通過 |
| 同 namespace Agent-as-Tool | `PASS` | 需要 agentgateway 有通往 BYO A2A endpoint 的 route |
| HITL approve／reject／resume | `PASS` | `kagent-adk` 可互通，approval callback 由 BYO 實作，approver authorization 未測 |
| Synthetic actor propagation | `PASS` | 合成 actor 沒有遺失，入口 authentication 未包含在本次測試 |
| Gateway A2A telemetry | `PASS` | 看得到 request 與 task 外層，看不到 Tool 授權理由 |
| 長期 memory | `NOT_TESTED` | HITL session continuity 不等於長期記憶 |
| Tool policy／argument authorization | `PARTIAL` | Reject 能擋這支 Tool，細粒度 resource policy 尚未實作 |
| Tool execution sandbox | `NOT_TESTED` | hardened Pod 不等於每次 Tool Call 都有獨立 sandbox |
| 跨 namespace reference | `NOT_TESTED` | 本次只驗同 namespace，不用文件替實測補 PASS |

UI 畫面確實同時列出 BYO Agent 與 declarative parent。對使用者來說，這已經省掉手動找 URL、看 Agent Card 與接 client 的工作。回到 Runtime 作者這一側，程式碼、dependency、memory、Tool policy、filesystem 與 framework upgrade 一項都沒有消失。

![kagent UI 的 Agents 頁面。day18-lab namespace 內同時顯示 BYO Google ADK Agent 與 declarative parent，BYO 卡片標出實際部署的 image。畫面也保留前一天 Lab 的 day16 Agent。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-18/01-kagent-agents.png)

五項自動驗收的輸出如下。圖片方便快速讀結果，指令與文字 evidence 仍保留在 repo，Reject path 也明確檢查沒有 `ACTION_EXECUTED`。

```text
DAY 18 / BYO PLATFORM BOUNDARY

BYO Agent Card                       PASS
Declarative Agent -> BYO Agent       PASS
Nested HITL approve/resume           PASS
Nested HITL reject/resume            PASS
Synthetic actor propagation          PASS

approve-reply=parent-complete ACTION_EXECUTED resource=demo/cache actor=sre-oncaller
reject-reply=parent-complete ACTION_SKIPPED decision=rejected
rejected-without-execution=true
matched 5/5
```

![Day 18 Lab terminal card。BYO Agent Card、declarative parent 呼叫 BYO child、HITL approve、HITL reject 與 actor propagation 五項全部通過，下方保留 approve 與 reject 的實際 receipt。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20/assets/screenshots/day-18/02-byo-platform-results.png)

## 公開 Lab 的執行方式

[Lab 03 的 Day 18 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20/labs/03-gateway-runtime/README.md)會建立 disposable kind cluster，部署 kagent、agentgateway、declarative parent 與 BYO Agent，再執行 approve／reject 兩條路徑。需要 Docker Engine、Helm、kind `0.30.0`、kubectl `1.34.x` 與 uv：

```bash
make lab-03-runtime-byo
```

若想先觀察兩個 Agent 的 CR、Pod 與 UI，再手動跑 probe，可以拆成：

```bash
make lab-03-runtime-byo-up
make lab-03-runtime-byo-run
```

完成後刪除 Lab 自己建立的 cluster：

```bash
make lab-03-runtime-kagent-down
```

BYO 讓我保留自建 Agent 的彈性，又能把 deployment、discovery 與 Agent-as-Tool 入口交給 kagent。這比每支 Agent 各自維護 endpoint 與 client 有價值，也說明 A2A 並非只剩協定格式。不過這份方便主要發生在「別人如何找到並呼叫我的 Agent」。Agent 內部如何規劃、記憶、批准與隔離執行，仍然是 Runtime 的工程成本。

現在平台已經找得到這個 Agent，也真的叫得動它，下一個缺口就不是 connectivity。組織還需要知道 image 從哪裡來、版本能不能重現、誰批准 promotion，以及這份 Artifact 是否值得被其他 Agent 使用。Day 19 會回到我曾經部署又拆除的 Agent Registry，看看現行版本能替這條信任鏈補上多少證據。

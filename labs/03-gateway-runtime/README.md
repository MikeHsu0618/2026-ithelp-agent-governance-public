# Lab 03 — Gateway Credential 與 Traffic Boundary

Tested: 2026-09-05（Asia/Taipei）

| 欄位 | 內容 |
| --- | --- |
| Question | 都能通過 Gateway 的 key 與 JWT，是否具有相同的 identity、rotation、offboarding 與 audit 語意？ |
| Claim | Human virtual key 若未同步企業 IdP lifecycle，帳號停用後仍可能放行；static key 可作 workload consumer isolation；JWT 必須拒絕錯誤或缺少 issuer／audience 的 Token。 |
| Non-claim | API key 不是強 workload attestation；JWT 也不保證帳號停用後立刻撤銷既有 Token；本 Lab 不比較產品效能。 |
| Runtime | Python `3.14.5`、PyJWT `2.13.0`、agentgateway `v1.5.0` pinned image digest |
| Architecture | 一個 agentgateway、兩條 route、同一個 synthetic OpenAI-compatible backend |
| Start | Day 14：`make lab-03-runtime-up && make lab-03-runtime-run`；Day 15：`make lab-03-runtime-traffic` |
| Positive | active Human key、workload key、合法 Human JWT 都能抵達相同 backend。 |
| Negative | 停用 Human 後 stale key 仍被放行；retired workload key，以及 wrong／missing issuer、wrong／missing audience 的 JWT 得到 `401`。 |
| Evidence | `artifacts/<run-id>/evidence/`，只保存指紋、redacted config、公開 JWKS 與 decision table。 |
| Cleanup | `make lab-03-runtime-down` |

## Day 15：同一層 Gateway 的 traffic contract

Day 15 不在公開 Lab 前面再疊既有 Ingress。它沿用同一個 live agentgateway 與 synthetic backend，直接驗證責任切分後必須守住的 output property：

```bash
make lab-03-runtime-up
make lab-03-runtime-traffic
```

預期輸出：

```text
DAY 15 / TRAFFIC BOUNDARY

one agentgateway / retry disabled

normal-json                     HTTP 200  PASS
sse-stream                      HTTP 200  PASS
missing-caller-credential       HTTP 401  PASS
invalid-caller-credential       HTTP 401  PASS
upstream-rate-limit             HTTP 429  PASS
backend-credential-isolation    HTTP 200  PASS

matched 6/6
```

- SSE case 必須保留 `text/event-stream`，並依序收到 `lab-`、`ok`、`[DONE]`。
- 缺 caller credential 與錯誤 credential 都在 backend 前得到 `401`。
- Synthetic provider 回 `429` 與 `Retry-After: 7` 時，Gateway 保留兩者，而且上游 request count 等於一。
- Backend 收到 agentgateway 注入的 provider credential；caller key 沒有穿透。

這些結果不等於 production 雙層 proxy、Kubernetes controller、HA、MCP session 或 A2A streaming 已通過。Day 15 用單層 Lab 驗 traffic contract，實務 topology 則另用責任矩陣說明。

## Day 16：kagent control plane 與 agentgateway traffic path

Day 16 在獨立 kind cluster 安裝 kagent `0.10.0` 與 agentgateway `1.5.0`。Lab 不複製既有 Ingress，也不需要 Gemini／OpenAI key，只有一個 declarative Agent、一個固定回覆的 OpenAI-compatible backend，以及一個 read-only MCP fixture。

先跑不接觸 cluster 的靜態責任檢查：

```bash
make lab-03-runtime-up
make lab-03-runtime-kagent-plan
```

預期得到四項 `PASS`、兩項 `PARTIAL`。`PARTIAL` 是刻意保留的產品邊界：Secret-backed header 沒有證明 Token acquisition／refresh，單步 Agent 也沒有證明任意多步 workflow。

Live Kubernetes slice 需要 Docker Engine、Helm、kind `0.30.0` 與 kubectl `1.34.x`。它使用 `labs/03-gateway-runtime/.runtime/day-16/kubeconfig`，current context 必須精確等於 `kind-ithelp-day16`，不會讀取預設的 `~/.kube/config`：

```bash
make lab-03-runtime-kagent-up
make lab-03-runtime-kagent-invoke
```

若 kind 或 kubectl 不在預設 PATH，可以指定完整路徑：

```bash
make lab-03-runtime-kagent-up \
  KIND_BIN=/path/to/kind-v0.30.0 \
  KUBECTL_BIN=/path/to/kubectl-v1.34.0
```

實際 A2A 呼叫的預期摘要如下。Gateway request counter 會隨同一個 cluster 的重跑次數增加，因此驗收只要求大於零，不把累積數字當固定 fixture：

```text
a2a-state=completed
agent-reply=boundary-ok
discovered-tools=14
gateway-llm-requests=<positive integer>
gateway-mcp-requests=<positive integer>
```

Live slice 同時確認：

- `ModelConfig`、`RemoteMCPServer` 與 `Agent` 狀態被 kagent 接受，Agent deployment 進入 Ready。
- 生成的 model base URL 指向 agentgateway `/v1`，`reasoning_effort=low` 保留下來。
- 生成的 MCP URL 被改寫成 agentgateway `/mcp`，並帶有原始 Service 的 `x-kagent-host`。
- A2A 呼叫回覆 `boundary-ok`，agentgateway access log 同時看到 LLM 與 MCP route。
- 公開 evidence 只保存 redacted runtime config、狀態摘要與安全的 route 結果，不保存 raw header value。

MCP fixture 的 package version 與 base image digest 都在 `fixtures/day-16-mcp/` 固定。Image 會先在本機依 lockfile build，再載入 kind node，Pod 啟動時不會另外執行 `npx` 下載依賴。

完成後刪除這個 Lab 自己建立的 cluster：

```bash
make lab-03-runtime-kagent-down
```

Cleanup 會先核對獨立 kubeconfig 的 context，再刪除名稱精確等於 `ithelp-day16` 的 kind cluster。

## Day 17：A2A Discovery、Routing 與 Runtime Execution

Day 17 沿用同一個 disposable cluster，加入兩條通往 kagent controller 的 route。一般 HTTP backend 保留 controller 原始 Agent Card，用來重現 `controller.a2aBaseUrl` 重複 prefix；A2A-aware backend 則把 Card 的 interface URL 改寫成 Gateway 公開路徑 `/agents/day16`。

一條命令會先重現壞路徑，再恢復 host-only base URL 並驗證 A2A `1.0`：

```bash
make lab-03-runtime-a2a
```

負向案例的預期輸出：

```text
DAY 17 / A2A PATH

Agent Card                     HTTP 200 PASS
A2A 1.0 / SendMessage          HTTP 404 EXPECTED_FAIL
A2A 1.0 / SSE stream           HTTP 404 EXPECTED_FAIL

advertised-url=.../api/a2a/api/a2a/day16-lab/day16-agent
stream-events=NOT_REACHED

matched 3/3
```

正向案例除了 HTTP status，還要求一般 invocation 的 Task 進入 `TASK_STATE_COMPLETED`，SSE stream 使用同一組 task／context、出現最後一個 artifact chunk，並走到 completed：

```text
DAY 17 / A2A PATH

Agent Card                     HTTP 200 PASS
A2A 1.0 / SendMessage          HTTP 200 PASS
A2A 1.0 / SSE stream           HTTP 200 PASS

advertised-url=.../agents/day16
task-state=TASK_STATE_COMPLETED
agent-reply=boundary-ok
stream-events=SUBMITTED > WORKING > AGENT_MESSAGE > ARTIFACT(last) > COMPLETED
stream-last-chunk=true

matched 3/3
```

Probe 會明確送出 `A2A-Version: 1.0`，使用 `SendMessage` 與 `SendStreamingMessage`，並依 A2A `1.0` 的 `result.task`／SSE update shape 解析結果。Gateway log 還必須分別出現兩個 method，且一般 invocation 有 success outcome 與 completed task state。

若需要分步觀察，可依序執行：

```bash
make lab-03-runtime-a2a-reproduce
make lab-03-runtime-a2a-run
```

兩個 target 都會先確認 Day 16 cluster 與 route 狀態，因此分開呼叫會重跑 Helm reconciliation；要一次完成請優先使用組合 target。Day 17 沒有把 `INPUT_REQUIRED`／`AUTH_REQUIRED` 當成 live PASS，也沒有驗證 BYO Agent 或 HITL resume，這些留給 Day 18。

## Day 18：BYO Agent、Agent-as-Tool 與 HITL

Day 18 把 Google ADK Agent 打成自己的 image，再以 `type: BYO` 註冊到 kagent。另一個 declarative parent 將 BYO Agent 當成 Tool，兩者的 A2A traffic 經 agentgateway route。版本固定為 kagent／`kagent-adk` `0.10.1` 與 agentgateway `1.5.0`。

BYO Tool 只回傳 action receipt，不會修改 Kubernetes 或外部服務。Parent model 也是 deterministic OpenAI-compatible fixture，因此不需要外部 LLM API key：

```bash
make lab-03-runtime-byo
```

預期輸出：

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

這五項只驗證 discovery、同 namespace Agent-as-Tool、HITL pause／resume 與 synthetic actor propagation。Probe 會核對前後 task ID、context ID 與狀態，但沒有驗證 approver 是否有權批准。它們也不代表跨 namespace policy、長期 memory、skills materialization 或獨立 Tool execution sandbox 已通過。

若要保留 cluster 觀察 Agent CR、Pod、UI 與 Gateway log，可分兩步執行：

```bash
make lab-03-runtime-byo-up
make lab-03-runtime-byo-run
```

`byo-up` 會從一開始就以 kagent `0.10.1` 建立共用 runtime，不會先安裝舊版再升級。BYO base image 同時鎖定 `0.10.1` tag 與 manifest digest。Deployment 保留 read-only root filesystem，另掛載限制為 `64Mi` 的 `/tmp`。三個 workload 都透過預先建立的 ServiceAccount 停用預設 Kubernetes API token automount，兩個 Agent 仍保留 controller 所需、audience 為 `kagent` 的 projected token。

Agent-as-Tool 產生的 remote Agent URL 指向 agentgateway proxy，並帶 `x-kagent-host: day18-byo.day18-lab`。`configs/day-18/kagent-resources.yaml` 內的 `HTTPRoute` 會依這個 header 導到 BYO A2A backend。缺少 route 時，parent 讀取 Agent Card 會得到 `404`，這是本 Lab 保留在 evidence 裡的負向部署紀錄。

本機 `x-user-id: sre-oncaller` 是為了觀察 propagation 而送出的合成 header。Lab 的 kagent 使用 unsecure auth，這條 route 也沒有 AuthenticationPolicy，不能把結果解讀成 caller 已完成 authentication。正式環境必須先在可信入口驗證 credential，再建立不能由外部任意覆寫的 identity context。

完成後仍使用同一個 context guard 清除 disposable cluster：

```bash
make lab-03-runtime-kagent-down
```

## Day 19：Agent Registry 不是批准章

Day 19 另外建立一個 `ithelp-day19` kind cluster，安裝 Agent Registry `0.4.0` 與
kagent `0.10.1`。Lab 直接使用 Agent Registry 的 declarative API，不放 Argo CD，也不在
前面疊 Gateway。它要驗證的是 catalog 到 runtime 的 reconciliation，以及這條順暢路徑仍然
缺少哪些 trust controls。

需求為 Docker Engine、Helm、curl、kind `0.30.0` 與 kubectl `1.34.x`：

```bash
make lab-03-runtime-registry
```

也可以保留 cluster 分段觀察：

```bash
make lab-03-runtime-registry-up
make lab-03-runtime-registry-run
```

Probe 先用未帶 credential 的 `POST /v0/apply` 寫入 `day19byo@approved`，再透過
`Deployment` 將它轉成 kagent `Agent`。接著，Lab 不改 tag，只把 image reference 從
`1.0.0` 改成 `1.0.1`。controller 正常把新 image reconcile 到 runtime，這在功能上是成功，
在 provenance 上卻是一筆風險證據：`approved` 不是 immutable digest，也不是簽章。

預期輸出：

```text
DAY 19 / AGENT REGISTRY BOUNDARY

Anonymous catalog write                  RISK_EXPOSED
Tagged Agent readable                    PASS
Deployment reached kagent                PASS
Same approved tag changed image          RISK_EXPOSED
Declarative undeploy removed Agent       PASS

catalog-tag=approved
image-before=ithelp/day19-byo:1.0.0
image-after=ithelp/day19-byo:1.0.1
observed=5/5
risk-findings=2
```

最後一個 apply 將 `desiredState` 改為 `undeployed`，並確認帶有
`aregistry.ai/deployment-id=day19-agent` 的 kagent `Agent` 已經移除。公開 evidence 不包含
PostgreSQL credential、Kubernetes token、Registry row UID 或完整 cluster dump。

完成後刪除 Day 19 自己建立的 cluster：

```bash
make lab-03-runtime-registry-down
```

## 這個 Lab 刻意只放一層 Gateway

```text
Human virtual key ─┐
Workload key ──────┼─> agentgateway ─> provider key ─> synthetic LLM backend
Human JWT ─────────┘
```

三條 caller path 都打 `/v1/chat/completions`，也都到同一個 backend。差異只來自入口 credential policy：

- API key route 在 key 上掛 `human`、`workload` 與 `consumer` metadata。
- JWT route 驗 `iss`、`aud`、簽章、`token_use` 與 scope，再取 `sub`、`client_id`。
- backend policy 移除 caller credential，改注入另一把 provider key。

[可讀的 agentgateway 設定](configs/agentgateway.example.yaml)使用合成固定值，方便 review 與 `--validate-only`。真正執行時會在 temporary directory 產生新 API keys、RSA signing key 與 provider key；container 結束後整個 runtime directory 一併刪除。

## 一條命令跑完九個 case

需求只有 [uv](https://docs.astral.sh/uv/) 與正在運作的 Docker Engine：

```bash
make lab-03-runtime-up
make lab-03-runtime-run
```

實際輸出會落在 `labs/03-gateway-runtime/artifacts/<run-id>/evidence/terminal.txt`：

```text
DAY 14 / CREDENTIAL BOUNDARY

human-key-active                ALLOW  KEY_MAPPING_ACTIVE
human-key-after-offboarding     ALLOW  STALE_MAPPING_ALLOWED
workload-key                    ALLOW  WORKLOAD_KEY_ISOLATED
retired-workload-key            DENY   OLD_KEY_REJECTED
jwt-human                       ALLOW  JWT_PRINCIPAL_VERIFIED
jwt-wrong-issuer                DENY   JWT_ISSUER_REJECTED
jwt-wrong-audience              DENY   JWT_AUDIENCE_REJECTED
jwt-missing-issuer              DENY   JWT_ISSUER_REQUIRED
jwt-missing-audience            DENY   JWT_AUDIENCE_REQUIRED

matched 9/9
```

`matched 9/9` 的意思是九個觀察都符合驗收預期；其中 `STALE_MAPPING_ALLOWED` 是**成功重現風險**，不是安全控制通過。看 `control_result` 才能分辨 `CONTROL_OK` 與 `RISK_EXPOSED`。

## 值班工程師被停用，key mapping 沒有跟著變

Human key case 分兩次送出完全相同的 credential。第一次 identity directory state 是 `ACTIVE`；第二次改成 `DISABLED`，但 Gateway 裡仍保留：

```yaml
metadata:
  kind: HUMAN_VIRTUAL_KEY
  human: user/sre-oncaller
  workload: NOT_APPLICABLE
  consumer: key/human-sre-oncaller
```

Gateway 能證明「這把 key 對應到這份 metadata」，無法憑這份 static mapping 知道值班工程師已離職或帳號已停用。第二次 request 因此仍是 HTTP `200`，評估器另標成 `RISK_EXPOSED / STALE_MAPPING_ALLOWED`。

這不是在宣稱所有 virtual-key 產品都無法串 lifecycle；它只證明一件比較窄的事：**只做 key mapping，不能自己變成企業 Human identity lifecycle。**

## Workload key 解的是另一個問題

`workload/runtime-a` 的新 key 在 allowlist 裡，所以得到 `200`；被輪替掉的舊 key 不在設定裡，所以得到 `401`。這能限制某個 runtime 的爆炸半徑，也能避免 provider key 散進每個 Agent deployment。

它仍是 bearer secret，不是 pod instance attestation。若要回答「是哪一個 Kubernetes workload instance」，還需要 ServiceAccount、federated workload identity、SPIFFE 類機制或同等的 runtime 身分證明，不能把 `metadata.workload` 當成密碼學事實。

## JWT 缺少 issuer 或 audience 也必須拒絕

第一版 Lab 鎖在 agentgateway `1.4.1`，只測 valid token 與 wrong audience。發稿 review 補測後發現，缺少 `iss` 或 `aud` 的 Token 都得到 `200`，與當時的六案例結論不一致。官方 release notes 說明，`1.4.x` 以前只在 Token 含有這些 claim 時才比較設定值。

公開 Lab 因此升到 `1.5.0`，除了 valid token，也驗證 wrong issuer、wrong audience、missing issuer 與 missing audience。四個負向案例都必須得到 `401`，而且不能抵達 synthetic backend。

## Provider key 沒有回到 caller artifact

Synthetic provider 會檢查收到的 `Authorization`：

- 必須等於 gateway 注入的 provider key。
- 不得等於 Human key、workload key 或 JWT。
- evidence 只寫前 16 位 SHA-256 指紋，不寫 raw credential。

每次執行最後還會掃過 artifact directory。Human key、workload key、retired key、JWT 或 provider key 只要有一個出現在檔案裡，command 就直接失敗。

## 驗收與清理

```bash
make lab-03-runtime-check
make lab-03-runtime-down
```

`check` 會執行完整 pytest（包含實際啟動 pinned agentgateway container）、branch coverage、Ruff，以及第二次 `--validate-only` 檢查公開 YAML。

Cleanup 只接受 `labs/03-gateway-runtime/artifacts`，而且目錄內必須有內容正確的 `.lab-03-artifacts` ownership marker。未標記目錄與 symlink 都拒絕刪除。

## 常見問題

### Docker Engine 沒有啟動

若看到 `Cannot connect to the Docker daemon`，先啟動 Docker Desktop，再重跑 `make lab-03-runtime-run`。

### `host.docker.internal` 無法連線

Runner 會加入 `host.docker.internal:host-gateway`。若使用不支援這個參數的舊版 container runtime，請升級 Docker；不要把 backend 改成任意外部網址。

### `401` 出現在三個正向 case

先執行 `make lab-03-runtime-config-check`。若公開 YAML 驗證成功，再檢查本機是否有其他 process 佔用動態 port；不要把實際 key 貼進 issue 或 terminal 截圖。

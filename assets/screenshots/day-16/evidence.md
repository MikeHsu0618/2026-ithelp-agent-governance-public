# Day 16 Screenshot Evidence

Status：complete。

## Environment

```text
Tested:       2026-09-08 Asia/Taipei
kind:         0.30.0
Kubernetes:   1.34.0
kubectl:      1.34.0
Gateway API:  1.6.0
kagent:       0.10.0
agentgateway: 1.5.0
```

Helm pull 在本次 live run 顯示下列 digest：

| Chart | Digest |
| --- | --- |
| `agentgateway-crds:v1.5.0` | `sha256:3a6cf44559c612ac8afb7f867aace69bbd4cdba765f1def6377b7a3186c603e3` |
| `agentgateway:v1.5.0` | `sha256:9216ce83965ad2ce0888014d14aac5e71333fd9d4057cd167da92b37630fbee1` |
| `kagent-crds:0.10.0` | `sha256:0d4b0b2f14f6ee715eec231803f6d14ac4e677862788d9e45e0a50af2a7cbb12` |
| `kagent:0.10.0` | `sha256:67049d4381176941e9980b6b80bd5a8a9bac8a16401e24d35da930d4249ef54a` |

MCP fixture 使用 `@modelcontextprotocol/server-everything` `2026.8.31`。Node base image 與 synthetic LLM 的 Python base image 都以 digest 固定在 YAML／Containerfile。

## Commands executed

```bash
make lab-03-runtime-kagent-plan
make lab-03-runtime-kagent-up
make lab-03-runtime-kagent-invoke
make lab-03-runtime-check
```

上面是讀者可直接執行的公開指令，預設使用 repo 內的獨立 kubeconfig。這次實測另外以 `KIND_BIN` 與 `KUBECTL_BIN` 指向下載後的版本化 binary；本機暫存路徑不屬於可重現條件，因此不寫入公開證據。

第一次檢查時，主機既有 kubectl 是 `1.29.2`，與 kind 建立的 Kubernetes `1.34.0` 超出支援的 minor-version skew。正式 live run 改用官方 kubectl `1.34.0`，SHA-256 為 `d491f4c47c34856188d38e87a27866bd94a66a57b8db3093a82ae43baf3bb20d`。Make target 也加入版本檢查，避免讀者忽略同樣的警告。

## Actual result

- `ModelConfig/day16-model`：`Accepted=True`。
- `RemoteMCPServer/day16-tools`：`Accepted=True`，發現 14 個 tools。
- `Agent/day16-agent`：`Accepted=True`、`Ready=True`，generated runtime 為 Go。
- A2A invocation：直接呼叫 Agent Service，state 為 `completed`，artifact text 為 `boundary-ok`。A2A 經 Gateway 的 path 與 failure semantics 留到 Day 17。
- Generated model base URL：`http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80/v1`，`reasoning_effort=low`。
- Generated MCP URL：`http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80/mcp`，帶原始目的地的 `x-kagent-host`。Authorization 值在公開檔案中已改為 `<redacted>`。
- Agentgateway access log：LLM route 的 `POST /v1/chat/completions` 得到 `200`；MCP route 的 `POST /mcp` 得到 `200`／`202`。
- 兩條 `HTTPRoute` 都是 `Accepted=True`、`ResolvedRefs=True`。Synthetic LLM 以 uid／gid `65532` 執行，MCP fixture 以 uid／gid `1000` 執行，兩個 container 的 root filesystem 都通過實際寫入拒絕檢查。
- `down` 後保留一份沒有 current-context 的 kubeconfig，再用同一檔案重跑 `up`，cluster 可以從零建立並完成相同驗收。這是 cleanup／rerun contract，不只驗第一次啟動。
- 靜態責任檢查：4 PASS、2 PARTIAL、0 FAIL。
- Regression：36 tests passed，branch coverage 87.16%，Ruff lint／format 與既有 standalone agentgateway YAML validation 均通過。

## Validation boundary

| Evidence | 能證明 | 不能證明 |
| --- | --- | --- |
| kagent status 與 generated workload | 本次 `Agent`／`ModelConfig`／`RemoteMCPServer` 被 controller 接受，Agent workload Ready | Production HA、upgrade、multi-tenant isolation 或所有 declarative runtime |
| A2A invocation | 本次 declarative Agent 可由 A2A request 呼叫，並取得 completed artifact | Streaming、長任務、HITL、BYO Agent parity 或任意 workflow |
| Generated runtime config | OpenAI-compatible model URL 與 internal MCP URL 指向 agentgateway，reasoning 欄位與 `x-kagent-host` 保留 | 每個 provider 的 thinking surface 相同，或所有 external MCP URL 都會被 rewrite |
| Secret-backed header | kagent 能從 Secret 把 header 值交給 Runtime | Token acquisition、refresh、revocation、restart recovery 或 offboarding |
| Agentgateway access log | 本次 Agent 的 LLM／MCP request 經過共同 traffic path | Production Ingress、企業 IdP、真實 LLM provider 或 Grafana MCP 已在公開 Lab 重現 |

## Presentation method

`01-kagent-boundary-results.png` 把同次 kubectl status、A2A response、generated config 與 agentgateway route observation 排成 1600 × 1000 terminal card。圖片只保存安全摘要，不包含 raw Secret、Token、cluster credential、Pod IP、UID 或本機路徑。正文與 Lab README 另保留可複製 command，不需要從圖片抄字。

## Image and evidence hashes

| File | SHA-256 |
| --- | --- |
| `01-kagent-boundary-results.png` | `08797592764e0135295ca6605e9d5ca4486ae684c911c76ffa6340452b0ef443` |
| `evidence/kagent-boundary-report.json` | `6103066ac0a9d3a8cf997c9d11ceabd4a4ec1c2efdd9f9ddedb3de7007ad489d` |
| `evidence/kagent-terminal.txt` | `9633178bd792eb6a4ca968b1b57d0851475542830fe808ff7770ba7ae87db1b6` |
| `evidence/generated-agent-config.redacted.json` | `ab4eedd5be73760f06bda2db263276441e27ab163e324ed5a00a50b9dc28b0bc` |
| `evidence/gateway-routes.redacted.txt` | `b87b7898cdd36efb89ab22eae19b4f4ad7848dd8c6e327606014297a4cccae29` |
| `evidence/ownership-matrix.md` | `d8bc3027276d231bfd4f5435103173a25bdd80600f9c4c7ece0ac1ee8ee3eba0` |
| `assets/diagrams/day-16/runtime-control-traffic-boundary.png` | `bbfe68a8fb9752b2fa0d4c05cf149fef0682152141e041b166424dbb2e2bec4c` |

## Cleanup

```bash
make lab-03-runtime-kagent-down
```

Cleanup 先驗證獨立 kubeconfig 的 current context 等於 `kind-ithelp-day16`，再刪除名稱精確等於 `ithelp-day16` 的 disposable cluster。全域 kubeconfig 沒有被切換或修改。

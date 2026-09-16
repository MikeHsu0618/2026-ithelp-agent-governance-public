# Lab 04 — Agent Telemetry Pipeline

這個 Lab 沿用 Day 1 的安全 Tool 名稱 `delete_demo_database`，但不再測模型會不會選到它。Day 20 先用單一 process 定義 field contract；Day 21 則把 producer 拆成 agentgateway、Agent Runtime 與 MCP adapter，實際驗證 Trace Context 能不能穿過每一段。

```text
Lab client -> agentgateway -> Agent Runtime -> agentgateway -> MCP adapter
                  |                |                 |
                  +------ OTLP ----+------ OTLP -----+
                                   v
                                Alloy -> LGTM
```

公開 Lab 只有一個 agentgateway。Runtime 呼叫 MCP 時會回到同一個 Gateway，因此不會出現雙層 proxy。這是為了在本機看清楚 data path；作者的實務環境在 Kubernetes，部署拓樸與容量規劃不包含在這個教學縮影裡。

Day 20 的資料契約仍保留三種角色：

- application record：產品介面需要的 session、generation 與 Tool 摘要；
- operational trace：服務執行順序、延遲、錯誤與 trace context；
- governance event：principal、delegation、Artifact、policy、approval 與 effect evidence。

`Governed Action Field Set v0.1` 是本系列的作者定義，不是 OpenTelemetry 標準。OpenTelemetry GenAI Agent semantic conventions 目前仍是 Development；本 Lab 只在適合的 span 上使用 `gen_ai.*` 欄位，自訂治理欄位一律加上 `ithelp.governance.*` prefix。

Day 21 會送出五個固定情境：

| 情境 | 預期結果 | Trace 應出現的邊界 |
|---|---|---|
| normal call | `CANARY_TRIGGERED` | client、Gateway、Runtime、MCP |
| Gateway policy deny | `DENIED` | client、Gateway |
| HITL approved | `APPROVED_AND_EXECUTED` | client、Gateway、Runtime、MCP |
| A2A routing failure | `ROUTING_FAILED` | client、Gateway、Runtime |
| LLM fallback | `FALLBACK_SUCCEEDED` | client、Gateway、Runtime、MCP |

它們都是可重跑的合成事件，後續實驗會沿用同一批情境，繼續檢查 telemetry 欄位、查詢成本與事件還原能力。

Day 22 在相同 Pipeline 上加入 identity projection。Raw claims 先經過 deterministic fixture check，再轉成不含 email／token 的 `VerifiedPrincipalContext`，最後依 Metrics、Traces、Logs 與 Audit 各自建立 allowlist。這個 fixture 只驗證資料流與欄位位置，不取代 Day 8 的 JWT signature、JWKS、issuer、audience 與 expiry 驗證。

Day 23 把缺少的產品實測補上。System under test 是 pinned agentgateway `1.5.0` 的 JWT AuthN、CEL telemetry projection 與原生 `agentgateway_requests_total`，不是 Python producer。Python 只建立本機臨時 RSA key、簽合成 Token、送相同流量並查詢 Prometheus、Tempo 與 Loki。

## 驗證 agentgateway JWT telemetry 與 Cardinality

Day 23 使用三個平行的 agentgateway 實驗組。它們不會互相代理，也不代表 production 要部署三層 Gateway；三組只是讓相同 90 筆 request 在隔離條件下比較不同 metric label 設定。

| 實驗組 | 由 Gateway 加入的 metric labels | 實際出現的 series |
|---|---|---:|
| bounded | `team` | 3 |
| per-user | `team`、`jwt.sub` | 30 |
| per-conversation | `team`、`jwt.sub`、`x-conversation-id` | 90 |

從 repo root 執行：

```bash
make lab-04-cardinality-check
make lab-04-cardinality-up
make lab-04-cardinality-run
make lab-04-cardinality-down
```

`lab-04-cardinality-up` 會建立只存在於 `.runtime/day23/` 的臨時 private key，權限固定為 `0600`。只有 public JWKS 會掛進 Gateway；private key、JWT 與 Authorization header 不會進入 evidence。整套 Lab 不需要外部 API key，也不使用真實帳號。

`lab-04-cardinality-run` 會先送一筆無 Token 與一筆錯誤 audience，兩者都必須由 Gateway 回 `401`。接著建立 30 個合成 principal、3 個 team 與每人 3 個 conversation，同一批 90 筆 request 分別送到三組 Gateway，共 270 次成功呼叫。Verifier 不只檢查 request client 的報告，還會查三個 backend：

- Prometheus：三組 `agentgateway_requests_total` 是否真的為 3／30／90 條 series；
- Tempo：以本輪 request 保存的 `trace_id` 直接取回 Gateway trace，並核對其中的 `jwt.sub`；
- Loki：Gateway access log 是否保留 `identity_user_id` structured metadata，同時確認 index label 只有 `service_name`。

本次保存的結果為：

```json
{
  "authentication_guards": "PASS",
  "observed_series": {
    "bounded": 3,
    "user": 30,
    "conversation": 90
  },
  "growth_vs_bounded": {
    "user": 10.0,
    "conversation": 30.0
  },
  "gateway_identity_log": "PASS",
  "gateway_jwt_trace": "PASS",
  "loki_identity_not_indexed": "PASS",
  "loki_stream_count": 1,
  "overall": "PASS"
}
```

這組數字是本次 traffic matrix 實際出現的 label set，不是把所有維度做笛卡兒積得到的理論上限。完整 query 與時間窗在 [`assets/screenshots/day-23/evidence/backend-report.json`](../../assets/screenshots/day-23/evidence/backend-report.json)。

## 驗證 LLM Fallback 與成本證據

Day 24 先使用 agentgateway `1.5.0` 內建的 LLM Analytics。兩份 Gateway config 都啟用暫存 SQLite request-log database 與 model catalog，`client-retry` instance 的官方 UI 可從 <http://127.0.0.1:28095/ui/llm/analytics> 開啟。跑完 Fallback 情境後，畫面會顯示 OpenAI／Anthropic 各一筆 request、兩個 calls，以及只有成功 backup response 能證明的 10 tokens／`USD 0.000066`。

Repo 另外收錄與 Lab image 相同 `v1.5.0` 的[官方 Grafana Dashboard](configs/day-24/official-dashboard/agentgateway-dashboard-v1.5.0.json)，原檔 SHA-256 也納入 `lab-04-cost-check`。Kubernetes 環境應優先使用 Helm chart 建立的 ServiceMonitor、PodMonitor 與 Dashboard ConfigMap；官方面板已包含 requests、LLM token／cost／latency、MCP calls、route latency、xDS 與 runtime health。

這個 Compose Lab 是 standalone agentgateway，不具備官方 Dashboard 預期的 Kubernetes `namespace`、Gateway name、Pod 與 container metrics。`configs/day-24/grafana-dashboard.json` 因此只是一張 Fallback／Cost evidence extension，專門補官方面板不會替業務 action 推論的三件事：

- 相同 `action_id` 的 primary `503` 與 backup `200` 是兩次 HTTP request；
- 失敗 attempt 沒有 provider usage payload 時，usage／cost 必須保持 `UNKNOWN`；
- `agentgateway_gen_ai_client_cost_usd_total` 是 model catalog estimate，不是 provider invoice。

從 Repo root 執行：

```bash
make lab-04-cost-check
make lab-04-cost-up
make lab-04-cost-run
make lab-04-cost-down
```

`lab-04-cost-run` 會實際送出三組流量：

| 情境 | HTTP attempts | 實際 provider 順序 | 結果 |
|---|---:|---|---|
| primary success | 1 | primary | OpenAI-shaped `200`，input 11／output 5 |
| failover without retry | 1 | primary | `503`，usage `UNKNOWN` |
| failover with client retry | 2 | primary → backup | `503` → Anthropic-shaped `200`，input 7／output 3 |

agentgateway `1.5.0` 的 virtual model failover 依賴 health eviction。觸發 eviction 的原 request 仍會失敗，後續 request 才改用下一個 target。本次使用的 simplified LLM config 不接受 `llm.policies.retry`，因此公開 Lab 由 client 對同一 `action_id` 發出第二次 request，不加第二層 proxy，也不把它說成 Gateway 內部 retry。

Verifier 會查 Loki、Prometheus、Tempo 與兩個 provider `/events` receipt。成功時必須同時看到 1／1／2 attempts、primary → backup 的 provider 順序、四條 Gateway traces、原生 token／cost metrics，以及 `team=platform` 的 bounded attribution。按 Lab price catalog 計算，primary calibration estimate 為 `USD 0.00006375`，backup 成功 attempt 為 `USD 0.00006600`；Fallback action 的失敗 attempt 沒有 usage，所以完整 action total 仍是 `UNKNOWN`，不是 `USD 0.00006600`。

Day 24 使用的本機入口如下，全部只綁 loopback：

- Grafana：<http://127.0.0.1:24000>
- agentgateway 內建 LLM Analytics：<http://127.0.0.1:28095/ui/llm/analytics>
- Prometheus：<http://127.0.0.1:29091>
- Alloy：<http://127.0.0.1:24345>
- failover-only Gateway：<http://127.0.0.1:28084>
- client-retry Gateway：<http://127.0.0.1:28085>

## 一次跑完整套 Lab

從 repo root 執行：

```bash
make lab-04-up
make lab-04-check
make lab-04-run
make lab-04-down
```

`make lab-04-run` 除了檢查五個 HTTP 結果，也會直接查三個 backend：

- Tempo：每個 Trace 是否包含該情境應經過的 service；
- Loki：同一個 `action_id` 是否能找到 producer event；
- Prometheus：是否已抓到 `agentgateway_*` data-plane metrics。

成功時最後一段會看到：

```json
{
  "overall": "PASS",
  "prometheus_agentgateway_metrics": "PASS"
}
```

LGTM 與 Alloy 介面只綁定 loopback：

- Grafana：<http://127.0.0.1:13000>
- Alloy：<http://127.0.0.1:12345>

這個 LGTM image 是本機開發與示範環境，不是 production topology。

## 驗證 Identity projection

啟動 Compose 後執行：

```bash
make lab-04-identity
```

這個 target 會刻意把 synthetic `user.email`、`auth.token`、`principal.ref` 與 `session.id` 放進送往 Alloy 的訊號，再直接查三個 backend：

- Tempo 保留 `principal.ref`、`action_id`、assurance、team 與 role，但找不到 raw email／token；
- Loki 可用 `principal_ref` structured metadata 過濾事件，不需要把它設成 stream label；
- Prometheus 只保留 team、route、outcome，不接受 principal、user、session、conversation 或 action ID label；
- 三個 backend 都不應出現 logging SDK 自動附帶的本機 `code.file.path`。

成功輸出如下：

```json
{
  "forbidden_fields_absent": "PASS",
  "loki_principal_not_indexed": "PASS",
  "loki_safe_projection": "PASS",
  "overall": "PASS",
  "prometheus_bounded_labels": "PASS",
  "tempo_safe_projection": "PASS"
}
```

完整位置判斷在 [`identity-field-placement.md`](identity-field-placement.md)。Lab 的 pseudonym 使用 HMAC-SHA256；程式裡的固定 key 只為了讓公開 fixture 可重現，production 必須改由 Secret 管理並規劃 rotation。

## 故意拿掉 Trace Context

下面的命令只在 normal call 的 Runtime -> MCP request 拿掉 `traceparent`，其他資料與執行結果維持不變：

```bash
make lab-04-broken-trace
```

Tool 依然回傳成功，但 verifier 會在原本的 Trace 裡找不到 `mcp-adapter`，並把 `overall` 標成 `FAIL`。這個 target 只有在確實重現缺口時才算成功，方便讀者比較「功能成功」與「追蹤完整」是兩件事。

Day 20 的 field-contract 負向測試仍可單獨執行：

```bash
make lab-04-negative
```

## 版本與設定檔

| 元件 | Lab 版本 |
|---|---|
| agentgateway | `1.5.0`，image 以 digest 固定 |
| Grafana Alloy | `1.18.1`，image 以 digest 固定 |
| `grafana/otel-lgtm` | image 以 digest 固定；內含 Grafana、Tempo、Loki、Prometheus 與 OTel Collector |
| Python | `3.14-slim`，base image 以 digest 固定 |

主要檔案：

- `agentgateway.yaml`：三條正常 route、一條固定 deny policy，以及 OTLP trace/access log；
- `config.alloy`：OTLP gRPC/HTTP receiver、memory limiter、identity transform、batch、LGTM exporter 與 Gateway metrics scrape；
- `docker-compose.yaml`：單一 Gateway、Runtime、MCP、Alloy、LGTM；
- `src/traceability_lab/service.py`：可重現的 Runtime/MCP fixture；
- `src/traceability_lab/suite.py`：五個情境的 client 與預期結果。
- `src/traceability_lab/identity.py`：verified principal context 與四種 destination projection；
- `src/traceability_lab/identity_run.py`：Day 22 的污染欄位實驗與安全 evidence 輸出。
- `configs/day-23/agentgateway-*.yaml`：Day 23 三組 JWT AuthN、CEL access-log／trace／metric projection；
- `config.day23.alloy`：三組 Gateway metrics scrape 與 OTLP logs／traces pipeline；
- `docker-compose.day23.yaml`：三組平行 Gateway、no-op backend、Alloy 與 LGTM；
- `src/traceability_lab/cardinality.py`：臨時 key、合成 Token 與固定 traffic matrix；
- `configs/day-23/grafana-dashboard.json`：可匯入的 Day 23 實測 Dashboard。
- `configs/day-24/official-dashboard/agentgateway-dashboard-v1.5.0.json`：未修改的官方維運 Dashboard；來源、commit 與 checksum 記在同目錄 README；
- `configs/day-24/grafana-dashboard.json`：只補 Fallback action／attempt 與成本證據邊界的 focused extension；
- `configs/day-24/agentgateway-*.yaml`：兩組隔離 eviction state 的 LLM virtual model 設定，以及供官方 Analytics 使用的暫存 SQLite request log；
- `configs/day-24/costs.json`：可重現且明確標示為 Lab estimate 的 model catalog；
- `docker-compose.day24.yaml`、`config.day24.alloy`：Day 24 standalone Gateway、provider fixtures 與 LGTM pipeline；
- `src/traceability_lab/cost_fallback.py`：deterministic provider fixture 與 client traffic；
- `tests/test_cost_fallback.py`：Fallback、usage 缺口、Dashboard 與官方資產 checksum regression tests。

`memory_limiter` 緊接 receiver，identity transform 只刪除已知禁止欄位，然後才進 batch/exporter。這是刻意保留的 collector 防護；它不能取代 producer minimization、backend RBAC、retention 與資料盤點。公開 port 也只綁 `127.0.0.1`。

要把其中一筆 run 整理成可公開 evidence，可執行：

```bash
uv run --directory labs/04-telemetry-pipeline \
  traceability-lab package-evidence \
  --artifact-dir artifacts/<run-id> \
  --backend-report .runtime/backend-report.json \
  --destination ../../assets/screenshots/day-20/evidence
```

這個命令會移除 manifest 裡的本機 `artifact_dir`，並一併輸出 backend correlation 與負向 schema 測試結果。

只測本機資料契約，不啟動 container：

```bash
uv run --directory labs/04-telemetry-pipeline \
  traceability-lab run \
  --artifact-root artifacts
```

## Safe failure mode

`delete_demo_database` 不連資料庫、shell、Kubernetes 或外部 API。MCP adapter 只回傳 `CANARY_TRIGGERED` receipt，`side_effects` 固定為 `0`。A2A failure 指向 Compose 裡刻意不存在的 service；LLM fallback 也不會呼叫外部模型。整套 Lab 不需要 API key。

## Evidence

Day 21 每次執行建立獨立目錄：

```text
artifacts/<run-id>/manifest.json
artifacts/<run-id>/scenario-report.json
```

這些檔案只含合成 action、scenario 與 Trace ID，不保存 raw prompt、email、JWT、API key 或 Tool output content。`make lab-04-down` 會移除 Compose volumes；`cleanup` 只會刪除帶有 Lab 04 marker 的 `artifacts/`。

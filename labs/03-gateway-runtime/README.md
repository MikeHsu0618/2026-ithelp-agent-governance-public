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

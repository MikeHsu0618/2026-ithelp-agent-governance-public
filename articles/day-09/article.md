# Day 9｜Delegation Context 實作：把 Human、Agent 與 Workload 寫進同一條責任鏈

Day 8 的 Gateway 已經能驗證 issuer、audience、scope 與 policy claim，但那只能證明「這枚 Token 能不能送到這個 resource」。如果值班工程師請 SRE Copilot 查詢錯誤，Copilot 再把工作交給 Investigator Agent，最後由 Kubernetes workload 呼叫 `query_logs`，一枚 access token 還是說不完整中間發生了什麼。

同一筆 Tool Call 走過不同觀測點時，各自會留下合理但不完整的答案：Gateway 看見 `sub=user/sre-oncaller`，Agent runtime 知道目前執行的是 `sre-investigator@v1`，Pod spec 則指定 `serviceAccountName=sre-agent`。三個值都可能是真的，卻不能互相取代。

我在整理 Cognito Human SSO、M2M credential 與 Agent runtime 的 audit 欄位時，最難處理的是這段責任該怎麼留下來。只記 Human，Agent 如何選 Tool、改參數或繼續委派會消失。只記 ServiceAccount，所有請求又會像 workload 自己發起的。這不是 production incident 回放，而是實作期間形成的 actor-model 判斷。以下用合成身分與 [Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/labs/02-identity-boundary/README.md) 的 `delegation` command 固定資料結構。

我先用七組測試把規則釘死：角色身分可以明確標成 `UNKNOWN`，需要存在的 slot 卻不能直接消失。

```text
human_delegated          ACCEPT  ACCEPT
scheduled_service        ACCEPT  ACCEPT
a2a_unknown_workload     ACCEPT  ACCEPT
missing_workload_slot    REJECT  REQUIRED_FIELD_MISSING
human_null               REJECT  NULL_NOT_ALLOWED
duplicate_agent_sequence REJECT  AGENT_SEQUENCE_INVALID
actor_only               REJECT  REQUIRED_FIELD_MISSING
```

`a2a_unknown_workload` 把 Human 與 Workload 寫成 `UNKNOWN`，validator 仍然接受，因為事件已經明說這條 flow 理應有這兩個角色，只是目前沒有足夠證據。`missing_workload_slot` 和 `human_null` 則被拒絕。欄位消失或塞入 `null` 時，事後無法判斷它代表角色不存在、上游沒傳，還是 parser 失敗。

![Delegation Context Lab 的實際 CLI 結果：三組完整或明確 UNKNOWN 的 context 被接受，缺 slot、null、重複 Agent sequence 與 actor-only 紀錄被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/screenshots/day-09/01-delegation-context-results.png)

> `Lab` 圖片由 `make lab-02-delegation` 的實際輸出重新排版。完整指令、JSON summary、JSONL event 與 hash 保存在 [Day 9 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/assets/screenshots/day-09/evidence.md)，不用從圖片抄指令。

## 各觀測點只能看見責任鏈的一段

這筆 Tool Call 的 actor chain 有四個 slot，其中 Service 在這條 Human flow 並不存在：

```text
Human      user/sre-oncaller
Service    NOT_APPLICABLE
Agent      sre-copilot@v1 → sre-investigator@v1
Workload   ServiceAccount lab/sre-agent
```

`client_id=sre-console` 仍然值得保存，但它屬於 credential context，不是第二個 actor。這條 Human flow 使用 public OAuth client，沒有 client authentication 可以證明 Service principal，因此 `service` 明寫 `NOT_APPLICABLE`。到了 Client Credentials flow，通過 client authentication 的 M2M principal 才會填進這個 slot。

這些位置來自不同來源，也有不同的可信程度。Agent display name 不能替代 Human principal，Pod spec 裡的 ServiceAccount 名稱也不能直接證明目前持有 credential 的 workload。若只剩一個 `actor` 欄位，最後寫進去的值通常取決於哪個元件剛好負責記 Log，而不是完整的責任鏈。

`trace_id` 可以幫忙串事件，不能代替身分。W3C Trace Context 對 `trace-id` 的定義是識別一條 distributed trace，它沒有證明 Human、Agent 或 Workload 是誰。[W3C Trace Context](https://www.w3.org/TR/trace-context/#trace-id)

我沒有再把四個值壓成一條更長的 actor 字串，而是讓 Delegation Context 分別保存 actor chain、credential、target 與 correlation 欄位。下圖先看 request 經過哪些角色，再看事件需要留下哪些證據：

![值班工程師委派 SRE Copilot，Copilot 再委派 Investigator Agent，由 Kubernetes ServiceAccount workload 呼叫 MCP。Delegation Context 保存完整 actor chain、credential、target 與 correlation 欄位。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/diagrams/day-09/delegation-sequence.png)

這份 Context 保存證據，不自動宣告委派合法。授權規則仍要判斷值班工程師能否使用這個 Agent、Agent 能否執行 `query_logs`，以及 workload 是否受信任。

## Delegation Context v0.1

完整 schema 放在 [`delegation-context-v0.1.schema.json`](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/labs/02-identity-boundary/src/identity_boundary/schemas/delegation-context-v0.1.schema.json)，使用 [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)。下面是正向案例的主要結構：

```json
{
  "schema_version": "delegation-context/v0.1",
  "event_id": "evt-day09-human-delegated",
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "timestamp": "2026-08-19T05:52:22Z",
  "flow_kind": "HUMAN_DELEGATED",
  "actor_chain": {
    "human": {
      "state": "PRESENT",
      "principal": "user/sre-oncaller",
      "evidence_source": "verified_access_token.sub",
      "evidence_level": "VERIFIED"
    },
    "service": {
      "state": "NOT_APPLICABLE",
      "reason": "human delegated flow has no separate service actor"
    },
    "agents": [
      {
        "sequence": 0,
        "principal": "agent/sre-copilot",
        "version": "v1",
        "role": "DELEGATING",
        "evidence_source": "controlled_deployment_metadata",
        "evidence_level": "ASSERTED"
      },
      {
        "sequence": 1,
        "principal": "agent/sre-investigator",
        "version": "v1",
        "role": "EXECUTING",
        "evidence_source": "controlled_deployment_metadata",
        "evidence_level": "ASSERTED"
      }
    ],
    "workload": {
      "state": "PRESENT",
      "principal": "k8s://lab/identity-boundary/sa/sre-agent",
      "evidence_source": "kubernetes.serviceaccount",
      "evidence_level": "ASSERTED"
    }
  },
  "credential": {
    "type": "OAUTH_ACCESS_TOKEN",
    "issuer": "https://issuer.lab.example/identity-boundary",
    "subject": "user/sre-oncaller",
    "client_id": "sre-console",
    "audiences": ["mcp://lab/observability/query"],
    "fingerprint": "sha256:5d333c1bd8075ace62ef09e3d8e9ca8153cbe6e4dc51c307ab0806f8fcbd3f3e"
  },
  "target": {
    "resource": "mcp://lab/observability/query",
    "action": "query_logs"
  }
}
```

這份 JSON 可以直接通過 v0.1 validator。Raw bearer token 不在 schema 允許的欄位中，Lab evidence 也會掃描 compact JWT 與 private-key marker。

每個欄位的用途、查詢方式與升版規則整理在 [Delegation Context Field Guide](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/articles/day-09/delegation-context-field-guide.md)。這份 v0.1 是本系列的 audit contract，不是我替 RFC 或 A2A 發明的新標準。

## Evidence level 與身分可信度

正向案例裡的 Human、Agent 與 Workload 都有值，但 `evidence_level` 故意沒有填成同一級。Service slot 則明確標成 `NOT_APPLICABLE`。

`user/sre-oncaller` 來自 Day 8 已驗過的 access-token `sub`，所以標 `VERIFIED`。`sre-console` 是 access token 裡的 public OAuth `client_id`，保存在 credential context 方便查詢。這個值能說明哪個應用參與流程，不能拿來填補不存在的 Service actor。

Agent 名稱與版本來自受控合成 deployment metadata，先標 `ASSERTED`。公開 Lab 的 ServiceAccount 名稱則取自合成 Pod spec，一樣只標 `ASSERTED`。Kubernetes 官方把 ServiceAccount 定義為 cluster 內的 non-human identity，Pod 可以使用其 credential 表明身分。不過，把 `serviceAccountName` 寫進事件，不等於這個 decision point 已驗過 bound token 或 workload attestation。[Kubernetes Service Accounts](https://kubernetes.io/docs/concepts/security/service-accounts/)

如果未來 Gateway 驗證 bound ServiceAccount token、SPIFFE SVID 或 cloud workload identity，再把該觀測點的 workload evidence 升為 `VERIFIED`。先把欄位塗綠，之後反而很難找出治理缺口。

## UNKNOWN 與 NOT_APPLICABLE 的 policy 差異

排程 Agent 沒有人坐在瀏覽器前，Human slot 應該是：

```json
{
  "state": "NOT_APPLICABLE",
  "reason": "scheduled execution has no interactive human"
}
```

A2A request 原本可能由 Human 啟動，但上游沒有傳遞這份 context，則要寫：

```json
{
  "state": "UNKNOWN",
  "reason": "upstream agent did not propagate human identity"
}
```

兩者對 incident replay 與 policy 的影響不同。第一種不必追查漏資料，第二種可能要 fail closed、降權或要求補充證據。`null` 把這個差異抹掉了。

A2A `1.0.0` 的 Agent Card 會宣告 server 接受哪些 authentication scheme，client 再透過該 scheme 的 out-of-band 流程取得 credential，並在每次 request 的 header 或 transport metadata 中送出。規格可以建立當下 A2A client 的 transport identity，卻不會替應用補出最初的 Human、前一個 Agent 與實際 Workload。[A2A Protocol Specification 1.0.0](https://a2a-protocol.org/v1.0.0/specification/#7-authentication-and-authorization)

我在評估 kagent／BYO Agent 邊界時也遇到同一題。A2A 能處理 Agent discovery、呼叫與 task lifecycle。Runtime 沒有收集或轉送 Human、Agent 與 Workload evidence 時，平台仍然無法從協定名稱重建責任鏈。Day 17–18 會再用 Kubernetes Lab 驗證這條邊界。

## Agent chain 的 schema 與 semantic validation

JSON Schema 能限制 `agents` 是陣列、每個 item 有哪些欄位，還能要求全鏈只出現一個 `EXECUTING`。它不適合把「sequence 必須從 0 連續遞增，而且 executing Agent 一定位於最後」寫成一團難維護的條件。

Lab 因此分兩層：

```python
errors = Draft202012Validator(schema).iter_errors(context)
if errors:
    reject("CONTEXT_SCHEMA_INVALID")

sequences = [agent["sequence"] for agent in agents]
if sequences != list(range(len(agents))):
    reject("AGENT_SEQUENCE_INVALID")

roles = [agent["role"] for agent in agents]
if roles[-1] != "EXECUTING" or "EXECUTING" in roles[:-1]:
    reject("AGENT_ROLE_INVALID")
```

Schema 管欄位與型別，semantic validator 管跨欄位語意。兩層都回穩定錯誤碼，audit 才能查「哪一種 context 一直壞掉」，不必解析一長串 validation message。

## RFC 8693 act 與本地 Audit Context 的分工

[RFC 8693 OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693.html#section-4.1) 已定義 JWT `act` claim：top-level subject 是被代表的一方，`act` 表示目前 actor，巢狀 `act` 還能保存之前的 delegation actors。

`act` 很適合接住 Day 11 的 Token Exchange／OBO，但 Day 9 沒把整份 Context 硬塞成自訂 JWT claim，理由有三個：

- RFC 的 `act` 處理 Token delegation identity。Agent artifact version、Kubernetes execution evidence、target action 與本地 evidence level 仍需要自己的 audit contract。
- RFC 明確說 access-control policy 只應考慮 top-level claims 與目前 actor，較早的巢狀 actors 是資訊性歷史。Incident replay 需要歷史，不代表每一個 prior actor 都能直接參與現在的 ALLOW。
- Context 可能來自多個觀測點。只有 access token 的欄位由 Token verifier 證明，其餘欄位要附各自的來源與 integrity protection。

Token Exchange 可以產生可驗的 subject／current actor。Delegation Context 再把它與 Agent、Workload、target、trace 串進治理事件，兩者處理不同層次的資料。

## 重現 Day 9 Delegation Lab

開頭的七組結果都能從 repo root 重跑。三個正向案例涵蓋 Human 委派、無人排程，以及 Human／Workload evidence 暫時未知的 A2A flow。四個負向案例分別拿掉必要 slot、放入 `null`、破壞 Agent sequence，或退回單一 `actor` 字串。

從 repo root 執行：

```bash
make lab-02-up
make lab-02-check
make lab-02-delegation
```

預期最後看到：

```text
7/7 cases matched
Raw credential persisted: no
```

如果要把結果交給 CI 或其他工具處理，可以輸出 JSON：

```bash
uv run --directory labs/02-identity-boundary \
  identity-boundary delegation \
  --artifact-root labs/02-identity-boundary/artifacts \
  --output json
```

每次 run 會寫入 schema snapshot、contexts、expected results、summary、manifest 與 JSONL events。Day 9 截圖保留的是 2026-08-26 完成這個 slice 時的輸出，當時共用 Lab 有 37 個測試。Day 10–12 後來繼續擴充同一套 Lab。2026-09-01 重新執行 `make lab-02-check` 為 72 tests passed、branch coverage 91.17%，`make lab-02-delegation` 仍是 7/7 matched，dependency audit 也維持通過。

清理仍由 ownership marker 限制範圍：

```bash
make lab-02-down
```

## 正式環境的 Context integrity 與 workload attestation

v0.1 固定了資料形狀，沒有替 production 完成四件事：

1. **Context integrity**：哪個元件有權新增或修改 Agent／Workload slot？跨 trust boundary 時要用簽章、受信任 envelope 或由 Gateway 重建，不能相信 client 自報。
2. **Workload attestation**：deployment label 與 ServiceAccount 名稱不等於當次 workload 已驗證。要決定是否採 bound token、SPIFFE、cloud identity 或其他機制。
3. **Propagation 與降級策略**：A2A／MCP hop 拿不到 Human 或 Workload context 時，是拒絕、縮小 scope，還是只允許低風險 Tool？`UNKNOWN` 讓 policy 有資料可判斷，不替 policy 做決定。
4. **Privacy 與 retention**：Human principal、trace、Agent chain 與 credential fingerprint 都能被關聯。它們不該全部變成 metric label，也不能無期限保存。這筆帳會在 Day 22–23 詳算。

## Token Passthrough 會破壞 Attribution

Day 9 解決的是 audit data model。現在一筆事件能回答：值班工程師提出目的、Copilot 委派、Investigator 決定執行、哪個 workload 送出 request，以及它使用的 credential 對哪個 resource 有效。

但資料結構畫得再完整，也擋不住一條常見捷徑：Copilot 收到值班工程師的 access token，原封不動傳給 Investigator，再一路送到 MCP Server。

這樣每個 hop 都「有 Token」，整條 network path 卻只看得到值班工程師。Workload attribution 消失，resource audience 也可能被迫放寬。

下一篇直接跑這條捷徑：Token passthrough 為什麼最好接，後來卻最難說清楚。

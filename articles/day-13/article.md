# Day 13｜從 LiteLLM 轉向 agentgateway：AI Gateway 功能表沒寫的維運成本

我一開始找 AI Gateway 的條件很直接：把不同 LLM provider 收進同一個 OpenAI-compatible endpoint，再補上 routing、fallback、virtual key、budget 和管理介面。只看功能表，LiteLLM 幾乎每一格都打中需求。

後來把方案放進 Kubernetes，我們開始盤點 PostgreSQL、Redis、migration、team／user state，以及為了配合 GitOps 另外補上的 API／Terraform glue。這些東西都能做，卻讓原本的問題從「哪個 Gateway 功能比較多」，變成「這套平台交給誰維運，Git 能不能重建，員工離職時又要去哪裡撤權」。

LiteLLM 並沒有在評估途中突然少掉哪項功能，改變的是我們手上的選型權重。我們要找的已經不只是一個 LLM Proxy，還要能把 LLM、MCP 與 A2A 流量放進共同的 policy 和 telemetry 邊界。這篇會用當時的 Kubernetes inventory、版本化選型表和事後風險時間線，把這次改變攤開來看。

## LiteLLM 的 LLM management 優勢

![LiteLLM 官方產品識別。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/third-party/litellm/litellm-logo.jpg)

[LiteLLM](https://www.litellm.ai/) 是 LLM Gateway，也是一層多 provider 的 translation／routing layer。應用程式只要更換 `base_url`，就能用接近一致的介面呼叫不同模型。真正的 provider key 留在 Proxy，應用 repository 不必各自保存一份。再加上 virtual key、rate limit、budget、spend tracking、fallback 和 UI，它很自然會進入共用模型入口的候選名單。

官方的 [Proxy architecture](https://docs.litellm.ai/docs/proxy/architecture) 會在 request path 上依序處理 virtual key／budget check、rate limit、Router 與 provider translation，response 回來後再更新 spend 與 logging callback。PostgreSQL 保存 key、team 和 spend，Redis 則負責 cache 與 rate-limit counter。這是一套完整的 LLM management 架構，不是裝完一個 Pod 就結束的玩具 Proxy。

`實戰` 我評估 LiteLLM 時，供應鏈事件還沒有發生。當時的 Kubernetes snapshot 落在 `1.80.x` 世代，去掉內部網域、registry 和 credential 後，實際要接手的 inventory 大致如下：

```text
LiteLLM Proxy
├── provider routing / fallback
├── virtual key / team / budget
├── management UI
├── PostgreSQL
├── Redis
├── database migration job
└── API + Terraform management glue
```

Inventory 最底下的 API + Terraform management glue 是我們自己加上的整合層，用來讓 team／user 管理符合既有交付方式。LiteLLM 當時已經能跑，選型卡住的是後續怎麼把它納入原有的平台治理。

## Kubernetes operating model 與 GitOps

我們習慣在 pull request 裡 review 變更，由 Git 保存 diff，再讓部署工具把宣告狀態送進 Kubernetes。LiteLLM 當時的模型清單可以寫進設定檔，team、user、virtual key 與部分管理狀態則主要透過 UI、API 和資料庫操作。為了讓這些資料也能跟著 IaC 交付，我們用 Terraform 呼叫管理 API：建立資源前先查 team ID，destroy 時再查一次 ID，最後才送出 delete request。

流程跑得通，Terraform state 卻只知道自己曾經呼叫 API，不知道產品資料庫裡是不是有人從 UI 改過值，也無法保證每個 response 都帶回足以 reconciliation 的狀態。當 resource ID 重建或 UI 與 Git 出現 drift，維運者面對的其實是一組腳本約定，不是 Kubernetes controller 持續收斂的 desired state。

企業 IdP 已經知道值班工程師屬於哪個 team，Gateway 裡卻又建立了 `值班工程師 → LiteLLM user → team → virtual key`。Virtual key 很適合追 usage 和 budget，但員工離職、轉調或換組時，平台還是得確保第二套 mapping 同步撤權。能算出這把 key 花了多少錢，和能證明這次 request 由哪位 Human 授權，是兩個不同問題。

如果高可用盤點只算 Proxy replica，PostgreSQL、Redis、migration、connection pool、background spend write 和 UI state 就全被漏掉了，後面的 backup、upgrade 與 recovery 也都需要 owner。這些不是 LiteLLM 的缺陷，而是採用這種 operating model 後，團隊必須一起接下來的責任。

當時 UI 有些操作確實不太順手，但我不想把整個選型濃縮成「UI 不好用，所以換掉」。UI 會改版，功能也可能補齊。Source of truth、identity lifecycle 和 on-call responsibility 才是比較難靠下一版消失的差異。

## AI Gateway 選型 Scorecard

最早那種 `Provider 數量 5 分、UI 4 分、效能 4 分` 的評分方式看起來很客觀，實際上很容易等答案出來後才回頭調權重。我們後來把比較方式改成十個決策面，每一列都要寫出產品外的 owner，並標明證據來自實際操作、當時 snapshot、官方文件或架構判斷。

完整的 [AI Gateway 平台選型 Scorecard](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/articles/day-13/gateway-selection-scorecard.md) 可以直接複製到自己的 ADR 或 Architecture Review。下面先保留最影響這次結果的六列：

| 決策面 | Application Team 常先看 | Platform Team 還要補的問題 |
| --- | --- | --- |
| Provider routing | API 相容、fallback、retry | provider lifecycle、quota、例外由誰處理 |
| Consumer 管理 | key、budget、rate limit | key 代表 Human 還是 workload，離職時從哪裡撤權 |
| Protocol | LLM request 能不能通 | MCP／A2A action 能否進入同一個 policy boundary |
| Declarative delivery | 有沒有 YAML／API | Git review、reconcile、drift 和 rollback |
| Runtime dependencies | Helm 能不能裝 | DB、cache、migration、backup、upgrade 和 on-call |
| Audit | 有沒有 usage／request log | 誰代表誰、透過哪個 workload、存取哪個 resource |

假如團隊只想快速統一 provider、收回 provider key、按專案限制 budget，再給使用者一個方便操作的 UI，LiteLLM 很可能更省時間。我們這次把 Kubernetes reconciliation、identity-aware policy 和跨 protocol traffic boundary 放在較高權重，才會得到不同答案。這張表因此不能離開 workload 與組織條件，被拿去當成產品排行榜。

## agentgateway control plane

![agentgateway 官方產品識別。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/third-party/agentgateway/agentgateway-logo.png)

[agentgateway](https://agentgateway.dev/) 的 data plane 可以代理 HTTP、gRPC、LLM、MCP 與 A2A 流量，Kubernetes 模式另外有 controller。依照官方的 [Kubernetes architecture](https://agentgateway.dev/docs/kubernetes/latest/about/architecture/)，controller 會 watch Gateway API 與 agentgateway resources，產生 runtime config，再透過 xDS 送給 data plane。

Route、backend、policy 與 Gateway lifecycle 從 Kubernetes API 進場，變更可以經過 Git review 和 reconciliation。Request 進入 runtime 後，再由同一個 data plane 處理 routing、authentication、authorization、resiliency 與 telemetry。這條交付路徑比 UI／API glue 更接近我們原有的工作方式。

我們實際轉向時的 snapshot 在 `1.3.x` 前後，不會把今天 `v1.4.1` 文件裡的所有能力倒寫成當時已經測過。可以用第一人稱確認的是，由 kagent ModelConfig 發出的 LLM 流量、Remote MCP、JWT 和 per-tool policy 等特定路徑，確實在 Kubernetes 串過。A2A、kagent 與 BYO Agent 的能力邊界，會留到 Day 16–18 用各自的證據處理。

```text
Git / Kubernetes API
        │
        ▼
controller / control plane
        │ xDS
        ▼
agentgateway data plane
        ├── LLM provider
        ├── MCP server
        └── A2A agent
```

在這條路徑裡，LLM、Tool 與 Agent traffic 都會經過共同的 enforcement point，identity、policy decision 和 telemetry 才有機會使用一致欄位。這個責任位置比「Rust 一定比 Python 好」更影響我的選擇。Day 5 提過的 Identity、Provenance、Enforcement、Traceability 四個問題，也因此有了可以落實的 traffic boundary。

## Discovery／Registration 的產品外責任

Day 12 已經讓 agentgateway 驗證 Cognito 發出的 Human／M2M Token，並依 `client_id`、`aud` 和 scope 執行 policy。這只處理 Token 進入 Gateway 之後的 request。MCP client 在登入前怎麼找到 authorization metadata、client 要預先註冊還是使用 CIMD，以及 Cognito 缺少的 provider adapter 由誰維護，仍然要另外指定 owner。

```text
登入與取 Token
MCP client → authorization metadata
           → pre-registration / CIMD / legacy DCR
           → Cognito

帶 Token 呼叫
MCP client → agentgateway → JWT / Tool policy → MCP server
```

第一段由 IdP、client registration process 和必要的 provider adapter 負責，第二段才進入 agentgateway 的 runtime traffic path。Provider adapter 可以只提供 metadata endpoint 與 registration process，沒有必要再疊一層通用 Proxy。

公開 Lab 也不會把 LiteLLM 和 agentgateway 串成兩層。多一層 Proxy 沒辦法自動補齊 discovery，反而新增 timeout、streaming、header、retry、auth 與 audit attribution 的責任。Day 15 會再把既有企業入口放回來談，但 Lab 仍會維持單層 agentgateway，避免用複雜 topology 假裝更接近實務。

## 選型後的供應鏈風險

下圖把兩條時間線分開。上半部是當時真的影響選型的 operating model 與 identity mapping。下半部則是轉向 agentgateway 後，LiteLLM 才發生的供應鏈事件，以及後續 Security Working Group 和 Rust staging 的改善方向。

![AI Gateway 選型時間線。原始決策來自 LiteLLM Kubernetes operating model 與 identity mapping。轉向 agentgateway 後才發生 2026 年 3 月 PyPI 惡意套件事件，2026 年 8 月再重新查證 Security Working Group 與 Rust staging。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/diagrams/day-13/selection-timeline.png)

### 2026 年 3 月 LiteLLM 供應鏈事件

[官方事件 issue](https://github.com/BerriAI/litellm/issues/24518) 列出 PyPI `1.82.7` 與 `1.82.8` 遭植入惡意程式，可能蒐集並外傳 credential。維護團隊移除了受影響套件、輪替 maintainer 帳號，並在調查期間暫停 release。Issue 也特別說明，當時使用 Proxy Docker image 的人不在公告列出的影響範圍。

我們在事件發生前，已經因 operating model 與 identity mapping 不合而轉向 agentgateway。這次事件不能拿來冒充早期決策理由，但它確實讓 software supply-chain trust 成為往後不會再漏掉的評估欄位。

2026 年 8 月重新查證時，[LiteLLM Security Working Group](https://github.com/BerriAI/litellm-security-wg) 已把 supply-chain hardening 標成 `Done`，security disclosure 仍在進行，dependency audit 則列為 `TODO`。[LiteLLM `v1.98.0` release](https://github.com/BerriAI/litellm/releases/tag/v1.98.0) 也提供 cosign image verification 指令。我會把這些改善和未完成項目一起記錄，既不因為出過事故就判定產品永遠不可信，也不靠一組簽章指令宣告風險已經消失。

我會把 image signature、SBOM、dependency audit、release provenance、patch SLA 與 incident response 固定放進 Gateway 選型表。以後不管評估哪個產品，都不用等它先出事才想起這一欄。

### LiteLLM Rust staging

LiteLLM 的確有 Rust 專案，只是現有文件還不能支撐「整套 Proxy 已經改寫成 Rust」。[Rust gateway staging README](https://github.com/BerriAI/litellm/blob/litellm_internal_staging/litellm-rust/crates/ai-gateway/README.md) 描述的是 minimal Axum service，先把 OpenAI Realtime WebSocket hot path 放進 Rust。專案拆成 core、gateway 和 Python bridge，啟動時仍能呼叫 Python proxy 讀取 model config，request log 也會送回 Python LiteLLM proxy，完整 spend logic 尚未移進 Rust gateway。

依目前公開內容，把它稱為 `staging · hybrid · Realtime-first` 比較準確。這個方向可能改善特定 streaming hot path，卻還沒有回答 team／user state、identity mapping、GitOps reconciliation 和 control-plane ownership，也沒有本系列親自跑過的 benchmark 可以證明效能或安全性已經超車。

## 選型結果與責任邊界

我們最後把 agentgateway 放在 LLM、MCP、A2A runtime traffic 的共同 policy／telemetry checkpoint，因為它的 Kubernetes control plane 比較符合既有 GitOps 工作方式。Identity provider、client registration、Agent runtime、Tool ownership、delegation context 和 telemetry backend 仍由各自的系統負責，沒有因為選了一個 Gateway 就全部消失。

LiteLLM 的 routing、virtual key、budget、spend 和 UI 依然很實用。當初真正用錯的是把 virtual key 同時當成 consumer isolation、用量歸屬與 Human identity，讓一把 key 扛了太多語意。

下一篇會把這筆帳拆開。Human virtual key、workload consumer key 和 JWT principal 都能讓 request 通過，rotation、offboarding、delegation 與 audit 留下來的答案卻完全不同。

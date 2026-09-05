# 當企業導入 Agent：30 天拆解治理邊界與平台選型

這裡放 iT 邦幫忙 30 天鐵人賽的文章、正文引用的圖表與實作素材，以及讀者可以直接執行的 Lab。

系列從一個真的會呼叫 Tool 的 Google ADK Agent 開始，依序處理 Identity、Delegation、Gateway、Runtime 與 Traceability。每篇文章只解一個當天碰得到的問題；做過的取捨、失敗路徑和可重現證據都會一起留下。

## 從這裡開始

- [閱讀 Day 1 文章](articles/day-01/article.md)
- [閱讀 Day 2 文章](articles/day-02/article.md)
- [閱讀 Day 3 文章](articles/day-03/article.md)
- [閱讀 Day 4 文章](articles/day-04/article.md)
- [閱讀 Day 5 文章](articles/day-05/article.md)
- [閱讀 Day 6 文章](articles/day-06/article.md)
- [閱讀 Day 7 文章](articles/day-07/article.md)
- [閱讀 Day 8 文章](articles/day-08/article.md)
- [閱讀 Day 9 文章](articles/day-09/article.md)
- [閱讀 Day 10 文章](articles/day-10/article.md)
- [閱讀 Day 11 文章](articles/day-11/article.md)
- [閱讀 Day 12 文章](articles/day-12/article.md)
- [閱讀 Day 13 文章](articles/day-13/article.md)
- [閱讀 Day 14 文章](articles/day-14/article.md)
- [下載 Day 2 Agent Threat Model Worksheet](articles/day-02/threat-model-worksheet.md)
- [下載 Day 4 Agent Delegation Decision Table](articles/day-04/delegation-decision-table.md)
- [下載 Day 5 Agent Governance 四問 Checklist](articles/day-05/governance-four-question-checklist.md)
- [下載 Day 6 Identity Center 組織選型 Decision Record](articles/day-06/identity-center-decision-matrix.md)
- [下載 Day 7 Human／Service／Agent／Workload Identity Flow Matrix](articles/day-07/identity-flow-matrix.md)
- [下載 Day 8 Token Claim Boundary](articles/day-08/token-claim-boundary.md)
- [下載 Day 9 Delegation Context Field Guide](articles/day-09/delegation-context-field-guide.md)
- [下載 Day 10 Token Passthrough Audit Reading Guide](articles/day-10/token-passthrough-audit-guide.md)
- [下載 Day 11 OAuth Flow 選擇與故障判讀表](articles/day-11/oauth-flow-selection-guide.md)
- [下載 Day 12 Human／M2M 雙路徑盤點表](articles/day-12/cognito-dual-path-checklist.md)
- [下載 Day 13 AI Gateway 平台選型 Scorecard](articles/day-13/gateway-selection-scorecard.md)
- [下載 Day 14 Credential Decision Table](articles/day-14/credential-decision-table.md)
- [直接執行 Day 1 Lab](labs/01-unsafe-agent/README.md)
- [直接執行 Day 8 JWT Lab](labs/02-identity-boundary/README.md)
- [直接執行 Day 9 Delegation Context Lab](labs/02-identity-boundary/README.md)
- [直接執行 Day 10 Token Passthrough Lab](labs/02-identity-boundary/README.md)
- [直接執行 Day 11 OAuth Flow Lab](labs/02-identity-boundary/README.md#day-11-oauth-flow-執行結果)
- [直接執行 Day 12 Cognito 雙路徑 Lab](labs/02-identity-boundary/README.md#day-12-cognito-dual-path-執行結果)
- [直接執行 Day 14 Credential Boundary Lab](labs/03-gateway-runtime/README.md)
- [查看 Day 1 Lab source code](labs/01-unsafe-agent/src/unsafe_agent/)
- [查看 Identity Boundary Lab source code](labs/02-identity-boundary/src/identity_boundary/)
- [查看 Gateway Runtime Lab source code](labs/03-gateway-runtime/src/gateway_runtime/)

文章第一行就是標題，不含編輯 metadata；圖片與 Lab 連結也能離開 GitHub 單獨使用，因此可以直接貼進 iT 邦幫忙編輯器。

## Labs

- [Day 1–5｜Unsafe Agent](labs/01-unsafe-agent/README.md)：Google ADK Agent、間接 Prompt Injection、Threat Model、Tool authorization、Delegation evidence 與治理四問盤點。
- [Day 8–12｜Identity Boundary](labs/02-identity-boundary/README.md)：JWT validation、Delegation Context、Token passthrough、OAuth flow 與 Cognito Human／M2M contract。Day 8 可先執行離線 JWT case，後續路徑會隨系列逐篇解說。
- [Day 14｜Gateway Runtime](labs/03-gateway-runtime/README.md)：用同一個 agentgateway 比較 Human virtual key、workload consumer key 與 Human JWT，重現 offboarding gap、key rotation、issuer／audience validation 與 provider credential isolation。

Lab 保留 README、source code、tests、fixture 與 lockfile。文章中的圖片是閱讀輔助，完整指令和可搜尋的結果仍以 repo 內容為準。

## 快速驗證

```bash
make lab-01-check
make lab-01-fixture
make lab-03-check
make lab-03-fixture
make lab-02-check
make lab-02-demo
make lab-02-delegation
make lab-02-passthrough
make lab-02-oauth
make lab-02-cognito
make lab-03-runtime-check
make lab-03-runtime-run
```

`make lab-02-cognito-config-check` 另外需要 Terraform 與 Docker。它只驗證 Terraform provider schema 及 agentgateway 設定，不會建立 AWS 資源，也不會啟動 MCP target。需要 live model 或 container 的其他步驟，請依各 Lab README 準備環境；`.env.example` 只列變數名稱，不包含任何 credential。

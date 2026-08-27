# 當企業導入 Agent：30 天拆解治理邊界與平台選型

這裡放 iT 邦幫忙 30 天鐵人賽的文章、正文引用的圖表與實作素材，以及讀者可以直接執行的 Lab。

系列從一個真的會呼叫 Tool 的 Google ADK Agent 開始，依序處理 Identity、Delegation、Gateway、Runtime 與 Traceability。每篇文章只解一個當天碰得到的問題；做過的取捨、失敗路徑和可重現證據都會一起留下。

## 從這裡開始

- [閱讀 Day 1 文章](articles/day-01/article.md)
- [閱讀 Day 2 文章](articles/day-02/article.md)
- [閱讀 Day 3 文章](articles/day-03/article.md)
- [閱讀 Day 4 文章](articles/day-04/article.md)
- [下載 Day 2 Agent Threat Model Worksheet](articles/day-02/threat-model-worksheet.md)
- [下載 Day 4 Agent Delegation Decision Table](articles/day-04/delegation-decision-table.md)
- [直接執行 Day 1 Lab](labs/01-unsafe-agent/README.md)
- [查看 Lab source code](labs/01-unsafe-agent/src/unsafe_agent/)

文章第一行就是標題，不含編輯 metadata；圖片與 Lab 連結也能離開 GitHub 單獨使用，因此可以直接貼進 iT 邦幫忙編輯器。

## Labs

- [Day 1–4｜Unsafe Agent](labs/01-unsafe-agent/README.md)：Google ADK Agent、間接 Prompt Injection、Threat Model、Tool authorization 與 Delegation evidence。

Lab 保留 README、source code、tests、fixture 與 lockfile。文章中的圖片是閱讀輔助，完整指令和可搜尋的結果仍以 repo 內容為準。

## 快速驗證

```bash
make lab-01-check
make lab-01-fixture
make lab-03-check
make lab-03-fixture
```

需要 live model 或 container 的步驟，請依各 Lab README 準備環境；`.env.example` 只列變數名稱，不包含任何 credential。

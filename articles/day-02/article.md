# Day 2｜Agent Threat Model 實作：從 Prompt Injection 到 Tool 執行的七道邊界

Day 1 的 SRE Investigation Agent 做了一件不該做的事。它讀到一段被動過手腳的 Log 後，沒有停在分析，而是向 Google ADK 提出 `delete_demo_database` 的 Tool Call。Lab 裡的 Tool 只是 safe canary，不會刪資料。但從模型提案、policy 放行到 Function Tool 被呼叫，這條動作路徑真的走完了。

當時留下三筆關鍵事件：

```text
03:24:46  model.tool_call   delete_demo_database
03:24:46  policy.decision   ALLOW
03:24:46  tool.executed     CANARY_TRIGGERED
```

如果只看攻擊入口，這當然是 Prompt Injection。問題是，修補方式也很容易直覺地停在 Prompt、關鍵字與輸入過濾。

把三筆 event 放回執行順序後，我在意的事情變了。不可信 Log 先影響模型，模型再提出動作，`open` policy 接著放行，最後才由 Tool 觸發 safe canary。從內容進入 context 到 Tool 真正執行，中間其實不只一次可以拒絕。

Day 2 就沿用這個 Agent 與 `trace_id=a281375fdcb5516c8983eada8ff11c9b`。我要把同一次執行拆成 trust boundary，找出每個元件接手之前，原本應該做、卻沒有做的決策。

這篇沿用 Day 1 的合成 Lab，不是真實事故。Threat Model 的邊界來自這筆 [公開的 ordered events](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04/assets/screenshots/day-01/evidence/live-events.jsonl)。OWASP 與 NIST 的官方資料則用來確認威脅名稱，沒有拿來代替 Lab 證據。

## 一條 Trace，七道信任邊界

我把這次執行依 event 順序切成七段。每跨過一個元件，就重新問一次：「上一層建立的信任，能不能直接帶到下一層？」

| ID | From → To | 這一層該回答的事 | Day 1 證據 |
| --- | --- | --- | --- |
| TB-01 | Caller／Job → Agent Runtime | 誰啟動？Agent 正代表誰？ | `UNKNOWN`，event 沒有 human principal 或 delegation context |
| TB-02 | External Log → Model Context | 外部資料和可信 instruction 有沒有分開？ | 已觀察：Log 內容影響模型的 Tool 選擇 |
| TB-03 | Runtime → Gemini | 哪些資料可以送往模型供應商？ | `UNKNOWN`，Lab 沒有資料分類與 provider policy |
| TB-04 | Model → Action Proposal | 模型提出動作，是否被誤當成已授權？ | 已觀察：模型提出 `delete_demo_database` |
| TB-05 | Proposal → Policy／Tool | 執行前有沒有獨立的 ALLOW／DENY？ | 已觀察：`open` policy 一律 `ALLOW` |
| TB-06 | Tool → Target Resource | Tool 最後拿誰的 credential、能碰哪些資源？ | `UNKNOWN`，safe canary 沒有連真實資料庫 |
| TB-07 | Ordered Events → Run Summary | 摘要有沒有保留已發生的高風險動作？ | 已觀察：後續 `SUCCESS` 曾蓋掉 canary 結果 |

我把它編成 TB-01 到 TB-07，只是為了後面方便對照。Day 1 有證據的只有 TB-02、TB-04、TB-05 與 TB-07。至於誰啟動 Agent、哪些資料可以送到 Gemini，以及 Tool 連到正式資源時會帶什麼 credential，這個 Lab 都沒有答案。

我寧可把這三格留成 `UNKNOWN`，也不想用一個沒有 backend credential 的 safe canary 推論正式環境權限。後面的 Identity、Policy 與 Audit，會沿著這三個未解欄位繼續補證據。

## 從固定 Route 到動態 Action Path

我長期從 API Gateway 的角度看流量，第一版也很自然地畫成 Client、Authentication、Authorization、Backend。那張圖沒有錯，卻把 action selection、Tool credential 和回饋迴圈全塞進「Agent」方框，最需要檢查的地方反而看不見。

傳統 Web 應用同樣會遇到 injection、SSRF、越權與 confused deputy。Agent 沒有發明一套全新的資安問題，改變的是資料如何進入決策，以及決策如何跨進有副作用的動作。

| 面向 | 一般 Web Request | Agent Run |
| --- | --- | --- |
| 動作路徑 | Route 與 handler 多半由程式碼預先決定 | 模型可以動態選擇 Tool 與 arguments |
| 輸入來源 | Request fields 進入既定處理流程 | Prompt、文件、Log、memory、Tool result 可能進入同一份 Context |
| 執行週期 | 多半是一個 request／response | 可以反覆推理、呼叫 Tool，再把結果送回下一輪 |
| 執行身分 | 常見是 user session 與 service identity | 還要區分 human、delegating Agent、workload 與 downstream credential |
| 結果判讀 | HTTP status 與 backend transaction | Run 尚未結束，副作用可能已經發生 |

下圖把兩條路徑放在一起。流程語意標在箭頭上方，不必靠顏色猜意思：Agent path 多了不可信資料進入 Context、模型提出 action proposal、獨立 policy 決策，以及 Tool result 回到下一輪的 loop。

![一般 Web request 依程式碼固定路徑執行，Agent run 則加入外部資料、模型 action proposal、獨立授權與 Tool result 回饋迴圈。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04/assets/diagrams/day-02/web-vs-agent-attack-surface.png)

圖裡最麻煩的地方，是 Agent 把 data path 和 action path 接在一起了。它剛從 Log 讀到的內容，下一步可能就拿來選 Tool。Tool 回傳的結果，又會被放回 context 影響下一輪。傳統 Web 的輸入驗證當然還要做，但光守住入口，已經不足以處理這種會反覆執行的流程。

## Prompt Injection 解釋入口，Excessive Agency 解釋後果

[OWASP LLM01:2025](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) 把網站、檔案等外部來源中的惡意內容歸為 indirect prompt injection。[NIST CAISI 對 Agent Hijacking 的說明](https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations)也指出，問題來自系統沒有清楚分開 trusted internal instructions 與 untrusted external data。

Day 1 的合成 Log 就是這種形狀。不過我刻意把 Agent instruction 寫得很差，讓它採信 Log 裡假裝成 runbook 的操作指示。這個 Lab 只用來建立可重現的失守基線，不拿來評比 Gemini 的防護能力。

至於模型被騙以後能造成多大損害，就要接著看 [OWASP LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) 拆出的三個根因：

| 根因 | Day 1 的狀態 | 能否由 Lab 證明 |
| --- | --- | --- |
| Excessive functionality | Investigation Agent 看得到 `delete_demo_database` | 可以，model output 已留下 Tool proposal |
| Excessive permissions | Tool 是否持有真實資料庫的刪除權限 | 不行，safe canary 沒有 backend credential |
| Excessive autonomy | 高風險動作是否需要獨立核准 | 可以，`open` policy 直接放行 |

如果把 Day 1 只當成 Prompt Injection，我第一個反應會是補 input guard。但把它和 LLM06 放在一起看，修法就不能只停在入口。Input guard 可以過濾已知 pattern，也能標記不可信來源。它回答的是「這段內容像不像攻擊」，卻不能回答某個 actor 是否有權操作某個 resource。

我會保留 input guard，但不把它當最後一道防線。就算模型照樣被騙，Tool catalog 可以先拿掉不需要的功能，credential 也不該比任務需要的更大。到了真正要執行時，獨立 policy 或人工核准還能再擋一次。安全設計不能假設模型每次都會判斷正確。

## 把 Threat Model 寫成可審查的 Worksheet

架構圖適合找邊界，真正進 design review 時，還是需要一份能填寫、能留下 `UNKNOWN` 的盤點表。我把 Day 1 的拆解整理成 [Agent Threat Model Worksheet](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04/articles/day-02/threat-model-worksheet.md)，內容分成六組：

- Task boundary：誰能啟動、代表誰、何時停止。
- Context inventory：哪些資料會進模型，來源由誰控制。
- Identity 與 credential：每一 hop 使用什麼身分，最後能碰哪個 resource。
- Tool inventory：讀寫能力、獨立 policy、人工核准與 rate limit。
- Trust boundary：每次跨界的假設、decision point、failure mode 與 evidence。
- Event／audit：事後能否重建 proposal、decision 與實際副作用。

從公開 repo 複製後，可以直接拿自己的 task 取代 Day 1 範例：

```bash
git clone https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public.git
cd 2026-ithelp-agent-governance-public
cp articles/day-02/threat-model-worksheet.md my-agent-threat-model.md
```

最後一格不要只填 `Prompt Injection`。一個可審查的 abuse case，至少要交代攻擊者控制了哪份資料、哪個 Agent 或 workload 使用哪個 credential、目標 resource 是什麼，以及預期由哪個 decision point 拒絕。

套回 Day 1，會得到這樣的句子：

```text
當攻擊內容進入 Agent 讀取的 Log，
它可能讓 SRE Investigation Agent 使用尚未建模的執行身分，
對 payments-demo 提出 delete_demo_database，
Tool authorization 應在執行前拒絕，
並保存 model proposal、policy decision、Tool result 與 ordered events。
```

把 abuse case 寫到 actor、credential、resource 與 decision point，design review 就不會只得到一個 `Prompt Injection` 標籤，也能直接看到該在哪裡加控制。

## 下一步：讓 Policy 真正拒絕 Tool

把 Day 1 的 trace 拆完後，可以看見四個已發生的節點：惡意內容在 TB-02 進入 context，模型在 TB-04 提出動作，`open` policy 在 TB-05 放行，Tool 才真的執行。TB-06 的 credential 與 resource 權限仍是 `UNKNOWN`，因此這篇不替正式環境下結論。

下一篇繼續使用同一個 Agent 和 safe canary，實際加入 keyword guard 與 Tool allowlist。明顯攻擊先讓 guard 擋，再把惡意內容換一種寫法，看看它通過輸入檢查後，Tool authorization 能不能在執行前獨立回覆 `DENY`。

# Day 15 Screenshot Evidence

Status：complete。

## Environment

```text
Tested:       2026-09-05 Asia/Taipei
Python:       3.14.5
PyJWT:        2.13.0
agentgateway: v1.5.0 pinned image digest
Docker:       29.4.0
```

Pinned image digest：`sha256:bf2f339ef326d32def2aaeb44b1b4549801293c19b89e764a4228667d97d9896`。

## Commands executed

```bash
make lab-03-runtime-check
make lab-03-runtime-traffic
```

Final result：27 tests passed，branch coverage 85.53%，Ruff lint／format clean；pinned agentgateway image 對公開 YAML 回傳 `Configuration is valid!`。Live container 的六個 traffic case 全部符合預期。

## Actual result

- 一般 OpenAI-compatible JSON response 得到 `200 application/json`。
- SSE 得到 `200 text/event-stream`；第一個 event 在 upstream 完成前抵達，完整順序為 `lab-`、`ok`、`[DONE]`。
- 缺 caller credential 與錯誤 caller credential 都得到 `401`，synthetic backend request count 都是零。
- Synthetic provider 的 `429`、`Retry-After: 7` 與 error code 都傳回 caller；provider request count 為一。
- Backend 收到 agentgateway 注入的 provider credential，沒有收到 caller key。
- Ephemeral caller key、invalid key、provider key、private JWK 欄位與 PEM private-key marker 都沒有落入 evidence artifact。

## Validation boundary

| Evidence | 能證明 | 不能證明 |
| --- | --- | --- |
| Live standalone Lab | pinned agentgateway 在單一 proxy 路徑上的 JSON、SSE、strict caller auth、backend auth 與 upstream `429` 傳遞 | Production Kong、Kubernetes controller、HA、吞吐或雙層 timeout 行為 |
| Upstream request counter | retry disabled 時 synthetic `429` 只送達 provider 一次 | 所有 provider、network failure 或開啟 retry 後仍只呼叫一次 |
| SSE fixture | `text/event-stream` 與三個 data event framing／順序保留 | 長時間 heartbeat、MCP session、A2A streaming、response guard 或 body-transform 組合 |
| 去識別化實務 topology | 作者實務責任切分的 owner 與 fail-closed 原則 | 原公司 deployment、domain、namespace、Kong plugin 或 production failure drill 已公開重現 |

## Presentation method

`01-traffic-boundary-results.png` 由本次 `make lab-03-runtime-traffic` 的 `traffic-terminal.txt` 在本機重新排成 terminal card，再以 headless Chrome 匯出 1600 × 1000 PNG。一次性 HTML template 已在匯出後刪除。圖片不包含 credential，正文另保留 command、redacted config、可讀表格與 machine-readable JSON。

## Image

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-traffic-boundary-results.png` | `b34a164c334a53f119954e5d6a1ae93d9aa7123dd5ce38c28acadee4eb7d138e` | `day15-20260905T131412Z` | none；畫面只使用 safe summary | PASS |

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/agentgateway-config.redacted.json` | `1b880bcf8e3010d7e45cedc162de8f6f39e8a1dc0aead289bad7602ab3958e77` |
| `evidence/config-validation.json` | `1c6f4cade470b2acb95a0b696f3a7d0ebefc39c31a9f39e0d9320207597ee3cd` |
| `evidence/manifest.json` | `c7781fa1d74333af3423761e7255c8d649cbb17caedf1a3b7eb86f474096333d` |
| `evidence/traffic-decision-table.md` | `3f5d615e7eb368e813145086037dd81a576d3619d2570d1e0b9114a2bcc8351a` |
| `evidence/traffic-report.json` | `3df462cdf4043e4988f54a40701e41806d5f091f656560b2d50c6e63cec308a1` |
| `evidence/traffic-terminal.txt` | `0975013fcf5e496c11868a40395c37b9c44fe7d0fe463745d0be04e93a5aee9e` |

## Config and diagram

- `labs/03-gateway-runtime/configs/agentgateway.example.yaml`：`bea2ee2e44b832b67357206b6ab1f8a7fdc22ffe227cd9c93b0cc0046c81ebec`
- `diagrams/src/day-15/ingress-boundary.mmd`：`b39b0284ac0f8b2eebf0e5b5860157041310b3e3137baf0b92609cfe8030db2a`
- `diagrams/svg/day-15/ingress-boundary.svg`：`2a8187ea3c8ebdfecd725aca65f9e8efd2ac93966f189e2cacd138aa111abaed`
- `assets/diagrams/day-15/ingress-boundary.png`：`d788624b8412fe6ddf1e7217724d16525492bae8cc8e94e9be11d90294c0a9db`

SVG 已通過 `xmllint`，並以 1600 × 900 viewport 視覺檢查。主 request path 只保留四個節點，箭頭不穿過文字；identity、telemetry 與 fail-closed 改放在下方三張 contract card。公開文章使用 PNG，SVG 與 Mermaid source 留在作者工作區。

## Cleanup

```bash
make lab-03-runtime-down
```

這個 command 只刪除 Lab root 下、帶正確 `.lab-03-artifacts` marker 且不是 symlink 的 `artifacts/`。

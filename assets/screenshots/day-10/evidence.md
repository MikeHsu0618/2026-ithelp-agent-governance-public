# Day 10 Screenshot Evidence

Status：complete。

2026-08-26 的 terminal 圖保留原始 7/7 case outcome；下方 committed machine evidence 於 2026-09-01 重新產生，修正 downstream runtime Service actor 的證據來源。

## Environment

```text
Tested:    2026-09-01
Python:    3.14.5
PyJWT:     2.13.0
jsonschema: 4.26.0
pytest:    9.1.1
MCP spec:  2026-07-28 (document reference only)
```

## Commands executed

```bash
make lab-02-up
make lab-02-check
make lab-02-passthrough
```

依賴安全檢查：

```bash
uv export --directory labs/02-identity-boundary \
  --format requirements-txt --no-dev --no-hashes --no-emit-project |
uvx pip-audit --requirement /dev/stdin --progress-spinner off
```

Build：

```bash
uv build --directory labs/02-identity-boundary
```

## Actual result

- 7 組 passthrough、audience-bound credential 與 context-binding case 全部符合預期。
- 同一枚值班工程師 Token 在 Agent entry ALLOW，原樣送到 Observability MCP 時由嚴格 validator 回 `AUDIENCE_MISMATCH`。
- 下游改為接受入口 audience／client profile 後 ALLOW，但 attribution 為 `COLLAPSED_TO_TOKEN_SUBJECT`。
- 下游專用 Token 搭配正確 Delegation Context 得到 `FULL_CHAIN`；回放到入口、缺 Context 與 fingerprint 不符都被拒絕。
- Downstream runtime 通過 client authentication，因此 `service=client/sre-investigator-runtime` 為 `PRESENT／VERIFIED`；public Human client 沒被拿來填 Service actor。
- 完整 Lab 02 為 72 tests passed，branch coverage 91.17%。
- Dependency audit 回傳 `No known vulnerabilities found`；wheel 與 source distribution build 成功。

## Presentation method

`01-passthrough-results.png` 由 2026-08-26 的 `identity-boundary passthrough` 實際 CLI output 重新排成 Carbon 類型 terminal card，再輸出為 1600 × 1050 PNG。圖片顯示的 decision 與 attribution 在 2026-09-01 重跑後沒有改變。

正文保留可複製 command 與文字輸出。圖片不是唯一證據；manifest、summary、events、正向 Context 與 Token fingerprints 保存在 `evidence/`。下列 machine evidence 來自 `day10-20260901T065911Z-024490f2`，7/7 case 符合預期。

所有 Human、Agent、Workload、issuer、resource、client 與 scope 都是合成值。Compact JWT、RSA private key、公司 domain 與 production event 沒有進入圖片或 committed evidence。被 audience validation 拒絕的 case 不把 unverified claim 寫成 authenticated principal。

## Image

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-passthrough-results.png` | `7ec530f4418352e86bbddb11daa755f9fc14637aa1262cb24c0156d883cc21e3` | `day10-20260826T143807Z-64adf942` | none；CLI 原始輸出使用相對 artifact path | PASS |

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/demo-manifest.json` | `aa93249f319f188b13cec3b5cad075e1b2344a5886bfbe8896dff8679606169e` |
| `evidence/demo-summary.json` | `3a2c02f16b39222c0aad1f3cf45032ddd251158b90fe93c8879fca6e33d241dd` |
| `evidence/demo-events.jsonl` | `0d045ab3229390ade4779bd9ab89a9a2895a05dcd85b534dcea8f67b6fa6e74c` |
| `evidence/demo-context-audience-bound.json` | `9d1509aea5f08fb33ccfd3d6c94e1a9d60f73931891b40c2b490db62af609a6e` |
| `evidence/demo-token-fingerprints.json` | `63d56e294752606e4328f4b0ec2cdc884d21fe9f2a1a925c85232d8404b71db3` |

## Cleanup

```bash
make lab-02-down
```

這個 command 只刪除帶正確 `.lab-02-artifacts` marker、位於 Lab 02 root 下且不是 symlink 的 `artifacts/`。

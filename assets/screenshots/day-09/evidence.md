# Day 9 Screenshot Evidence

Status：complete。

這份文件分開記錄兩次驗證：2026-08-26 的 terminal 圖保留 Day 9 完成當下的 7/7 結果；committed machine evidence 則在 2026-09-01 發稿前重新產生，確認 Human／A2A flow 不會把 public client context 冒充 Service actor。

## Environment

```text
Tested:    2026-09-01
Python:    3.14.5
jsonschema: 4.26.0
pytest:    9.1.1
```

## Commands executed

```bash
make lab-02-up
make lab-02-check
make lab-02-delegation
```

依賴安全檢查：

```bash
uv export --directory labs/02-identity-boundary \
  --format requirements-txt --no-dev --no-hashes --no-emit-project |
uvx pip-audit --requirement /dev/stdin --progress-spinner off
```

## Publication preflight（2026-09-01）

從 repo root 重新執行：

```bash
make lab-02-check
make lab-02-delegation

uv export --directory labs/02-identity-boundary \
  --format requirements-txt --no-dev --no-hashes --no-emit-project |
uvx pip-audit --requirement /dev/stdin --progress-spinner off
```

目前共用 Lab 02 為 72 tests passed、branch coverage 91.17%，Ruff lint／format check 通過。Delegation slice 仍為 7/7 matched，`Raw credential persisted: no`，dependency audit 也通過。2026-08-26 截圖的七組結果沒有改變；下方 machine evidence 已換成這次重跑的輸出。

## Actual result

- 7 組正向／負向 Delegation Context 全部符合預期。
- Human delegated、scheduled service 與明確標示 `UNKNOWN` 的 A2A case 通過。
- 缺 workload slot、Human 為 `null`、Agent sequence 重複與 actor-only record 被拒絕。
- Human delegated 與 A2A case 的 `service_state` 都是 `NOT_APPLICABLE`；public `client_id` 只留在 credential context。
- 完整 Lab 02 為 72 tests passed，branch coverage 91.17%。
- Dependency audit 回傳 `No known vulnerabilities found`。
- Wheel build 已確認包含 `delegation-context-v0.1.schema.json`，installed CLI 不依賴 repo-relative path。

## Presentation method

`01-delegation-context-results.png` 由 2026-08-26 的 `identity-boundary delegation` 實際 CLI output 重新排成 Carbon 類型 terminal card，再輸出為 1600 × 1050 PNG。它顯示的 case outcome 在 2026-09-01 重跑後仍維持 7/7。

圖片不是唯一證據；manifest、summary、events 與完整正向 context 保存在 `evidence/`。下列 machine evidence 來自 `day09-20260901T065424Z-ba745470`，用來檢查每個 identity state 與完整 context。

所有 Human、Service、Agent、Workload、issuer、client ID、resource 與 action 都是合成值。Raw bearer token、private key、公司 domain 與 production event 沒有進入圖片或 committed evidence。

## Image

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-delegation-context-results.png` | `1b11eac9ea4375e8adc19b573e86891529122bbc7555df04d5abceb59c7d5153` | `day09-20260826T143807Z-2018465b` | none；CLI 原始輸出使用相對 artifact path | PASS |

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/demo-manifest.json` | `0f598c2da0434480fb8a679eaf9906e6f7b94e8850b8b58a9963ef4a4fed9ef8` |
| `evidence/demo-summary.json` | `e760f285f3090480ac8564fdc9ac200e9860d5e50f2dc3007d39324586f74872` |
| `evidence/demo-events.jsonl` | `10e95c662f5e4c178df1f54b67a301ad624a4e3b8138f17b640a56c89794ceaa` |
| `evidence/demo-context-human-delegated.json` | `7d94a522df33b686543808f6391ca5687f5ee36338f757cde45bc67e0b91d896` |
| `labs/02-identity-boundary/.../delegation-context-v0.1.schema.json` | `f080f54b3e0a6327af022d65f24758bed1a60929921cfed65304ebdc31e6ea56` |

## What to inspect

- `a2a_unknown_workload` 使用 `UNKNOWN` 而非捏造 principal，仍通過 schema。
- `actor_only` 沒有 actor chain、credential、target 或 trace，因此回 `REQUIRED_FIELD_MISSING`。
- `duplicate_agent_sequence` 通過欄位 schema，再由 semantic validator 回 `AGENT_SEQUENCE_INVALID`。
- Manifest 的 `raw_credentials_persisted` 是 `false`，完整證據掃描也找不到 compact JWT 或 private-key marker。
- `human_delegated` 的 public client ID 留在 credential context，`service` slot 為 `NOT_APPLICABLE`。
- Fixture hash 為 `sha256:8c6f89aab0a4161f1211130b88d74c665cb9c85ed932d2647d6574a91396fe96`。

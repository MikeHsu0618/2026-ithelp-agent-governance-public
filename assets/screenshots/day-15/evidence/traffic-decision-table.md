| Case | HTTP | Matched | Evidence |
| --- | ---: | --- | --- |
| normal-json | 200 | PASS | status preserved |
| sse-stream | 200 | PASS | SSE lab- / ok / DONE |
| missing-caller-credential | 401 | PASS | upstream_requests=0 |
| invalid-caller-credential | 401 | PASS | upstream_requests=0 |
| upstream-rate-limit | 429 | PASS | Retry-After=7; upstream_requests=1 |
| backend-credential-isolation | 200 | PASS | provider=MATCHED; caller_forwarded=false |

| Responsibility | Owner | Source of truth |
| --- | --- | --- |
| Agent business logic | Application Team | Agent source 與 runtime tests |
| Agent deployment | kagent | `Agent` CR 與 generated Deployment |
| Agent discovery | kagent | Agent status 與 Agent Card |
| LLM traffic policy | agentgateway | Gateway route 與 policy |
| MCP traffic policy | agentgateway | Gateway route 與 policy |
| Credential acquisition／refresh | Identity Platform／Application Team | Workload identity 與 token lifecycle |
| Runtime telemetry | kagent／Application Team | Runtime span 與 action event |
| Traffic telemetry | agentgateway | Gateway access log、metric 與 trace |

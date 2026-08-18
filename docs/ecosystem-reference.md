# Ecosystem Reference

Condensed practical reference for the OSS stack used in this project. All commands, package
names, image paths, and API versions below were validated against live registries and docs
on 2026-08-17.

Targets:
- (a) eval pipeline scoring agent behavior from OTel traces → **agentevals**
- (b) kagent fleet-sre agent on k3d with Ollama → **kagent**, **Ollama in Docker**
- (c) Python MCP servers (streamable HTTP) + minimal A2A surface → **MCP Python SDK**, **A2A**

---

## 1. agentevals (aevals.ai, github.com/agentevals-dev/agentevals)

Framework-agnostic evals scored from OpenTelemetry traces. Never re-runs the agent.
Apache 2.0. Latest release: **v0.9.8** (moves fast — "expect breaking changes").

### Install — package name gotcha

```bash
pip install agentevals-cli          # <-- THE Solo/agentevals-dev project (CLI + REST API + web UI)
pip install "agentevals-cli[live]"     # adds MCP server support
pip install "agentevals-cli[openai]"   # OpenAI Evals API graders
pip install "agentevals-cli[streaming]"  # AgentEvals SDK session/decorator API
pip install agentevals-evaluator-sdk   # separate package: SDK for writing custom evaluators
```

> **WARNING:** `pip install agentevals` (no `-cli`) installs an **unrelated LangChain package**
> (v0.0.9, "Open-source evaluators for LLM agents"). The docs site's quick-start page says
> `pip install agentevals` but the README/PyPI badge say `agentevals-cli` — use `agentevals-cli`.
> (One code block inside docs/custom-evaluators.md also shows the bare name; it's wrong.)

### How it consumes OTel traces — three ways

1. **Trace files on disk** (CLI, offline, CI): Jaeger JSON or native OTLP JSON files.
   `agentevals run trace.json --eval-set eval_set.json -m tool_trajectory_avg_score`
2. **Built-in OTLP receiver** (live): `agentevals serve` starts UI/API on **8001** plus an
   OTLP receiver on **4318 (HTTP)** and **4317 (gRPC)**. Point any OTel-instrumented agent at it:

   ```bash
   # Terminal 1
   agentevals serve --dev

   # Terminal 2
   export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
   export OTEL_RESOURCE_ATTRIBUTES="agentevals.session_name=my-agent"
   python your_agent.py
   ```

   For gRPC exporters: `OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317`,
   `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`. Sessions group by `agentevals.session_name`;
   set `agentevals.eval_set_id` to associate traces with an eval set.
3. **As an exporter destination in an OTel Collector pipeline** (Kubernetes) — the receiver
   is "just another exporter destination". `examples/kubernetes/` in the repo is an
   end-to-end walkthrough with **kagent + OTel Collector** — directly our architecture.

Requires OTel **GenAI semantic conventions** spans (model calls, tool calls, agent
invocations). kagent's tracing emits these. Claude Code/Codex-style log telemetry does NOT work.

### Eval set format (golden traces) — JSON, Google ADK `EvalSet` schema

```json
{
  "eval_set_id": "helm_eval_set",
  "eval_cases": [
    {
      "eval_id": "helm_list_releases",
      "conversation": [
        {
          "invocation_id": "inv-1",
          "user_content": {"role": "user", "parts": [{"text": "list all Helm releases"}]},
          "final_response": {"role": "model", "parts": [{"text": "There are two Helm releases..."}]},
          "intermediate_data": {
            "tool_uses": [{"name": "helm_list_releases", "args": {}, "id": "call_1"}],
            "tool_responses": [{"name": "helm_list_releases", "response": {"content": [{"type": "text", "text": "..."}], "isError": false}, "id": "call_1"}]
          }
        }
      ]
    }
  ]
}
```

Multi-turn = multiple invocations in `conversation`. Built-in metrics and what they need:

| Metric | Needs eval set | Reads |
|---|---|---|
| `tool_trajectory_avg_score` | yes | `intermediate_data.tool_uses` |
| `response_match_score` | yes | `final_response` (ROUGE-1) |
| `final_response_match_v2` | yes | `final_response` (LLM judge) |
| `hallucinations_v1`, `safety_v1` | no | — |

Trajectory matching modes: `--trajectory-match-type EXACT | IN_ORDER | ANY_ORDER`.

### Custom evaluators — any language, JSON over stdin/stdout

An evaluator is any program reading `EvalInput` JSON from stdin, writing `EvalResult` JSON
to stdout. Scaffold: `agentevals evaluator init my_evaluator` (`--runtime js` for JS/TS).

```python
# evaluators/no_denied_calls.py  — "no denied calls" style deterministic check
from agentevals_evaluator_sdk import evaluator, EvalInput, EvalResult

@evaluator
def no_denied_calls(input: EvalInput) -> EvalResult:
    denied = set(input.config.get("denied_tools", []))
    scores = []
    for inv in input.invocations:
        called = {tc["name"] for tc in inv.intermediate_steps.get("tool_calls", [])}
        scores.append(0.0 if called & denied else 1.0)
    return EvalResult(score=min(scores) if scores else 1.0, per_invocation_scores=scores)

if __name__ == "__main__":
    no_denied_calls.run()
```

`EvalInput` fields: `protocol_version` ("1.0"), `metric_name`, `threshold`, `config`,
`invocations[]` (each: `invocation_id`, `user_content` str, `final_response` str|null,
`intermediate_steps.tool_calls[]` `{name, args}`, `intermediate_steps.tool_responses[]`
`{name, output}`), and `expected_invocations` (golden turns from the eval set, or null) —
use `expected_invocations` for "tool-call sequence matches golden trace" logic beyond the
built-in `tool_trajectory_avg_score`.
`EvalResult`: `score` (0.0–1.0, required), optional `status` ("PASSED"/"FAILED"/"NOT_EVALUATED"),
`per_invocation_scores[]`, `details{}`.

Eval config YAML (`--config eval_config.yaml`):

```yaml
evaluators:
  - name: tool_trajectory_avg_score
    type: builtin
  - name: no_denied_calls
    type: code
    path: ./evaluators/no_denied_calls.py
    threshold: 1.0
    timeout: 30            # subprocess seconds, default 30
    config:
      denied_tools: [k8s_delete_resource]
  # also: type: remote (source: github, ref: <path in community repo>)
  #       type: openai_eval (grader: {type: text_similarity|label_model, ...}; needs OPENAI_API_KEY)
```

### CLI for CI

```bash
agentevals run traces/run1.json traces/run2.json \
  --eval-set eval_set.json \
  --config eval_config.yaml \
  -m tool_trajectory_avg_score -m response_match_score \
  --output json
# Exit code gates the pipeline; --output json for machine-readable results. No server needed.
agentevals evaluator list [--source builtin|github]
```

### Container / Helm

- Image: **`ghcr.io/agentevals-dev/agentevals`** (tags = release versions, e.g. `0.9.8`; verified
  tags list on ghcr). Bundles API+UI (8001), OTLP receivers (4317/4318), MCP (8080, streamable HTTP).
- Helm (validated pull): `helm install agentevals oci://ghcr.io/agentevals-dev/agentevals/helm/agentevals`
  (chart 0.9.8, appVersion 0.9.8). Default backend is in-memory (nothing persisted);
  `--set storage.backend=postgres --set database.postgres.bundled.enabled=true` for run history.
- MCP server: `agentevals mcp` (tools: `evaluate_traces` works offline; `list_sessions`,
  `evaluate_sessions`, `summarize_session` need `agentevals serve` running).

---

## 2. kagent (kagent.dev, github.com/kagent-dev/kagent)

Latest published chart/tag: **0.9.12** (git has v0.10.0-rc tags, but
`oci://ghcr.io/kagent-dev/kagent/helm/kagent` resolves latest → **0.9.12**; verified with
`helm show chart`). Docs and 0.9.12 CRDs use **`apiVersion: kagent.dev/v1alpha2`**
(main branch already has v1alpha3 — pin your chart version).

### Install (OCI Helm, validated)

```bash
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent --create-namespace \
  --version 0.9.12

helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent \
  --version 0.9.12 \
  --set providers.default=openAI \
  --set providers.openAI.apiKey=$OPENAI_API_KEY
```

Notes:
- Default image registry in values is `cr.kagent.dev`; kmcp subchart is on by default
  (`--set kmcp.enabled=false` to drop), `kagent-tools` (builtin tool server) on by default.
- CLI alternative: `brew install kagent` or
  `curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash`,
  then `kagent install --profile demo` (or `--profile minimal` for no preloaded agents).

### Disable default agents (helm values, 0.9.12)

Default agents are top-level values keys, each with `enabled: true`:
`k8s-agent`, `kgateway-agent`, `istio-agent`, `promql-agent`, `observability-agent`,
`argo-rollouts-agent`, `helm-agent`, `cilium-policy-agent`, `cilium-manager-agent`,
`cilium-debug-agent`. Disable each explicitly:

```bash
--set k8s-agent.enabled=false \
--set kgateway-agent.enabled=false \
--set istio-agent.enabled=false \
--set promql-agent.enabled=false \
--set observability-agent.enabled=false \
--set argo-rollouts-agent.enabled=false \
--set helm-agent.enabled=false \
--set cilium-policy-agent.enabled=false \
--set cilium-manager-agent.enabled=false \
--set cilium-debug-agent.enabled=false
```

(On current main/0.10.x these agent blocks are gone from the chart entirely — agents come
from the CLI profile instead.)

### ModelConfig for Ollama (v1alpha2, from official docs)

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: ollama-model-config
  namespace: kagent
spec:
  provider: Ollama
  model: qwen3:4b
  ollama:
    host: http://ollama.ollama.svc.cluster.local     # 11434 implied; point at your Ollama svc
```

(The docs example also carries `apiKeySecret: kagent-openai` / `apiKeySecretKey: OPENAI_API_KEY`
fields, but they are not meaningful for Ollama.) Helm-generated default equivalent:
`--set providers.default=ollama --set providers.ollama.model=qwen3:4b --set providers.ollama.config.host=...`
(values also support `providers.ollama.config.options.num_ctx`). Docs warn: "make sure you're
using a model that allows function calling."

### Agent CRD (v1alpha2)

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: fleet-sre
  namespace: kagent
spec:
  type: Declarative
  declarative:
    modelConfig: ollama-model-config        # name of ModelConfig (same ns)
    systemMessage: |
      You are a fleet SRE agent. Investigate and remediate robot fleet issues.
    tools:
      - type: McpServer
        mcpServer:
          name: fleet-mcp                   # RemoteMCPServer name
          kind: RemoteMCPServer
          apiGroup: kagent.dev
          toolNames:                        # explicit allowlist, required
            - get_robot_status
            - restart_robot
          requireApproval:                  # optional human-in-the-loop per tool
            - restart_robot
```

Cross-namespace tool ref: add `namespace: tools` under `mcpServer` (target RemoteMCPServer
must permit it via `spec.allowedNamespaces`). Agents can also reference other agents as
tools (`namespace/name`).

### RemoteMCPServer CRD (v1alpha2, fields from Go types)

```yaml
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata:
  name: fleet-mcp
  namespace: kagent
spec:
  description: Fleet ops MCP server        # required
  protocol: STREAMABLE_HTTP                # enum SSE | STREAMABLE_HTTP (default STREAMABLE_HTTP)
  url: http://fleet-mcp.fleet.svc.cluster.local:8000/mcp   # required
  timeout: 30s                             # default 30s
  sseReadTimeout: 5m0s                     # optional
  terminateOnClose: true                   # default true
  # headersFrom:                           # optional; values resolved from Secret/ConfigMap
  #   - name: Authorization
  #     valueFrom: {type: Secret, name: fleet-mcp-token, key: token}
  # tls: {...}                             # rejected when url is http://
```

### Invoke an agent

```bash
# CLI
kagent invoke --agent fleet-sre --task "Get the pods in the kagent namespace"

# A2A endpoint (controller port 8083)
kubectl port-forward svc/kagent-controller 8083:8083 -n kagent
curl localhost:8083/api/a2a/kagent/fleet-sre/.well-known/agent.json   # agent card
# JSON-RPC message/send goes to http://localhost:8083/api/a2a/{namespace}/{agent-name}
```

Note kagent serves the **legacy card path** `/.well-known/agent.json` (A2A ≤0.2.x
convention), not `agent-card.json` — see §4.

### OTel tracing (feeds agentevals)

```bash
--set otel.tracing.enabled=true \
--set otel.tracing.exporter.otlp.endpoint=<collector-or-agentevals>:4317 \
--set otel.tracing.exporter.otlp.protocol=grpc \
--set otel.tracing.exporter.otlp.insecure=true
```

kagent's OTLP export defaults to **gRPC**; agentevals' receiver is HTTP-first — put an OTel
Collector between them to bridge gRPC→HTTP (this is exactly what
`agentevals/examples/kubernetes/` does).

---

## 3. MCP Python SDK (github.com/modelcontextprotocol/python-sdk)

pip package: **`mcp`** — current version **2.0.0** (PyPI, verified).

> **BIG gotcha:** v2 is a major rework. `FastMCP` is gone — the server class is
> **`mcp.server.MCPServer`**, and `pip install mcp` now gets 2.x. If you find code using
> `from mcp.server.fastmcp import FastMCP`, that's v1 — pin `mcp>=1.28,<2` or migrate.
> Docs: https://py.sdk.modelcontextprotocol.io/ (v1 docs under /v1/).

```bash
pip install "mcp[cli]"     # cli extra adds `mcp dev|run|install`; plain `mcp` for the SDK only
```

### Server (v2, streamable HTTP on a port + path)

```python
# server.py
from mcp.server import MCPServer

mcp = MCPServer("fleet-ops")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    # host default 127.0.0.1, port default 8000, path default /mcp
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, streamable_http_path="/mcp")
```

All transport options go to `run()`, not the `MCPServer()` constructor. CLI equivalent:
`uv run mcp run server.py --transport streamable-http`. For k8s, `host="0.0.0.0"` is
required (default binds loopback only).

ASGI/uvicorn alternative:

```python
app = mcp.streamable_http_app()      # serve with: uvicorn server:app --host 0.0.0.0 --port 8000
# endpoint: http://<host>:8000/mcp
# If mounting inside a larger Starlette/FastAPI app, the host app's lifespan MUST enter
# mcp.session_manager.run() or all requests fail.
```

### Client (async, streamable HTTP)

```python
import asyncio
from mcp import Client

async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:   # URL => streamable HTTP
        result = await client.call_tool("add", {"a": 1, "b": 2})
        print(result.structured_content)  # {'result': 3}

asyncio.run(main())
```

`Client` also accepts a stdio subprocess spec or custom transport. Streamable HTTP here
matches kagent `RemoteMCPServer` `protocol: STREAMABLE_HTTP` — the `spec.url` must include
the `/mcp` path.

---

## 4. A2A (a2a-protocol.org, github.com/a2aproject/a2a-python)

pip package: **`a2a-sdk`** — current version **1.1.2** (PyPI, verified; Python ≥3.10).
Extras: `a2a-sdk[http-server]`, `[fastapi]`, `[grpc]`, `[telemetry]`, `[all]`.

> **Version-drift gotcha:** the SDK/spec are now protocol **1.0** (method `SendMessage`,
> enum roles like `ROLE_USER`, card at `/.well-known/agent-card.json`). kagent 0.9.12 speaks
> the older **0.2.x/0.3 dialect** (method `message/send`, role `"user"`, `kind: "text"`
> parts, card at `/.well-known/agent.json`). Match the dialect to the peer.

### SDK server (1.x, from official helloworld sample)

```python
import uvicorn
from starlette.applications import Starlette
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

skill = AgentSkill(id="echo_bot", name="Echo Bot", description="Echoes requests.",
                   input_modes=["text/plain"], output_modes=["text/plain"], tags=["a2a"])

card = AgentCard(
    name="Hello World Agent", description="Just a hello world agent", version="0.0.1",
    default_input_modes=["text/plain"], default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[AgentInterface(protocol_binding="JSONRPC",
                                         url="http://127.0.0.1:9999", protocol_version="1.0")],
    skills=[skill],
)

handler = DefaultRequestHandler(agent_executor=MyExecutor(),   # subclass a2a.server.agent_execution.AgentExecutor
                                task_store=InMemoryTaskStore(), agent_card=card)

routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
uvicorn.run(Starlette(routes=routes), host="127.0.0.1", port=9999)
```

The executor implements `async def execute(self, context: RequestContext, event_queue: EventQueue)`:
create a task with `new_task_from_user_message(context.message)`, use `TaskUpdater` to move
through `TaskState.TASK_STATE_WORKING` → `add_artifact(parts=[new_text_part(...)])` →
`TASK_STATE_COMPLETED`. Helpers live in `a2a.helpers` (`get_message_text`, `new_text_message`).

### SDK client (1.x)

```python
import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

async with httpx.AsyncClient() as hc:
    card = await A2ACardResolver(httpx_client=hc, base_url="http://127.0.0.1:9999").get_agent_card()

client = await create_client(agent=card, client_config=ClientConfig(streaming=False))
request = SendMessageRequest(message=new_text_message("Hi there", role=Role.ROLE_USER))
async for chunk in client.send_message(request):
    print(chunk)
await client.close()
```

### Hand-rolled minimal surface (recommended for talking to kagent 0.9.12)

The SDK is heavy (Starlette + task machinery). The whole 0.3-dialect surface is two routes:

- **Agent card:** `GET /.well-known/agent.json` (kagent/legacy) — new spec name is
  `/.well-known/agent-card.json`; serve both if you're the server. JSON with `name`,
  `description`, `url`, `version`, `capabilities`, `skills`, `defaultInputModes/OutputModes`.
- **JSON-RPC:** `POST /` (or the card's `url`) — method `message/send`
  (v0.3.0 spec, verbatim):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "tell me a joke"}],
      "messageId": "9229e770-767c-417b-a0b0-f0741243c589"
    },
    "metadata": {}
  }
}
```

Response `result` is either a Message or a Task:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "363422be-b0f9-4692-a24d-278670e7c7f1",
    "contextId": "c295ea44-7543-4f78-b524-7a38915ad6e4",
    "status": {"state": "completed"},
    "artifacts": [{"parts": [{"kind": "text", "text": "..."}]}],
    "kind": "task"
  }
}
```

(Protocol 1.0 renames the method to `SendMessage`, roles to `ROLE_USER`, states to
`TASK_STATE_*`, drops `kind` discriminators, and adds the `A2A-Version` header.)

---

## 5. Ollama in Docker

- Official image: **`ollama/ollama`** (Docker Hub; `:latest` or pinned like `:0.11.x`;
  `ollama/ollama:rocm` for AMD). Serves on **11434**.
- OpenAI-compatible endpoints (verified in ollama docs): base URL
  `http://localhost:11434/v1/` → **`/v1/chat/completions`**, `/v1/completions`,
  `/v1/models`, `/v1/embeddings`, `/v1/responses`. Native API: `/api/chat`, `/api/generate`.

### Pull a model at container start (entrypoint pattern)

The image's entrypoint is `ollama` with default command `serve`; `ollama pull` needs the
server up first, so start serve in the background, pull, then wait:

```yaml
# docker-compose.yml
services:
  ollama:
    image: ollama/ollama
    ports: ["11434:11434"]
    volumes: ["ollama:/root/.ollama"]     # cache models across restarts
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        ollama serve &
        sleep 2
        ollama pull qwen3:4b
        ollama pull qwen2.5:0.5b
        wait
volumes:
  ollama:
```

(Equivalent k8s pattern: default command + a postStart lifecycle hook or an initContainer
sharing the model volume. Set `OLLAMA_HOST=0.0.0.0` if it isn't reachable off-loopback —
the Docker image already sets this.)

### Tool calling: qwen3:4b and qwen2.5:0.5b

Verified capability tags on ollama.com/library:

| Model | Capabilities | Notes |
|---|---|---|
| `qwen3:4b` | **tools**, thinking | Solid tool caller; thinking mode on by default (`/no_think` or `think=false` to disable). Good fleet-sre pick. |
| `qwen2.5:0.5b` | **tools** | Template supports tool calling, but at 0.5B params tool selection/argument quality is unreliable — fine for smoke tests, not for demos that must land. |

---

## Cross-project wiring summary (this demo)

```
kagent Agent (Ollama ModelConfig, qwen3:4b)
  ├─ tools ─► RemoteMCPServer (STREAMABLE_HTTP) ─► Python MCPServer (mcp 2.0, /mcp, port 8000)
  ├─ A2A  ─► kagent-controller :8083 /api/a2a/{ns}/{agent}  (0.3 dialect: message/send)
  └─ OTel tracing (gRPC :4317) ─► OTel Collector ─► agentevals OTLP receiver (:4318 HTTP)
                                                       └─ agentevals run / CI gate (eval sets + custom evaluators)
```

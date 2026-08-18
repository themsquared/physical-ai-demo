# agentgateway v1.4.1 — standalone config reference

Condensed from the official docs at `agentgateway.dev/docs/standalone/latest/` (the "latest" docs ARE the 1.4.x docs — verified against `llms.txt` version index; v1.4.1 is the newest GitHub release) plus the published JSON schema (`https://agentgateway.dev/schema/config`) and the v1.4.1 source tree. All YAML below is quoted verbatim from docs/schema unless marked "derived".

Put this at the top of every config file so editors validate it:

```yaml
# yaml-language-server: $schema=https://agentgateway.dev/schema/config
```

---

## 1. Config file structure

Top-level keys (from the JSON schema): `config`, `gateways`, `routes`, `tcpRoutes`, `routeGroups`, `llm`, `mcp`, `ui`, `binds`, `backends`, `policies`, `frontendPolicies`, `services`, `workloads`.

**IMPORTANT (1.4.x change vs older sketches): `binds` → `listeners` → `routes` is DEPRECATED.** From the overview doc:

> `binds` is the deprecated predecessor to `gateways`, which nests listeners and routes under each port. Use `gateways` and `routes` instead.

`binds` still works in 1.4.1 (it is still in the schema, and several repo examples use it), and `agentgateway migrate -f config.yaml` converts old configs. But new configs should use the flat form: **`gateways` (named map of ports) + top-level `routes` (attach to gateways by name) + `backends` inside each route + `policies` at gateway/route/backend level**.

Minimal config (quoted from overview doc):

```yaml
gateways:
  default:
    port: 3000
routes:
- backends:
  - host: localhost:8000
```

Fuller anatomy (quoted from routes doc):

```yaml
gateways:
  http-proxy:
    port: 8080
    protocol: HTTP
routes:
- name: http-backend
  gateways: [http-proxy]
  hostnames:
  - "example.com"
  matches:
  - path:
      pathPrefix: /
  backends:
  - host: http.example.com:8080
    weight: 1
```

Route fields: `gateways` (defaults to the gateway named `default` when omitted), `name`, `hostnames`, `matches`, `backends`, `policies`.

Backend variants inside `routes[].backends[]` (schema `LocalRouteBackend` oneOf): `host:`, `service:`, `backend:`, `internal:`, `dynamic:`, plus the typed backends `mcp:`, `ai:`, `aws:`. Each backend entry can also carry `weight` and backend-level `policies`.

**Policy attachment levels:**
- **Gateway/listener level** (`gateways.<name>.*`): `jwtAuth`, `authorization`, `cors`, `extAuthz`, `extProc`, `transformations`, `basicAuth`, `oidc`, `tls`, ...
- **Route level** (`routes[].policies`): full set — schema `FilterOrPolicy` keys: `a2a`, `ai`, `apiKey`, `authorization`, `backendAuth`, `backendTLS`, `backendTunnel`, `basicAuth`, `buffer`, `cors`, `csrf`, `delay`, `directResponse`, `extAuthz`, `extProc`, `jwtAuth`, `localRateLimit`, `mcpAuthentication`, `mcpAuthorization`, `mcpGuardrails`, `oidc`, `remoteRateLimit`, `requestHeaderModifier`, `requestMirror`, `requestRedirect`, `responseHeaderModifier`, `retry`, `timeout`, `transformations`, `urlRewrite`.
- **Backend level** (`routes[].backends[].policies`, schema `LocalBackendPolicies`): `a2a`, `ai`, `authorization`, `backendAuth`, `backendTLS`, `backendTunnel`, `extAuthz`, `health`, `http`, `inferenceRouting`, `mcpAuthorization`, `mcpGuardrails`, `requestHeaderModifier`, `requestRedirect`, `responseHeaderModifier`, `sessionAffinity`, `tcp`, `transformations`.
- **`frontendPolicies`** (top-level, applies to ALL traffic): `accessLog`, `logging`, `tracing`, `connect`, `http`, `tcp`, `tls`, `proxy`, `proxyProtocol`, `networkAuthorization`, `networkExtAuthz`.
- **`config`** (static, startup-only): `adminAddr`, `statsAddr`, `readinessAddr`, `logging` (level/format/fields), `tracing` (otlpEndpoint/...), `metrics`, `backend` (connect timeouts/pools), `modelCatalog`, `database`, etc.

There is also a **simplified mode**: top-level `llm:` (models/providers/virtualModels/policies) and `mcp:` (targets/policies) sections that skip routes entirely. Docs use simplified mode for most LLM/MCP examples; both modes can coexist in one file. Simplified sections attach to the gateway named `default` unless you set `llm.gateways`/`mcp.gateways`. **Defaults when no gateway is defined: MCP on port 3000, LLM on port 4000** (`llm.port`/`mcp.port` are deprecated but still work and override this).

---

## 2. LLM route with multi-provider failover + Ollama + retries/timeouts

### Ollama provider (simplified `llm` mode — the first-class way)

Quoted from the Ollama provider doc (Ollama provider is first-class since 1.3; defaults to `http://localhost:11434/v1`):

```yaml
llm:
  port: 3000
  models:
  - name: "*"
    provider: ollama
    params:
      model: llama3.2
      baseUrl: http://192.168.1.20:11434/v1   # optional override; omit for localhost
```

- `params.model`: default Ollama model (must be pulled locally).
- `params.baseUrl`: must include the `/v1` prefix.
- `name: "*"` matches any requested model name.
- `llm.models[].params` full key list (schema `LocalLLMParams`): `apiKey`, `awsRegion`, `azureApiVersion`, `azureProjectName`, `azureResourceName`, `azureResourceType`, `baseUrl`, `hostOverride`, `model`, `pathOverride`, `pathPrefix`, `tokenize`, `vertexProject`, `vertexRegion`.
- Valid `provider:` values in `llm.models[]`: built-ins `openAI`/`openai`, `gemini`, `vertex`, `anthropic`, `bedrock`, `azure`, `copilot`; presets `ollama`, `cohere`, `baseten`, `cerebras`, `deepinfra`, `deepseek`, `groq`, `huggingface`, `mistral`, `openrouter`, `togetherai`, `xai`, `fireworks`; or `{reference: <llm.providers[] name>}` or `{custom: {...}}`.

### Failover chain (simplified mode): `virtualModels` + priority + health.eviction

This is the documented failover mechanism in 1.4.x. Quoted from the Virtual models doc:

```yaml
llm:
  models:
  - name: claude-primary
    visibility: internal
    provider: anthropic
    params:
      model: claude-sonnet-4-0
      apiKey: "$ANTHROPIC_API_KEY"
    health:
      eviction:
        consecutiveFailures: 1
        duration: 60s
  - name: claude-backup-a
    visibility: internal
    provider: anthropic
    params:
      model: claude-3-5-haiku-20241022
      apiKey: "$ANTHROPIC_API_KEY"
    health:
      eviction:
        consecutiveFailures: 1
        duration: 60s

  virtualModels:
  - name: resilient
    routing:
      failover:
        targets:
        - model: claude-primary
          priority: 0
        - model: claude-backup-a
          priority: 1
```

Critical semantics (quoted/paraphrased from the doc):

> Setting `routing.failover` alone does **not** switch to a lower-priority target after errors. You must set `health.eviction` on the primary (and typically backup) concrete models. Without eviction, requests keep hitting the highest-priority group forever.

> Failover is driven by eviction of the active set, not by rewriting a single in-flight request to another target. The request that triggers eviction still fails unless you also configure retries so a later attempt can re-select a provider after eviction.

- Lower `priority` value = preferred. Same priority = one group, load-balanced by health+latency score.
- Traffic moves to the next priority group only after EVERY target in the current group is evicted.
- `health.unhealthyExpression`: optional CEL; default unhealthy = any 5xx / connection failure.
- `eviction.duration` (default 3s, multiplicative backoff), `eviction.consecutiveFailures`, `eviction.healthThreshold`, `eviction.restoreHealth`.
- `visibility: public | internal` on models; virtual model names are what clients request.
- Alternatives: `routing.weighted.targets[{model, weight}]` and `routing.conditional.targets[{model, when: <CEL>}]`.

### Failover in routing-based mode: `ai` backend with `groups`

From the schema (`LocalAIBackend`): an `ai:` backend is EITHER a single named provider `{name, provider, hostOverride, pathOverride, pathPrefix, tokenize, policies}` OR `{groups: [{providers: [<same shape>...]}, ...]}`. Providers within a group are "load balanced together" (schema description); groups are the fallback tiers. Single-provider example quoted from the configuration-modes doc:

```yaml
gateways:
  default:
    port: 3000
    protocol: HTTP
routes:
- backends:
  - ai:
      name: openai
      provider:
        openAI:
          model: gpt-3.5-turbo
  policies:
    backendAuth:
      key: "$OPENAI_API_KEY"
```

Grouped form (derived from schema — not shown assembled in the docs; prefer virtualModels for failover, which is what the docs document):

```yaml
routes:
- backends:
  - ai:
      groups:
      - providers:
        - name: primary
          provider:
            anthropic:
              model: claude-sonnet-4-0
      - providers:
        - name: fallback
          provider:
            openAI:
              model: gpt-4o-mini
```

**Ollama caveat in routing mode:** the routing-based `ai.provider` oneOf is ONLY `openAI | gemini | vertex | anthropic | bedrock | azure | copilot | custom` — there is **no `ollama` variant**. For Ollama behind an `ai:` backend, use `provider: {openAI: {model: llama3.2}}` plus `hostOverride` on the provider entry, or use the simplified `llm` mode (recommended; that's where the `ollama` preset lives). The Docker quickstart does exactly this openAI-compat approach:

```yaml
llm:
  models:
  - name: "*"
    provider: openAI
    params:
      baseUrl: "http://host.docker.internal:11434"
```

### Retries (route-level policy)

Quoted from the retries doc (routing-based tab):

```yaml
gateways:
  default:
    port: 3000
routes:
- policies:
    retry:
      # total number of attempts allowed.
      # Note: 1 attempt implies no retries; the initial attempt is included in the count.
      attempts: 3
      # Optional; if set, a delay between each additional attempt
      backoff: 500ms
      # A list of HTTP response codes to consider retry-able.
      # In addition, retries are always permitted if the request to a backend was never started.
      codes: [429, 500, 503]
  backends:
  - host: localhost:8080
```

- Schema: `codes` is REQUIRED; `attempts` default 1; optional `precondition` and `condition` CEL expressions.
- "When a retry is attempted, a different backend will be preferred (if possible)." Body is buffered; oversized bodies disable retries.
- The same `retry` block also works under `mcp.policies` / (llm mode lacks `retry` in `llm.policies` — attach retries on a route for routing-based LLM traffic; for virtualModels failover, retries + eviction combine as described above).

### Timeouts (route-level policy)

Schema `TimeoutPolicy` (both fields duration strings):

```yaml
routes:
- policies:
    timeout:
      requestTimeout: 60s         # full downstream request+response
      backendRequestTimeout: 30s  # per upstream backend request
```

---

## 3. MCP backend + JWT auth + mcpAuthorization

### MCP backend (routing-based, quoted from mcp-authz doc)

```yaml
gateways:
  default:
    port: 3000
routes:
- policies:
    mcpAuthorization:
      rules:
      # Allow anyone to call 'echo'
      - 'mcp.tool.name == "echo"'
      # Only the test-user can call 'add'
      - 'jwt.sub == "test-user" && mcp.tool.name == "add"'
      # Any authenticated user with the claim `nested.key == value` can access 'printEnv'
      - 'mcp.tool.name == "printEnv" && jwt.nested.key == "value"'
  backends:
  - mcp:
      targets:
      - name: everything
        stdio:
          cmd: npx
          args: ["@modelcontextprotocol/server-everything"]
```

MCP target types (schema `LocalMcpTarget` oneOf): `stdio: {cmd, args, env, clear_env}`, `mcp: {host}` (streamable HTTP; or `{host, port, path}`), `sse: {host...}`, `openapi: {host, schema: {url|file}}`. MCP backend options: `statefulMode: stateless|stateful`, `prefixMode`, `failureMode`, `dnsRebindingProtection`.

### JWT authentication policy (quoted from jwt-authn doc)

Attaches to Listener/Gateway or Route (and `llm.policies`/`mcp.policies` in simplified mode):

```yaml
gateways:
  default:
    port: 3000
    jwtAuth:
      mode: strict
      issuer: agentgateway.dev
      audiences: [test.agentgateway.dev]
      jwks:
        # Relative to the folder the binary runs from, not the config file
        file: ./manifests/jwt/pub-key
routes:
- policies:
    mcpAuthorization:
      rules:
      - 'jwt.sub == "test-user" && mcp.tool.name == "add"'
  backends:
  - mcp:
      targets: [...]
```

- `mode`: `strict` (valid token required) | `optional` (**the default** — validates a token if present but allows requests without one!) | `permissive` (never rejects).
- `jwks`: `file:` | `url:` | inline (schema `FileInlineOrRemote`).
- Multi-issuer form exists: `jwtAuth: {mode, location, providers: [{issuer, audiences, jwks, jwtValidationOptions}, ...]}`.
- For MCP-spec OAuth flows there is also `mcpAuthentication` (issuer, audiences, jwks, `resourceMetadata: {resource, scopesSupported, bearerMethodsSupported}`) which serves `/.well-known/oauth-protected-resource` metadata; JWT claims from it feed the same `jwt.*` CEL variables.

### mcpAuthorization rule format — PRD sketch is CORRECT

Schema: `mcpAuthorization: {rules: [<rule>...]}` where each rule (`RuleSerde`) is **either a bare CEL string** (treated as allow) **or** an object `{allow: '<cel>'}` / `{deny: '<cel>'}` / `{require: '<cel>'}`. The docs use bare strings throughout. The schema warns against `deny` ("expression failures fail to deny; prefer Allow or Require").

**Authorization DOES filter list output** — quoted from the mcp-authz doc:

> If a tool or other resource is not allowed, the gateway automatically filters it from the `list` response, so unauthorized clients never see it.

**Exact CEL variables for mcpAuthorization rules** (quoted table from the doc):

| Variable | Type | Availability |
| --- | --- | --- |
| `mcp.tool.name` | string | Request-time |
| `mcp.tool.target` | string | Request-time |
| `mcp.prompt.name` | string | Request-time |
| `mcp.resource.name` | string | Request-time |
| `mcp.tool.arguments` | map | Post-request (access logs ONLY — **cannot** be used in authz rules) |
| `mcp.tool.result` / `mcp.tool.error` | any | Post-request (access logs only) |
| `mcp.methodName` | string | Post-request (e.g. `tools/call`) |
| `mcp.sessionId` | string | Post-request |
| `jwt.sub` | string | Request-time |
| `jwt.<claim>` | any | Request-time (e.g. `jwt.roles`, `jwt.nested.key`) |
| `has(jwt.<claim>)` | bool | presence check (since 1.x, missing JWT ⇒ `has()` is false; unguarded access errors) |

Example rule combining them: `'mcp.tool.target == "admin-tools" && has(jwt.sub) && "admin" in jwt.roles'`.

---

## 4. A2A

A2A is a **route policy marker** (`a2a: {}` — schema `A2aPolicy` is an empty object) on a route pointing at a plain host backend. Agentgateway then understands the A2A protocol (rewrites the agent-card `url`, logs `a2a.method`, etc.). Quoted from the a2a doc (note: this doc still uses the deprecated `binds` form):

```yaml
config:
  logging:
    format: json
frontendPolicies:
  accessLog:
    add:
      backend: backend
binds:
- port: 3000
  listeners:
  - routes:
    - policies:
        cors:
          allowOrigins:
          - '*'
          allowHeaders:
          - content-type
          - cache-control
        # Mark this route as a2a traffic
        a2a: {}
      backends:
      - host: localhost:9999
```

Equivalent modern form (derived — same keys, `gateways` style):

```yaml
gateways:
  default:
    port: 3000
routes:
- policies:
    a2a: {}
    cors:
      allowOrigins: ["*"]
      allowHeaders: [content-type, cache-control]
  backends:
  - host: localhost:9999
```

Verify with `curl localhost:3000/.well-known/agent.json`. Request logs gain `a2a.method=message/stream`-style fields.

---

## 5. Access logging (JSON + custom CEL fields)

Two cooperating pieces:

**Static `config.logging`** — level/format (startup-only section):

```yaml
config:
  logging:
    format: json          # text | json
    level: info           # or "info,agent_core=trace"
    filter: '<CEL: which requests are logged>'
    fields:
      remove: [<field names>]
      add:
        <field>: '<CEL expression>'
```

**Dynamic `frontendPolicies.accessLog`** (schema `LoggingPolicy`: `filter`, `add`, `remove`, `otlp`, `database`). Quoted from the MCP observability doc:

```yaml
frontendPolicies:
  accessLog:
    filter: 'mcp.methodName == "tools/call"'
    add:
      tool_args: 'mcp.tool.arguments'
      tool_result: 'mcp.tool.result'
      tool_error: 'mcp.tool.error'
```

(`frontendPolicies.logging` is an alias with the same shape; `accessLog` is what the examples use.)

**MCP fields emitted by default in structured logs:** `mcp.method.name`, `mcp.session.id`, `mcp.target`, `mcp.resource.type`, `mcp.resource.uri`, `gen_ai.tool.name`.
**MCP CEL variables available for `add:` but not default:** `mcp.methodName`, `mcp.sessionId`, `mcp.tool.name`, `mcp.tool.target`, `mcp.tool.arguments`, `mcp.tool.result`, `mcp.tool.error`.

**LLM fields emitted by default** (example log line from the LLM observability doc): `protocol=llm gen_ai.operation.name=chat gen_ai.provider.name=openai gen_ai.request.model=gpt-4o gen_ai.response.model=gpt-4o-2024-08-06 gen_ai.usage.input_tokens=68 gen_ai.usage.output_tokens=298 duration=2488ms`.

**LLM CEL context for custom `add:` fields** (`llm.` object, from the CEL reference): `llm.provider`, `llm.requestModel`, `llm.responseModel`, `llm.inputTokens`, `llm.outputTokens`, `llm.totalTokens`, `llm.cachedInputTokens`, `llm.cacheCreationInputTokens`, `llm.reasoningTokens`, `llm.prompt` (array, perf warning), `llm.completion` (array, perf warning), `llm.serviceTier`, `llm.timePerOutputToken`, plus `llm.cost`/`llm.costRates` when a `config.modelCatalog` is configured.

Logging-context CEL top-level variables: `request`, `response`, `env`, `jwt`, `apiKey`, `basicAuth`, `llm`, `source`, `mcp`, `backend`, `extauthz`, `extproc`, `metadata`. Handy functions: `flatten(request.headers)`, `json(...)`, `default(expr, fallback)`, `has(...)`.

---

## 6. OTel tracing + Prometheus metrics

### Tracing — two equivalent config points

Static (startup, quoted from LLM/MCP observability docs — used in most examples):

```yaml
config:
  tracing:
    otlpEndpoint: http://localhost:4317
    randomSampling: true      # or a 0.0-1.0 ratio / CEL; default false
    # otlpProtocol: grpc | http    (default grpc)
    # path: /v1/traces
    # headers: {<name>: <value>}   # e.g. auth headers for the collector
    # clientSampling: true         # default true (honor incoming trace context)
    # fields: {add: {<attr>: '<CEL>'}, remove: [...]}
```

Dynamic frontend policy (quoted from the OpenTelemetry doc):

```yaml
frontendPolicies:
  tracing:
    host: localhost:4317
    randomSampling: true      # or "0.1" for 10%
```

Schema for `frontendPolicies.tracing` (`TracingConfig`): target as `host:` | `service:` | `backend:` (oneOf), plus `protocol` (grpc|http, default grpc), `path` (default `/v1/traces`), `randomSampling`, `clientSampling`, `filter` (CEL keep-semantics), `attributes:` (map name → CEL), `resources:` (OTel Resource attrs, e.g. `service.name`), `remove: [...]`, `policies` (backendAuth/backendTLS to the collector).

Trace attributes include: `gateway`, `listener`, `route`, `endpoint`, `src.addr`, `http.method/host/path/status/version`, `trace.id`, `span.id`, `protocol`, `duration`, plus `mcp.method.name`/`mcp.session.id` and `gen_ai.operation.name`/`gen_ai.request.model` etc.

### Prometheus metrics

- **Metrics endpoint: `:15020/metrics`** (default `statsAddr`, binds wildcard; override with `config.statsAddr` or `STATS_ADDR` env).
- **Admin UI: `:15000/ui/`** (localhost-only by default; override `config.adminAddr` or `ADMIN_ADDR=0.0.0.0:15000` env).
- **Readiness probe: `:15021`** (`config.readinessAddr` / `READINESS_ADDR`). (Ports verified in v1.4.1 source `crates/agentgateway/src/config.rs`.)

Key metric names:
- `agentgateway_requests_total{gateway, listener, route, route_rule, backend, method, status}` — HTTP requests (verified sample output in metrics reference doc).
- `agentgateway_gen_ai_client_token_usage` — histogram with labels `gen_ai_token_type` (`input`|`output`), `gen_ai_operation_name`, `gen_ai_system`, `gen_ai_request_model`, `gen_ai_response_model` (the documented LLM token metric).
- `mcp_requests_total{server, method, resource, resource_type}` — MCP requests (filter `method="tools/call"` for tool calls); also `tool_calls`/`tool_call_errors`/`list_calls`/`read_resource_calls`/`get_prompt_calls` counters.
- `agentgateway_cost_catalog_lookups_total{status, ...}` when a model catalog is set.
- CAVEAT: the Prometheus integration page also lists `agentgateway_llm_requests_total`, `agentgateway_llm_tokens_total`, `agentgateway_request_duration_seconds`, etc. Those names do NOT match the sample output on the metrics reference page or the LLM observability page; treat `agentgateway_requests_total`, `agentgateway_gen_ai_client_token_usage`, and `mcp_requests_total` as the reliable ones and confirm against a live `:15020/metrics` scrape.

Scrape config (quoted):

```yaml
scrape_configs:
  - job_name: 'agentgateway'
    static_configs:
      - targets: ['localhost:15020']
    scrape_interval: 15s
```

Custom metric labels: `config.metrics: {remove: [...], fields: {add: {<label>: '<CEL>'}}}`.

---

## 7. Rate limiting

### Local (in-memory token bucket; per-replica, no CEL keying)

Schema `localRateLimit` is a LIST of `RateLimitSpec`: `maxTokens`, `tokensPerFill`, `fillInterval` (required), `type: requests|tokens` (default `requests`). Quoted (routing-based tab) — 5,000 LLM tokens/hour AND 60 req/s on one route:

```yaml
gateways:
  default:
    port: 3000
routes:
- policies:
    localRateLimit:
    - maxTokens: 5000
      # Every hour, refill 5000 tokens
      tokensPerFill: 5000
      fillInterval: 1h
      type: tokens
    - maxTokens: 60
      # Every second, refill 1 token
      tokensPerFill: 1
      fillInterval: 1s
      type: requests
  backends:
  - host: localhost:8080
```

Same block works under `llm.policies.localRateLimit` and `mcp.policies.localRateLimit`.

Token-mode behavior: without `tokenize: true` on the AI backend/provider, request-time cost is unknown so requests are admitted and the bucket is debited from the provider's usage numbers on response (subsequent requests get limited). With `tokenize: true` (a `llm.models[].params.tokenize` / `ai` provider field — "expensive operation"), input tokens are estimated at request time and over-limit requests are rejected up front, then reconciled against actual usage.

**Local rate limits have NO per-identity key field** — counters are per-route-policy. Per-identity/per-key limiting requires the remote rate limit.

### Remote (Envoy RLS gRPC; CEL-keyed descriptors)

Quoted (routing-based tab):

```yaml
routes:
- policies:
    remoteRateLimit:
      # The address to access the rate limit server
      host: localhost:8081
      # Arbitrary 'domain' to match limits on the rate limit server
      domain: example.com
      descriptors:
      - entries:
        - key: some-static-value
          value: '"something"'
        - key: organization
          value: 'request.headers["x-organization"]'
        - key: authenticated
          value: 'has(jwt.sub)'
        type: tokens # or 'requests'
  backends:
  - host: localhost:8080
```

- Each `value` is a CEL expression — so per-identity keying is e.g. `value: 'jwt.sub'`.
- `failureMode: failClosed` (default — deny with 500 when RLS is down) | `failOpen`.
- Optional `policies:` on `remoteRateLimit` for `backendAuth`/`backendTLS`/`tcp.connectTimeout` to the RLS server.
- Works against `envoyproxy/ratelimit` (Redis-backed); limits are defined server-side by `domain` + descriptor keys.
- Conditional variants exist (`conditional` field) for different limits per request.

---

## 8. Running the container

**Image: `ghcr.io/agentgateway/agentgateway:v1.4.1` — verified to exist (ghcr manifest returns HTTP 200).** Note the official docs consistently use the vanity registry **`cr.agentgateway.dev/agentgateway:v1.4.1`** (same image). Tag has the `v` prefix on both.

Quoted docker run (Ollama-on-host variant from the Docker doc):

```bash
docker run -v "$PWD/config.yaml:/config.yaml" -p 3000:3000 \
  --add-host=host.docker.internal:host-gateway \
  cr.agentgateway.dev/agentgateway:v1.4.1 -f /config.yaml
```

Admin UI from the host (UI is localhost-bound inside the container by default):

```bash
docker run -v "$PWD/config.yaml:/config.yaml" -p 3000:3000 \
  -p 127.0.0.1:15000:15000 -e ADMIN_ADDR=0.0.0.0:15000 \
  cr.agentgateway.dev/agentgateway:v1.4.1 -f /config.yaml
# then open http://localhost:15000/ui/
```

Docker Compose (quoted):

```yaml
services:
  agentgateway:
    container_name: agentgateway
    restart: unless-stopped
    image: cr.agentgateway.dev/agentgateway:v1.4.1
    ports:
      - "3000:3000"
      - "127.0.0.1:15000:15000"
    volumes:
      - ./config.yaml:/config.yaml
    environment:
      - ADMIN_ADDR=0.0.0.0:15000
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    command: ["-f", "/config.yaml"]
```

**CLI flags (verified in v1.4.1 source, `crates/agentgateway-app/src/lib.rs`):**
- `-f, --file <file>` — config file (YAML or JSON)
- `-c, --config <config>` — config from an inline string
- `--validate-only` — **yes, a validation flag exists**: parse/validate the config and exit
- `-V` / `--version` — version (string / JSON)
- Subcommands: `import --from <source> -f <file> [-o <file>]` (convert another gateway's config), `migrate -f <file>` (rewrite deprecated fields, e.g. `binds` → `gateways`), `oneshot` (Linux only).
- Config hot-reloads on file change except the `config:` section. Env vars: `ADMIN_ADDR`, `STATS_ADDR`, `READINESS_ADDR`. `$VARS` in config values (e.g. `apiKey: "$OPENAI_API_KEY"`) resolve from the environment — pass them with `-e` in Docker.
- Remember: for metrics scraping from outside the container also publish `-p 15020:15020`.

---

## Differences from the PRD sketch (summary)

1. **`mcpAuthorization.rules` with bare CEL strings — the PRD guess is VALID.** Schema accepts plain strings (allow semantics) or `{allow|deny|require: '<cel>'}` objects. Docs use bare strings.
2. **`binds:` is deprecated in 1.4.x.** Use `gateways:` (named map with `port`) + top-level `routes:`. `binds` still parses, and some docs/examples (a2a, telemetry, ratelimit examples) still show it.
3. **LLM failover is NOT "priority groups on the ai backend" in the docs.** The documented mechanism is simplified-mode `llm.virtualModels[].routing.failover.targets[{model, priority}]` **plus mandatory `health.eviction` on each concrete model** — without eviction there is no cross-priority failover, and the triggering request still fails unless a `retry` policy is present. (Routing mode's `ai.groups` exists in the schema as fallback tiers but is undocumented.)
4. **Ollama**: first-class `provider: ollama` exists only in simplified `llm.models[]`; params are `model` + `baseUrl` (default `http://localhost:11434/v1`) — there is no separate host/port pair. The routing-based `ai:` backend has no ollama variant (use openAI-compat + baseUrl/hostOverride).
5. **jwtAuth default mode is `optional`** — requests without a token pass. Set `mode: strict` explicitly.
6. **Rate limiting**: `localRateLimit` is a list, has no CEL/identity key; per-identity limits require `remoteRateLimit` (Envoy RLS) with CEL descriptor values. Token limits use `type: tokens` (+ optional `tokenize: true` on the provider for request-time enforcement).
7. **Metric names**: trust `agentgateway_requests_total`, `agentgateway_gen_ai_client_token_usage`, `mcp_requests_total`; the Prometheus page's `agentgateway_llm_*` names look stale.
8. **Ports**: admin UI 15000 (localhost-only unless `ADMIN_ADDR` overridden), metrics 15020, readiness 15021; simplified-mode defaults LLM 4000 / MCP 3000 when no gateway is declared.
9. **`--validate-only` exists** (plus a `migrate` subcommand for upgrading deprecated configs).

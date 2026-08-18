"""fleet-mcp: k8s ops tools for the kagent fleet-sre agent.

Agents operating the infrastructure that runs the robots (the Ops tier of the
PRD). Read-mostly diagnosis plus a narrow, auditable set of remediations, all
scoped to the warehouse namespace by the in-cluster ServiceАccount's RBAC —
the fleet-sre can only touch what its Role allows, the same deny-by-default
posture as the robot gateway.
"""

import os

from kubernetes import client, config
from mcp.server.fastmcp import FastMCP

NAMESPACE = os.environ.get("FLEET_NAMESPACE", "warehouse")
PORT = int(os.environ.get("PORT", "8000"))

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

apps = client.AppsV1Api()
core = client.CoreV1Api()

mcp = FastMCP(
    name="fleet-mcp", host="0.0.0.0", port=PORT, streamable_http_path="/mcp", stateless_http=True
)


@mcp.tool()
def list_robot_pods() -> str:
    """List all robot/agent pods in the warehouse namespace with their phase,
    restart count, and readiness — the first thing to check when the fleet is unhealthy."""
    pods = core.list_namespaced_pod(NAMESPACE).items
    lines = []
    for p in pods:
        cs = (p.status.container_statuses or [{}])[0] if p.status.container_statuses else None
        restarts = cs.restart_count if cs else 0
        ready = cs.ready if cs else False
        reason = ""
        if cs and cs.state and cs.state.waiting:
            reason = cs.state.waiting.reason or ""
        lines.append(
            f"{p.metadata.name}: phase={p.status.phase} ready={ready} "
            f"restarts={restarts} {reason}".strip()
        )
    return "\n".join(lines) or "(no pods)"


@mcp.tool()
def get_pod_logs(pod_name: str, tail: int = 50) -> str:
    """Fetch the last N log lines from a pod (use to find the crash cause)."""
    try:
        return core.read_namespaced_pod_log(pod_name, NAMESPACE, tail_lines=tail) or "(no logs)"
    except client.ApiException as e:
        return f"error reading logs: {e.reason}"


@mcp.tool()
def get_pod_events(pod_name: str) -> str:
    """Recent k8s events for a pod (CrashLoopBackOff, OOMKilled, image pull errors)."""
    field = f"involvedObject.name={pod_name}"
    events = core.list_namespaced_event(NAMESPACE, field_selector=field).items
    return (
        "\n".join(f"{e.last_timestamp} {e.type}/{e.reason}: {e.message}" for e in events)
        or "(no events)"
    )


@mcp.tool()
def restart_deployment(deployment_name: str) -> str:
    """Roll-restart a deployment to recover it (the standard remediation for a
    crashlooping or wedged robot component). Auditable and reversible."""
    import datetime

    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kagent.dev/restartedAt": datetime.datetime.utcnow().isoformat()
                    }
                }
            }
        }
    }
    try:
        apps.patch_namespaced_deployment(deployment_name, NAMESPACE, patch)
        return f"restarted deployment {deployment_name} in {NAMESPACE}"
    except client.ApiException as e:
        return f"error restarting {deployment_name}: {e.reason}"


@mcp.tool()
def get_deployment_status(deployment_name: str) -> str:
    """Replica readiness for a deployment (confirm a remediation worked)."""
    try:
        d = apps.read_namespaced_deployment(deployment_name, NAMESPACE)
        s = d.status
        return (
            f"{deployment_name}: desired={s.replicas or 0} ready={s.ready_replicas or 0} "
            f"available={s.available_replicas or 0} updated={s.updated_replicas or 0}"
        )
    except client.ApiException as e:
        return f"error: {e.reason}"


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "namespace": NAMESPACE})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

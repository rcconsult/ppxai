"""
Container management tools for Docker, Podman, and Kubernetes.

Provides read-only inspection and management operations with consent
for destructive actions.

v1.13.8: Initial implementation
"""

import shutil
import subprocess
import asyncio
from typing import TYPE_CHECKING, Optional, List, Dict, Any

from ..base import BaseTool

if TYPE_CHECKING:
    from ...client import EngineClient
    from ..manager import ToolManager


# =============================================================================
# Runtime Detection
# =============================================================================

def detect_container_runtime() -> Optional[str]:
    """
    Detect available container runtime.

    Returns:
        'docker', 'podman', or None if neither is available
    """
    if shutil.which('docker'):
        return 'docker'
    if shutil.which('podman'):
        return 'podman'
    return None


def detect_kubernetes_cli() -> bool:
    """Check if kubectl is available."""
    return shutil.which('kubectl') is not None


def _run_command(
    cmd: List[str],
    timeout: int = 30,
    max_output: int = 10000,
) -> str:
    """
    Run a command and return output.

    Args:
        cmd: Command and arguments
        timeout: Timeout in seconds
        max_output: Maximum output characters

    Returns:
        Command output or error message
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        if len(output) > max_output:
            output = output[:max_output] + "\n... (output truncated)"
        return output.strip() or "Command completed (no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except FileNotFoundError:
        return f"Error: Command not found: {cmd[0]}"
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Docker/Podman Tools
# =============================================================================

class ContainerListTool(BaseTool):
    """List containers."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "container_list"
        self.description = (
            "List Docker/Podman containers. Shows container ID, name, image, and status. "
            "Use 'all=true' to include stopped containers."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "all": {
                    "type": "boolean",
                    "description": "Include stopped containers (default: running only)"
                },
                "filter": {
                    "type": "string",
                    "description": "Filter by name or status (e.g., 'name=web', 'status=running')"
                }
            },
            "required": []
        }

    async def execute(self, all: bool = False, filter: str = None, **kwargs) -> str:
        runtime = detect_container_runtime()
        if not runtime:
            return "Error: No container runtime found. Install Docker or Podman."

        cmd = [
            runtime, 'ps',
            '--format', 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
        ]
        if all:
            cmd.insert(2, '-a')
        if filter:
            cmd.extend(['--filter', filter])

        return _run_command(cmd)


class ContainerLogsTool(BaseTool):
    """Get container logs."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "container_logs"
        self.description = (
            "Get logs from a Docker/Podman container. "
            "Specify container name or ID."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID"
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of lines from end (default: 100)"
                },
                "since": {
                    "type": "string",
                    "description": "Show logs since timestamp (e.g., '10m', '1h', '2023-01-01')"
                }
            },
            "required": ["container"]
        }

    async def execute(
        self,
        container: str,
        tail: int = 100,
        since: str = None,
        **kwargs
    ) -> str:
        runtime = detect_container_runtime()
        if not runtime:
            return "Error: No container runtime found."

        cmd = [runtime, 'logs', '--tail', str(tail)]
        if since:
            cmd.extend(['--since', since])
        cmd.append(container)

        return _run_command(cmd, timeout=30)


class ContainerInspectTool(BaseTool):
    """Inspect container details."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "container_inspect"
        self.description = (
            "Get detailed information about a container including "
            "configuration, network settings, and mounts."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID"
                },
                "format": {
                    "type": "string",
                    "description": "Go template format (e.g., '{{.NetworkSettings.IPAddress}}')"
                }
            },
            "required": ["container"]
        }

    async def execute(self, container: str, format: str = None, **kwargs) -> str:
        runtime = detect_container_runtime()
        if not runtime:
            return "Error: No container runtime found."

        cmd = [runtime, 'inspect']
        if format:
            cmd.extend(['--format', format])
        cmd.append(container)

        return _run_command(cmd)


class ContainerStartStopTool(BaseTool):
    """Start, stop, or restart a container (requires consent)."""

    def __init__(self, engine: 'EngineClient', action: str):
        self.engine = engine
        self.action = action  # 'start', 'stop', 'restart'
        self.name = f"container_{action}"
        self.description = f"{action.title()} a Docker/Podman container."
        self.parameters = {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID"
                }
            },
            "required": ["container"]
        }

    async def execute(self, container: str, **kwargs) -> str:
        runtime = detect_container_runtime()
        if not runtime:
            return "Error: No container runtime found."

        # Request consent for state-changing operation
        cmd_str = f"{runtime} {self.action} {container}"
        working_dir = self.engine.get_working_dir() or "."

        consent = await self.engine.request_shell_consent(cmd_str, working_dir)
        if not consent:
            return f"Error: User denied permission to {self.action} container '{container}'"

        return _run_command([runtime, self.action, container], timeout=60)


class ContainerExecTool(BaseTool):
    """Execute command in a running container (requires consent)."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "container_exec"
        self.description = (
            "Execute a command inside a running container. "
            "Requires user consent for security."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID"
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute (e.g., 'ls -la', 'cat /etc/hosts')"
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory inside container"
                }
            },
            "required": ["container", "command"]
        }

    async def execute(
        self,
        container: str,
        command: str,
        workdir: str = None,
        **kwargs
    ) -> str:
        runtime = detect_container_runtime()
        if not runtime:
            return "Error: No container runtime found."

        # Request consent
        cmd_str = f"{runtime} exec {container} {command}"
        working_dir = self.engine.get_working_dir() or "."

        consent = await self.engine.request_shell_consent(cmd_str, working_dir)
        if not consent:
            return "Error: User denied permission to execute command in container"

        cmd = [runtime, 'exec']
        if workdir:
            cmd.extend(['-w', workdir])
        cmd.append(container)
        cmd.extend(command.split())

        return _run_command(cmd, timeout=30)


class ImageListTool(BaseTool):
    """List container images."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "image_list"
        self.description = "List Docker/Podman images."
        self.parameters = {
            "type": "object",
            "properties": {
                "all": {
                    "type": "boolean",
                    "description": "Show all images including intermediate"
                },
                "filter": {
                    "type": "string",
                    "description": "Filter by reference (e.g., 'reference=nginx*')"
                }
            },
            "required": []
        }

    async def execute(self, all: bool = False, filter: str = None, **kwargs) -> str:
        runtime = detect_container_runtime()
        if not runtime:
            return "Error: No container runtime found."

        cmd = [
            runtime, 'images',
            '--format', 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}'
        ]
        if all:
            cmd.insert(2, '-a')
        if filter:
            cmd.extend(['--filter', filter])

        return _run_command(cmd)


# =============================================================================
# Kubernetes Tools
# =============================================================================

class KubePodListTool(BaseTool):
    """List Kubernetes pods."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "pod_list"
        self.description = (
            "List Kubernetes pods. Can filter by namespace or show all namespaces."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace (default: current context namespace)"
                },
                "all_namespaces": {
                    "type": "boolean",
                    "description": "List pods across all namespaces"
                },
                "selector": {
                    "type": "string",
                    "description": "Label selector (e.g., 'app=nginx')"
                }
            },
            "required": []
        }

    async def execute(
        self,
        namespace: str = None,
        all_namespaces: bool = False,
        selector: str = None,
        **kwargs
    ) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found. Install Kubernetes CLI."

        cmd = ['kubectl', 'get', 'pods', '-o', 'wide']
        if all_namespaces:
            cmd.append('-A')
        elif namespace:
            cmd.extend(['-n', namespace])
        if selector:
            cmd.extend(['-l', selector])

        return _run_command(cmd)


class KubePodLogsTool(BaseTool):
    """Get pod logs."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "pod_logs"
        self.description = (
            "Get logs from a Kubernetes pod. "
            "Specify container for multi-container pods."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "pod": {
                    "type": "string",
                    "description": "Pod name"
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace (default: current)"
                },
                "container": {
                    "type": "string",
                    "description": "Container name (for multi-container pods)"
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of lines from end (default: 100)"
                },
                "previous": {
                    "type": "boolean",
                    "description": "Get logs from previous container instance"
                }
            },
            "required": ["pod"]
        }

    async def execute(
        self,
        pod: str,
        namespace: str = None,
        container: str = None,
        tail: int = 100,
        previous: bool = False,
        **kwargs
    ) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        cmd = ['kubectl', 'logs', pod, '--tail', str(tail)]
        if namespace:
            cmd.extend(['-n', namespace])
        if container:
            cmd.extend(['-c', container])
        if previous:
            cmd.append('--previous')

        return _run_command(cmd, timeout=30)


class KubePodDescribeTool(BaseTool):
    """Describe a pod."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "pod_describe"
        self.description = (
            "Get detailed information about a Kubernetes pod including "
            "events, conditions, and container statuses."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "pod": {
                    "type": "string",
                    "description": "Pod name"
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace (default: current)"
                }
            },
            "required": ["pod"]
        }

    async def execute(self, pod: str, namespace: str = None, **kwargs) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        cmd = ['kubectl', 'describe', 'pod', pod]
        if namespace:
            cmd.extend(['-n', namespace])

        return _run_command(cmd)


class KubeDeploymentListTool(BaseTool):
    """List deployments."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "deployment_list"
        self.description = "List Kubernetes deployments."
        self.parameters = {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace"
                },
                "all_namespaces": {
                    "type": "boolean",
                    "description": "List across all namespaces"
                }
            },
            "required": []
        }

    async def execute(
        self,
        namespace: str = None,
        all_namespaces: bool = False,
        **kwargs
    ) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        cmd = ['kubectl', 'get', 'deployments', '-o', 'wide']
        if all_namespaces:
            cmd.append('-A')
        elif namespace:
            cmd.extend(['-n', namespace])

        return _run_command(cmd)


class KubeServiceListTool(BaseTool):
    """List services."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "service_list"
        self.description = "List Kubernetes services."
        self.parameters = {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace"
                },
                "all_namespaces": {
                    "type": "boolean",
                    "description": "List across all namespaces"
                }
            },
            "required": []
        }

    async def execute(
        self,
        namespace: str = None,
        all_namespaces: bool = False,
        **kwargs
    ) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        cmd = ['kubectl', 'get', 'services', '-o', 'wide']
        if all_namespaces:
            cmd.append('-A')
        elif namespace:
            cmd.extend(['-n', namespace])

        return _run_command(cmd)


class KubeApplyTool(BaseTool):
    """Apply Kubernetes manifest (requires consent)."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "kubectl_apply"
        self.description = (
            "Apply a Kubernetes manifest file. "
            "Requires user consent."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Path to YAML/JSON manifest file"
                },
                "namespace": {
                    "type": "string",
                    "description": "Target namespace"
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Perform dry-run only (no actual changes)"
                }
            },
            "required": ["file"]
        }

    async def execute(
        self,
        file: str,
        namespace: str = None,
        dry_run: bool = False,
        **kwargs
    ) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        # Request consent (even for dry-run, to be safe)
        cmd_str = f"kubectl apply -f {file}"
        if namespace:
            cmd_str += f" -n {namespace}"
        if dry_run:
            cmd_str += " --dry-run=client"

        working_dir = self.engine.get_working_dir() or "."
        consent = await self.engine.request_shell_consent(cmd_str, working_dir)
        if not consent:
            return "Error: User denied permission to apply Kubernetes manifest"

        cmd = ['kubectl', 'apply', '-f', file]
        if namespace:
            cmd.extend(['-n', namespace])
        if dry_run:
            cmd.append('--dry-run=client')

        return _run_command(cmd, timeout=60)


class KubePodExecTool(BaseTool):
    """Execute command in a pod (requires consent)."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "pod_exec"
        self.description = (
            "Execute a command inside a Kubernetes pod. "
            "Requires user consent."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "pod": {
                    "type": "string",
                    "description": "Pod name"
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute"
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace"
                },
                "container": {
                    "type": "string",
                    "description": "Container name (for multi-container pods)"
                }
            },
            "required": ["pod", "command"]
        }

    async def execute(
        self,
        pod: str,
        command: str,
        namespace: str = None,
        container: str = None,
        **kwargs
    ) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        # Request consent
        cmd_str = f"kubectl exec {pod} -- {command}"
        working_dir = self.engine.get_working_dir() or "."

        consent = await self.engine.request_shell_consent(cmd_str, working_dir)
        if not consent:
            return "Error: User denied permission to execute command in pod"

        cmd = ['kubectl', 'exec', pod]
        if namespace:
            cmd.extend(['-n', namespace])
        if container:
            cmd.extend(['-c', container])
        cmd.append('--')
        cmd.extend(command.split())

        return _run_command(cmd, timeout=30)


class KubeNamespaceListTool(BaseTool):
    """List namespaces."""

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "namespace_list"
        self.description = "List Kubernetes namespaces."
        self.parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }

    async def execute(self, **kwargs) -> str:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found."

        return _run_command(['kubectl', 'get', 'namespaces'])


# =============================================================================
# Registration
# =============================================================================

def register_tools(manager: 'ToolManager', engine: 'EngineClient') -> None:
    """
    Register container tools with the manager.

    Only registers tools for available container runtimes.

    Args:
        manager: Tool manager instance
        engine: Engine client for consent requests
    """
    has_docker_podman = detect_container_runtime() is not None
    has_kubectl = detect_kubernetes_cli()

    if not has_docker_podman and not has_kubectl:
        # No container tools available - skip registration
        return

    # Docker/Podman tools
    if has_docker_podman:
        manager.register_tool(ContainerListTool(engine))
        manager.register_tool(ContainerLogsTool(engine))
        manager.register_tool(ContainerInspectTool(engine))
        manager.register_tool(ContainerStartStopTool(engine, 'start'))
        manager.register_tool(ContainerStartStopTool(engine, 'stop'))
        manager.register_tool(ContainerStartStopTool(engine, 'restart'))
        manager.register_tool(ContainerExecTool(engine))
        manager.register_tool(ImageListTool(engine))

    # Kubernetes tools
    if has_kubectl:
        manager.register_tool(KubePodListTool(engine))
        manager.register_tool(KubePodLogsTool(engine))
        manager.register_tool(KubePodDescribeTool(engine))
        manager.register_tool(KubeDeploymentListTool(engine))
        manager.register_tool(KubeServiceListTool(engine))
        manager.register_tool(KubeApplyTool(engine))
        manager.register_tool(KubePodExecTool(engine))
        manager.register_tool(KubeNamespaceListTool(engine))

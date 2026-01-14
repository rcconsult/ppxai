"""
Container management tools for Docker, Podman, and Kubernetes.

Provides read-only inspection and management operations with consent
for destructive actions.

v1.13.8: Initial implementation
v1.13.10: Refactored to reduce code duplication using parameterized base classes
"""

import shutil
import subprocess
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Callable

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
# Base Classes for CLI Tools (reduces duplication)
# =============================================================================

class CLITool(BaseTool):
    """
    Base class for read-only CLI tools.

    Subclasses define:
        - name, description, parameters (tool metadata)
        - build_command(): returns the command list
        - runtime_check(): returns error string or None
    """

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self._timeout = 30

    def runtime_check(self) -> Optional[str]:
        """Override to check runtime availability. Return error string or None."""
        return None

    def build_command(self, **kwargs) -> List[str]:
        """Override to build the command. Return list of command args."""
        raise NotImplementedError

    async def execute(self, **kwargs) -> str:
        error = self.runtime_check()
        if error:
            return error
        cmd = self.build_command(**kwargs)
        return _run_command(cmd, timeout=self._timeout)


class ConsentCLITool(CLITool):
    """
    Base class for CLI tools requiring user consent.

    Adds consent request before command execution.
    """

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
        self._timeout = 60

    def build_consent_description(self, **kwargs) -> str:
        """Override to build human-readable command description for consent."""
        cmd = self.build_command(**kwargs)
        return ' '.join(cmd)

    async def execute(self, **kwargs) -> str:
        error = self.runtime_check()
        if error:
            return error

        # Request consent
        cmd_str = self.build_consent_description(**kwargs)
        working_dir = self.engine.get_working_dir() or "."
        consent = await self.engine.request_shell_consent(cmd_str, working_dir)
        if not consent:
            return f"Error: User denied permission to execute: {cmd_str}"

        cmd = self.build_command(**kwargs)
        return _run_command(cmd, timeout=self._timeout)


class DockerTool(CLITool):
    """Base class for Docker/Podman tools."""

    def runtime_check(self) -> Optional[str]:
        if not detect_container_runtime():
            return "Error: No container runtime found. Install Docker or Podman."
        return None

    @property
    def runtime(self) -> str:
        return detect_container_runtime() or 'docker'


class DockerConsentTool(ConsentCLITool):
    """Base class for Docker/Podman tools requiring consent."""

    def runtime_check(self) -> Optional[str]:
        if not detect_container_runtime():
            return "Error: No container runtime found. Install Docker or Podman."
        return None

    @property
    def runtime(self) -> str:
        return detect_container_runtime() or 'docker'


class KubeTool(CLITool):
    """Base class for Kubernetes tools."""

    def runtime_check(self) -> Optional[str]:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found. Install Kubernetes CLI."
        return None


class KubeConsentTool(ConsentCLITool):
    """Base class for Kubernetes tools requiring consent."""

    def runtime_check(self) -> Optional[str]:
        if not detect_kubernetes_cli():
            return "Error: kubectl not found. Install Kubernetes CLI."
        return None


# =============================================================================
# Docker/Podman Tools
# =============================================================================

class ContainerListTool(DockerTool):
    """List containers."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, all: bool = False, filter: str = None, **kwargs) -> List[str]:
        cmd = [
            self.runtime, 'ps',
            '--format', 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
        ]
        if all:
            cmd.insert(2, '-a')
        if filter:
            cmd.extend(['--filter', filter])
        return cmd


class ContainerLogsTool(DockerTool):
    """Get container logs."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, container: str, tail: int = 100, since: str = None, **kwargs) -> List[str]:
        cmd = [self.runtime, 'logs', '--tail', str(tail)]
        if since:
            cmd.extend(['--since', since])
        cmd.append(container)
        return cmd


class ContainerInspectTool(DockerTool):
    """Inspect container details."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, container: str, format: str = None, **kwargs) -> List[str]:
        cmd = [self.runtime, 'inspect']
        if format:
            cmd.extend(['--format', format])
        cmd.append(container)
        return cmd


class ContainerStartStopTool(DockerConsentTool):
    """Start, stop, or restart a container (requires consent)."""

    def __init__(self, engine: 'EngineClient', action: str):
        super().__init__(engine)
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

    def build_command(self, container: str, **kwargs) -> List[str]:
        return [self.runtime, self.action, container]


class ContainerExecTool(DockerConsentTool):
    """Execute command in a running container (requires consent)."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
        self._timeout = 30
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

    def build_command(self, container: str, command: str, workdir: str = None, **kwargs) -> List[str]:
        cmd = [self.runtime, 'exec']
        if workdir:
            cmd.extend(['-w', workdir])
        cmd.append(container)
        cmd.extend(command.split())
        return cmd

    def build_consent_description(self, container: str, command: str, **kwargs) -> str:
        return f"{self.runtime} exec {container} {command}"


class ImageListTool(DockerTool):
    """List container images."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, all: bool = False, filter: str = None, **kwargs) -> List[str]:
        cmd = [
            self.runtime, 'images',
            '--format', 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}'
        ]
        if all:
            cmd.insert(2, '-a')
        if filter:
            cmd.extend(['--filter', filter])
        return cmd


# =============================================================================
# Kubernetes Tools
# =============================================================================

class KubePodListTool(KubeTool):
    """List Kubernetes pods."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, namespace: str = None, all_namespaces: bool = False, selector: str = None, **kwargs) -> List[str]:
        cmd = ['kubectl', 'get', 'pods', '-o', 'wide']
        if all_namespaces:
            cmd.append('-A')
        elif namespace:
            cmd.extend(['-n', namespace])
        if selector:
            cmd.extend(['-l', selector])
        return cmd


class KubePodLogsTool(KubeTool):
    """Get pod logs."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, pod: str, namespace: str = None, container: str = None, tail: int = 100, previous: bool = False, **kwargs) -> List[str]:
        cmd = ['kubectl', 'logs', pod, '--tail', str(tail)]
        if namespace:
            cmd.extend(['-n', namespace])
        if container:
            cmd.extend(['-c', container])
        if previous:
            cmd.append('--previous')
        return cmd


class KubePodDescribeTool(KubeTool):
    """Describe a pod."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, pod: str, namespace: str = None, **kwargs) -> List[str]:
        cmd = ['kubectl', 'describe', 'pod', pod]
        if namespace:
            cmd.extend(['-n', namespace])
        return cmd


class KubeDeploymentListTool(KubeTool):
    """List deployments."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, namespace: str = None, all_namespaces: bool = False, **kwargs) -> List[str]:
        cmd = ['kubectl', 'get', 'deployments', '-o', 'wide']
        if all_namespaces:
            cmd.append('-A')
        elif namespace:
            cmd.extend(['-n', namespace])
        return cmd


class KubeServiceListTool(KubeTool):
    """List services."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, namespace: str = None, all_namespaces: bool = False, **kwargs) -> List[str]:
        cmd = ['kubectl', 'get', 'services', '-o', 'wide']
        if all_namespaces:
            cmd.append('-A')
        elif namespace:
            cmd.extend(['-n', namespace])
        return cmd


class KubeApplyTool(KubeConsentTool):
    """Apply Kubernetes manifest (requires consent)."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
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

    def build_command(self, file: str, namespace: str = None, dry_run: bool = False, **kwargs) -> List[str]:
        cmd = ['kubectl', 'apply', '-f', file]
        if namespace:
            cmd.extend(['-n', namespace])
        if dry_run:
            cmd.append('--dry-run=client')
        return cmd

    def build_consent_description(self, file: str, namespace: str = None, dry_run: bool = False, **kwargs) -> str:
        cmd_str = f"kubectl apply -f {file}"
        if namespace:
            cmd_str += f" -n {namespace}"
        if dry_run:
            cmd_str += " --dry-run=client"
        return cmd_str


class KubePodExecTool(KubeConsentTool):
    """Execute command in a pod (requires consent)."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
        self._timeout = 30
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

    def build_command(self, pod: str, command: str, namespace: str = None, container: str = None, **kwargs) -> List[str]:
        cmd = ['kubectl', 'exec', pod]
        if namespace:
            cmd.extend(['-n', namespace])
        if container:
            cmd.extend(['-c', container])
        cmd.append('--')
        cmd.extend(command.split())
        return cmd

    def build_consent_description(self, pod: str, command: str, **kwargs) -> str:
        return f"kubectl exec {pod} -- {command}"


class KubeNamespaceListTool(KubeTool):
    """List namespaces."""

    def __init__(self, engine: 'EngineClient'):
        super().__init__(engine)
        self.name = "namespace_list"
        self.description = "List Kubernetes namespaces."
        self.parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }

    def build_command(self, **kwargs) -> List[str]:
        return ['kubectl', 'get', 'namespaces']


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

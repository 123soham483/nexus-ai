"""DockerSandbox — run model-generated code with no network and no escape hatch.

Generated code is *untrusted*: it comes from an LLM and may be wrong, hostile,
or contain a prompt-injected payload. It therefore never runs in this process.
Every execution goes through a throwaway container with the hardening below:

    --network none              no egress at all (exfiltration is impossible)
    --read-only + --tmpfs /tmp  the image root is immutable; /tmp is scratch
    --cap-drop ALL              no capabilities
    --security-opt no-new-privileges   cannot gain privileges via setuid
    --pids-limit 64             a fork bomb cannot take the host down
    --memory/--cpus             bounded CPU and memory
    --user 65534:65534          unprivileged nobody, never root
    --rm                        always cleaned up

The program is fed over **stdin** (``python -``), so no host path is ever
mounted — code cannot read the repo, the host filesystem, or the docker socket.

The runner is injectable, and the argv is built by a pure function
(:meth:`DockerSandbox.build_command`) so the security flags are asserted in
tests rather than trusted.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

#: Container name prefix; also how the timeout path finds what to kill.
CONTAINER_PREFIX = "nexusai-sandbox-"
#: Output cap — a runaway print loop must not blow up the AgentRun row.
MAX_OUTPUT_BYTES = 20_000

#: Injectable process runner: (argv, stdin) -> (exit_code, stdout, stderr).
Runner = Callable[[Sequence[str], str], Awaitable[Tuple[int, str, str]]]


@dataclass
class SandboxResult:
    """Outcome of one sandboxed execution (JSON-safe, embeddable in a result)."""

    command: List[str] = field(default_factory=list)
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    container: str = ""
    #: Set only when the sandbox itself failed (docker missing, image absent…),
    #: which is different from the *code* failing.
    error: str = ""

    @property
    def success(self) -> bool:
        """True only when the code ran to completion and exited 0."""
        return not self.error and not self.timed_out and self.exit_code == 0

    def to_dict(self, max_chars: int = MAX_OUTPUT_BYTES) -> Dict[str, object]:
        """Serializable view for embedding in an ``AgentResult.parsed`` blob."""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "error": self.error,
            "container": self.container,
            "duration_seconds": round(self.duration_seconds, 3),
            "stdout": self.stdout[:max_chars],
            "stderr": self.stderr[:max_chars],
        }


class DockerSandbox:
    """Runs untrusted programs in a locked-down throwaway container."""

    def __init__(
        self,
        image: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        memory_limit: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        pids_limit: int = 64,
        docker_bin: str = "docker",
        runner: Optional[Runner] = None,
    ) -> None:
        self.image = image or settings.SANDBOX_IMAGE
        self.timeout_seconds = (
            settings.SANDBOX_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        )
        self.memory_limit = memory_limit or settings.SANDBOX_MEMORY_LIMIT
        self.cpu_limit = (
            settings.SANDBOX_CPU_LIMIT if cpu_limit is None else cpu_limit
        )
        self.pids_limit = pids_limit
        self.docker_bin = docker_bin
        self._runner = runner
        self._available: Optional[bool] = None

    # ── command construction (pure → asserted in tests) ──────────────────────
    def build_command(self, container: str, command: Sequence[str]) -> List[str]:
        """The full ``docker run`` argv for one sandboxed execution."""
        return [
            self.docker_bin,
            "run",
            "--rm",
            "-i",
            "--name",
            container,
            # ── isolation ────────────────────────────────────────────────────
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",  # nobody:nogroup
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=32m",
            # ── resource bounds ──────────────────────────────────────────────
            "--memory",
            self.memory_limit,
            "--memory-swap",
            self.memory_limit,  # no swap beyond the limit
            "--cpus",
            str(self.cpu_limit),
            "--pids-limit",
            str(self.pids_limit),
            # ── runtime ──────────────────────────────────────────────────────
            "--workdir",
            "/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "HOME=/tmp",
            self.image,
            *command,
        ]

    # ── availability ─────────────────────────────────────────────────────────
    async def available(self) -> bool:
        """Whether a usable docker CLI is present (probed once, then cached)."""
        if self._available is None:
            self._available = await self._probe()
        return self._available

    async def _probe(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.docker_bin,
                "version",
                "--format",
                "{{.Server.Version}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (OSError, asyncio.TimeoutError):
            return False
        return proc.returncode == 0 and bool(stdout)

    # ── execution ────────────────────────────────────────────────────────────
    async def run_python(self, code: str, *, args: Sequence[str] = ()) -> SandboxResult:
        """Run ``code`` as a Python program inside the sandbox."""
        return await self.run(["python", "-", *args], stdin=code or "")

    async def run(self, command: Sequence[str], *, stdin: str = "") -> SandboxResult:
        """Run one command in the sandbox, bounded by ``timeout_seconds``.

        Never raises: an unreachable docker daemon or a missing image comes back
        as a :class:`SandboxResult` with ``error`` set, so a failing sandbox
        degrades the agent's confidence instead of crashing a task.
        """
        container = f"{CONTAINER_PREFIX}{uuid.uuid4().hex[:12]}"
        argv = self.build_command(container, command)
        runner = self._runner or self._subprocess_runner
        started = time.perf_counter()
        try:
            exit_code, stdout, stderr = await asyncio.wait_for(
                runner(argv, stdin), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            return SandboxResult(
                command=argv,
                exit_code=-1,
                stderr=f"execution timed out after {self.timeout_seconds}s",
                duration_seconds=time.perf_counter() - started,
                timed_out=True,
                container=container,
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("DockerSandbox unavailable: %s", exc)
            return SandboxResult(
                command=argv,
                exit_code=-1,
                error=f"sandbox unavailable: {exc}",
                duration_seconds=time.perf_counter() - started,
                container=container,
            )

        return SandboxResult(
            command=argv,
            exit_code=exit_code,
            stdout=_truncate(stdout),
            stderr=_truncate(stderr),
            duration_seconds=time.perf_counter() - started,
            container=container,
        )

    # ── default runner ───────────────────────────────────────────────────────
    async def _subprocess_runner(
        self, argv: Sequence[str], stdin: str
    ) -> Tuple[int, str, str]:
        """Run the docker CLI; on cancellation kill the container, not just it.

        ``docker run`` is a *client*: killing it leaves the container running, so
        the container is killed by name and then removed explicitly.
        """
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate(stdin.encode("utf-8"))
        except asyncio.CancelledError:
            await self._force_kill(proc, _container_from_argv(argv))
            raise
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _force_kill(self, proc, container: str) -> None:
        """Kill the container and the CLI process (best effort, never raises)."""
        if container:
            try:
                killer = await asyncio.create_subprocess_exec(
                    self.docker_bin,
                    "kill",
                    container,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=10)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("DockerSandbox: docker kill %s failed: %s", container, exc)
        try:
            proc.kill()
        except ProcessLookupError:  # pragma: no cover - already gone
            pass


def _container_from_argv(argv: Sequence[str]) -> str:
    """The ``--name`` value in an argv produced by :meth:`build_command`."""
    try:
        return str(argv[list(argv).index("--name") + 1])
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return ""


def _truncate(text: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… [truncated {len(text) - limit} chars]"

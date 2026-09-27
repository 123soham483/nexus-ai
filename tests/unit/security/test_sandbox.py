"""Tests for DockerSandbox (Phase 3, Step 3.6).

The argv is asserted flag-by-flag — a security control that is never checked is
not a control — and execution semantics are exercised through an injected
runner, so no Docker daemon is required.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.security.sandbox import (
    CONTAINER_PREFIX,
    DockerSandbox,
    SandboxResult,
    _truncate,
)


class FakeRunner:
    """Injectable process runner: records argv/stdin, returns canned output."""

    def __init__(self, exit_code=0, stdout="ok", stderr="", delay=0.0, error=None):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.delay = delay
        self.error = error
        self.argv = None
        self.stdin = None
        self.calls = 0

    async def __call__(self, argv, stdin):
        self.calls += 1
        self.argv = list(argv)
        self.stdin = stdin
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.exit_code, self.stdout, self.stderr


def _sandbox(runner=None, **kwargs) -> DockerSandbox:
    kwargs.setdefault("timeout_seconds", 5)
    return DockerSandbox(runner=runner or FakeRunner(), **kwargs)


# ── hardening (the reason this module exists) ────────────────────────────────

def _argv(sandbox=None, command=("python", "-")) -> list[str]:
    sandbox = sandbox or _sandbox()
    return sandbox.build_command("nexusai-sandbox-test", list(command))


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--network", "none"),          # no egress → exfiltration impossible
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--user", "65534:65534"),      # unprivileged nobody:nogroup
        ("--memory", "256m"),
        ("--memory-swap", "256m"),      # no swap escape hatch
        ("--cpus", "0.5"),
        ("--pids-limit", "64"),
        ("--workdir", "/tmp"),
    ],
)
def test_build_command_contains_isolation_flag(flag, value):
    argv = _argv()
    assert flag in argv, f"{flag} missing from {argv}"
    assert argv[argv.index(flag) + 1] == value


def test_root_filesystem_is_read_only_with_a_scratch_tmpfs():
    argv = _argv()
    assert "--read-only" in argv
    tmpfs = argv[argv.index("--tmpfs") + 1]
    assert tmpfs.startswith("/tmp:")
    assert "nosuid" in tmpfs


def test_image_and_command_come_last():
    argv = _argv(DockerSandbox(runner=FakeRunner(), image="python:3.11-slim"))
    assert argv[-3:] == ["python:3.11-slim", "python", "-"]


@pytest.mark.parametrize(
    "dangerous",
    ["--privileged", "--net=host", "--network=host", "-v", "--volume",
     "--mount", "--pid=host", "--ipc=host", "--userns=host", "--device"],
)
def test_build_command_never_grants_host_access(dangerous):
    argv = _argv()
    assert dangerous not in argv
    # Neither the host filesystem nor the docker socket can be mounted: the
    # program is delivered over stdin, so there is nothing to bind-mount.
    assert not any(str(a).startswith("/var/run/docker.sock") for a in argv)


def test_read_only_docker_socket_is_not_reachable():
    argv = _argv()
    joined = " ".join(argv)
    assert "docker.sock" not in joined
    assert "/var/run" not in joined


def test_container_is_always_removed():
    assert "--rm" in _argv()


# ── execution ────────────────────────────────────────────────────────────────

async def test_run_python_feeds_code_over_stdin():
    runner = FakeRunner()
    sandbox = _sandbox(runner)

    result = await sandbox.run_python("print('hello')")

    assert runner.stdin == "print('hello')"
    assert runner.argv[-2:] == ["python", "-"]
    assert result.exit_code == 0
    assert result.success is True


async def test_each_run_gets_a_unique_prefixed_container_name():
    """Unique names are how the timeout path knows exactly what to kill."""
    runner = FakeRunner()
    sandbox = _sandbox(runner)

    await sandbox.run_python("pass")
    first = runner.argv[runner.argv.index("--name") + 1]
    await sandbox.run_python("pass")
    second = runner.argv[runner.argv.index("--name") + 1]

    assert first.startswith(CONTAINER_PREFIX)
    assert second.startswith(CONTAINER_PREFIX)
    assert first != second


async def test_nonzero_exit_is_a_failed_result_not_an_exception():
    runner = FakeRunner(exit_code=1, stderr="AssertionError: 1 != 2")
    result = await _sandbox(runner).run_python("assert False")

    assert result.success is False
    assert result.exit_code == 1
    assert "AssertionError" in result.stderr


async def test_timeout_returns_a_timed_out_result():
    runner = FakeRunner(delay=5)
    sandbox = _sandbox(runner, timeout_seconds=0.05)

    result = await sandbox.run_python("while True: pass")

    assert result.timed_out is True
    assert result.success is False
    assert "timed out" in result.stderr
    assert result.exit_code == -1


async def test_missing_docker_binary_degrades_to_an_error_result():
    runner = FakeRunner(error=FileNotFoundError("docker not found"))
    result = await _sandbox(runner).run_python("print(1)")

    assert result.error.startswith("sandbox unavailable")
    assert result.success is False
    assert result.timed_out is False


async def test_output_is_truncated():
    runner = FakeRunner(stdout="x" * 50_000)
    result = await _sandbox(runner).run_python("print('x')")

    assert len(result.stdout) < 50_000
    assert "truncated" in result.stdout


def test_truncate_leaves_short_text_alone():
    assert _truncate("short") == "short"
    assert _truncate(None) == ""


async def test_result_to_dict_is_json_serializable():
    result = await _sandbox(FakeRunner(stdout="hi")).run_python("print('hi')")
    payload = json.loads(json.dumps(result.to_dict()))

    assert payload["success"] is True
    assert payload["stdout"] == "hi"
    assert set(payload) >= {"exit_code", "timed_out", "duration_seconds", "container"}


async def test_duration_is_recorded():
    result = await _sandbox(FakeRunner()).run_python("pass")
    assert result.duration_seconds >= 0


# ── availability probe ───────────────────────────────────────────────────────

# ── the real subprocess runner ──────────────────────────────────────────────

class _FakeProc:
    """Stand-in for asyncio.subprocess.Process, with a never-finishing stdin read."""

    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self, data=None):
        if data is None:  # the `docker version` probe path
            return self._stdout, self._stderr
        await asyncio.Event().wait()  # a container that never exits
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


async def test_probe_reports_a_reachable_daemon(monkeypatch):
    async def fake_exec(*argv, **kwargs):
        return _FakeProc(returncode=0, stdout=b"25.0.1")  # a server version

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await DockerSandbox().available() is True


async def test_probe_reports_an_unreachable_daemon(monkeypatch):
    async def fake_exec(*argv, **kwargs):
        return _FakeProc(returncode=1, stderr=b"cannot connect to the docker daemon")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await DockerSandbox().available() is False


async def test_cancellation_kills_the_container_not_just_the_cli(monkeypatch):
    """`docker run` is only a client — killing it would leave the container up."""
    created = []

    async def fake_exec(*argv, **kwargs):
        proc = _FakeProc()
        created.append((argv, proc))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    sandbox = DockerSandbox(timeout_seconds=30)
    argv = sandbox.build_command(f"{CONTAINER_PREFIX}abc123", ["python", "-"])

    running = asyncio.create_task(sandbox._subprocess_runner(argv, "while True: pass"))
    await asyncio.sleep(0.01)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    # A second process was spawned to kill the container by name, and the CLI
    # process itself was killed too.
    assert len(created) == 2
    kill_argv, _ = created[1]
    assert kill_argv[1] == "kill"
    assert kill_argv[2] == f"{CONTAINER_PREFIX}abc123"
    assert created[0][1].killed is True


async def test_container_name_extraction_from_argv():
    from app.security.sandbox import _container_from_argv

    assert _container_from_argv(["docker", "run", "--name", "c1", "img"]) == "c1"
    assert _container_from_argv(["docker", "run"]) == ""


class _ProbeCountingSandbox(DockerSandbox):
    def __init__(self, available: bool, **kwargs):
        super().__init__(runner=FakeRunner(), **kwargs)
        self.probe_calls = 0
        self._answer = available

    async def _probe(self) -> bool:
        self.probe_calls += 1
        return self._answer


async def test_available_is_probed_once_and_cached():
    sandbox = _ProbeCountingSandbox(available=True)
    assert await sandbox.available() is True
    assert await sandbox.available() is True
    assert sandbox.probe_calls == 1


async def test_unavailable_daemon_is_reported_not_raised():
    sandbox = _ProbeCountingSandbox(available=False)
    assert await sandbox.available() is False


async def test_sandbox_uses_settings_defaults():
    from app.config import settings

    sandbox = DockerSandbox(runner=FakeRunner())
    assert sandbox.image == settings.SANDBOX_IMAGE
    assert sandbox.memory_limit == settings.SANDBOX_MEMORY_LIMIT
    assert sandbox.cpu_limit == settings.SANDBOX_CPU_LIMIT
    assert sandbox.timeout_seconds == settings.SANDBOX_TIMEOUT_SECONDS

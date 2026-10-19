"""OS isolation for generated pure-data Python methods; never fall back to host exec."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.errors import ServiceError

WORKER = Path(__file__).with_name("worker.py").resolve()
DOCKER_IMAGE = "python:3.11-slim"


def macos_profile(worker=WORKER, extra_readable=()):
    readable = [sys.base_prefix, "/System/Library", "/usr/lib", "/usr/share/zoneinfo", *extra_readable]
    rules = " ".join(f"(subpath {json.dumps(path)})" for path in readable)
    literals = " ".join(f"(literal {json.dumps(path)})" for path in ("/", str(worker), str(Path(sys.prefix) / "pyvenv.cfg"), "/dev/null", "/dev/random", "/dev/urandom", "/private/etc/localtime"))
    executables = [str(Path(sys.executable).resolve())]
    framework_launcher = Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python"
    if framework_launcher.exists():
        executables.append(str(framework_launcher))
    executable_rules = " ".join(f"(literal {json.dumps(path)})" for path in executables)
    return f"(version 1) (deny default) (allow process-exec {executable_rules}) (allow sysctl-read) (allow file-read-metadata) (allow file-read* {rules} {literals})"


class CodeSandbox:
    def _command(self):
        if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
            return ["/usr/bin/sandbox-exec", "-p", macos_profile(), sys.executable, "-I", "-S", "-B", str(WORKER)]
        docker = shutil.which("docker")
        if docker:
            # No host mounts, credentials, networking, writable root or Docker socket.
            return [docker, "run", "--pull=never", "--rm", "-i", "--network=none", "--read-only", "--cap-drop=ALL",
                    "--security-opt=no-new-privileges", "--pids-limit=16", "--memory=256m", "--cpus=1",
                    "--user=65534:65534", DOCKER_IMAGE, "python", "-I", "-S", "-B", "-c", WORKER.read_text()]
        raise ServiceError("独立执行环境尚未就绪。macOS 需要 sandbox-exec，Linux 需要可用 Docker 和 python:3.11-slim 镜像。", 503)

    def execute(self, code, arguments):
        try:
            wire = json.dumps({"code": code, "arguments": arguments}, allow_nan=False).encode()
        except (ValueError, TypeError) as error:
            raise ServiceError("参数必须是有效 JSON，不能包含非有限数值。", 422) from error
        if len(wire) > 160000:
            raise ServiceError("本次输入连同方法代码超过 160 KB，请减少输入数据。", 422)
        command = self._command()
        environment = {"PATH": "/usr/bin:/bin:/usr/local/bin", "LANG": "C", "LC_ALL": "C"}
        # docker needs its normal engine location, but no model credentials are passed.
        if Path(command[0]).name == "docker":
            for key in ("HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"):
                if key in os.environ:
                    environment[key] = os.environ[key]
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=environment, start_new_session=True, cwd="/private/tmp" if sys.platform == "darwin" else "/tmp")
        except OSError as error:
            raise ServiceError("独立执行环境无法启动，请检查运行器配置。", 503) from error
        try:
            deadline = time.monotonic() + 7
            first = True
            while True:
                try:
                    stdout, _ = process.communicate(wire if first else None, timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    if time.monotonic() >= deadline:
                        raise
                    if sys.platform == "darwin":
                        # macOS rejects RLIMIT_AS/DATA; the parent enforces RSS.
                        usage = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                                               capture_output=True, text=True, timeout=1)
                        if usage.stdout.strip().isdigit() and int(usage.stdout) > 256 * 1024:
                            raise subprocess.TimeoutExpired(command, 7)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise ServiceError("方法运行超时，已停止。请简化计算或缩小输入。", 422)
        if process.returncode or len(stdout) > 65536:
            raise ServiceError("独立执行环境启动失败或方法触发资源限制，未在主机环境重试。", 503)
        try:
            result = json.loads(stdout)
        except (ValueError, UnicodeDecodeError):
            raise ServiceError("方法未返回有效的 JSON 结果。", 422)
        if not result.get("ok"):
            raise ServiceError(result.get("error", "方法执行失败。"), 422)
        return result["result"]

    def status(self):
        try:
            if self.execute("def run(arguments):\n    return {'ready': True}", {}) == {"ready": True}:
                return {"available": True, "runtime": "python-stdlib-v1", "message": "文本与结构化数据方法可独立运行。"}
        except (OSError, ServiceError):
            pass
        return {"available": False, "runtime": "python-stdlib-v1", "message": "独立执行环境尚未就绪，暂时不能测试或发布生成的方法。"}

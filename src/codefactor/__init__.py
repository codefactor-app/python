"""Importable client for the separately maintained Codefactor core executable."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable
from ._core import ConfigError, argument_context, resolve_binary

__all__ = ["Codefactor", "CodefactorError", "Result", "scan"]


class CodefactorError(RuntimeError):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


@dataclass(frozen=True)
class Result:
    data: dict[str, Any]
    exit_code: int
    stderr: str


def absolute(path: str | os.PathLike[str]) -> str:
    value = os.fspath(path)
    if not value or "\0" in value:
        raise ValueError("Invalid path")
    return str(Path(value).resolve())


class Codefactor:
    def __init__(self, binary: str | os.PathLike[str] | None = None, timeout: float = 120):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be positive")
        self.binary = absolute(binary) if binary is not None else None
        self.timeout = timeout

    def scan(self, root: str | os.PathLike[str] = ".", *, config: str | os.PathLike[str] | None = None,
             languages: Iterable[str] | None = None, architecture: bool = True, strict_config: bool = False) -> Result:
        args = ["scan", "--format", "json"]
        if config is not None:
            args += ["--config", absolute(config)]
        if languages is not None:
            languages = list(languages)
            if not languages or any(language not in {"php", "python", "rust", "javascript", "typescript", "js", "ts"} for language in languages):
                raise ValueError("Invalid languages")
            args += ["--lang", ",".join(languages)]
        if not architecture:
            args.append("--no-architecture")
        if strict_config:
            args.append("--strict-config")
        result = self._run([*args, "--", absolute(root)])
        if not isinstance(result.data.get("summary"), dict) or not isinstance(result.data.get("files"), list) or not result.data.get("schema_version"):
            raise CodefactorError("Invalid Codefactor analysis report")
        return result

    def ast(self, path: str | os.PathLike[str], config: str | os.PathLike[str] | None = None) -> Result:
        return self._run(["ast", "--format", "json", *(["--config", absolute(config)] if config is not None else []), "--", absolute(path)])

    def graph(self, selector: str, root: str | os.PathLike[str] = ".", direction: str = "both", depth: int | None = None) -> Result:
        if direction not in {"callers", "callees", "both"} or (depth is not None and (not isinstance(depth, int) or isinstance(depth, bool) or depth < 0)):
            raise ValueError("Invalid graph direction or depth")
        return self._run(["graph", direction, "--root", absolute(root), "--format", "json", *(["--depth", str(depth)] if depth is not None else []), "--", selector])

    def _run(self, args: list[str]) -> Result:
        try:
            binary = self.binary or str(resolve_binary(**argument_context(args)))
        except (OSError, ValueError, RuntimeError) as error:
            raise CodefactorError(str(error), 3 if isinstance(error, ConfigError) else None) from error
        try:
            process = subprocess.run([binary, *args], capture_output=True, text=True, encoding="utf-8", timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as error:
            raise CodefactorError("Codefactor analysis timed out") from error
        except OSError as error:
            raise CodefactorError("Cannot start Codefactor binary; run codefactor core update or check CODEFACTOR_BINARY") from error
        if process.returncode not in {0, 1, 2}:
            raise CodefactorError(f"Codefactor failed ({process.returncode}): {process.stderr.strip()}", process.returncode, process.stderr)
        try:
            data = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise CodefactorError(f"Codefactor failed ({process.returncode}): {process.stderr.strip()}", process.returncode, process.stderr) from error
        if not isinstance(data, dict):
            raise CodefactorError("Codefactor did not return a JSON object")
        return Result(data, process.returncode, process.stderr)


def scan(root: str | os.PathLike[str] = ".", **options: Any) -> Result:
    return Codefactor().scan(root, **options)

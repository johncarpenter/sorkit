"""Oracle runner — execute tests, extract metrics, compute composite scores."""

from __future__ import annotations

import asyncio
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sorkit.config import SorConfig


@dataclass
class OracleResult:
    passed: bool
    scored: bool = False
    composite: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    output: str = ""
    error: bool = False
    error_message: str | None = None


async def run_oracle(
    config: SorConfig, layer_idx: int, project_dir: Path
) -> OracleResult:
    """Run the oracle for a layer: contracts first, then scored tests if applicable."""
    layer = config.layers[layer_idx]
    oracle = layer.oracle
    test_runner = config.defaults.test_runner

    # Step 1: Run contract tests
    contract_output = ""
    if oracle.contracts:
        contract_result = await _run_tests(
            test_runner, oracle.contracts, project_dir,
        )
        contract_output = contract_result.stdout
        if contract_result.returncode != 0:
            return _classify_failure(contract_result, "Contract tests failed")

    # Step 2: Non-scored layer — contracts passing is enough
    if not oracle.scored:
        return OracleResult(
            passed=True,
            scored=False,
            output=contract_output,
        )

    # Step 3: Run scored tests and extract metrics
    if not oracle.scored_tests:
        return OracleResult(
            passed=False,
            error=True,
            error_message="Scored layer has no scored_tests defined",
        )

    scored_result = await _run_tests(
        test_runner, oracle.scored_tests, project_dir, capture_output=False,
    )
    scored_output = scored_result.stdout

    if scored_result.returncode != 0:
        return _classify_failure(scored_result, "Scored tests failed")

    # Extract metrics from stdout
    metrics: dict[str, float] = {}
    for metric in oracle.metrics:
        val = _extract_metric(scored_output, metric.extract)
        if val is None:
            return OracleResult(
                passed=False,
                scored=True,
                error=True,
                error_message=(
                    f"Could not extract metric '{metric.name}' "
                    f"(pattern: {metric.extract})"
                ),
                output=scored_output,
            )
        metrics[metric.name] = val

    if not metrics:
        return OracleResult(
            passed=False,
            scored=True,
            error=True,
            error_message="No metrics defined for scored layer",
            output=scored_output,
        )

    # Compute weighted composite
    composite = sum(
        metrics[m.name] * m.weight for m in oracle.metrics
    )

    return OracleResult(
        passed=True,
        scored=True,
        composite=round(composite, 4),
        metrics=metrics,
        output=scored_output,
    )


def _extract_metric(output: str, pattern: str) -> float | None:
    """Extract a numeric metric value from test output.

    Looks for lines matching `^{pattern}:  <value>` (or similar spacing).
    If multiple matches, takes the last one (matching bash `tail -1` behavior).
    """
    regex = re.compile(rf"^{re.escape(pattern)}:\s+(\S+)", re.MULTILINE)
    matches = regex.findall(output)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


async def _run_tests(
    test_runner: str,
    test_path: str,
    project_dir: Path,
    *,
    capture_output: bool = True,
) -> _SubprocessResult:
    """Run a test command and capture output.

    Args:
        capture_output: If False, adds -s flag to disable pytest output capture.
            Used for scored tests so metric print statements appear in stdout.
    """
    base_args = [test_path, "-x", "--tb=short", "-q"]
    if not capture_output:
        base_args.append("-s")

    if sys.platform == "win32":
        cmd_parts = test_runner.split() + base_args
    else:
        cmd_parts = shlex.split(test_runner) + base_args

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=project_dir,
        )
        stdout_bytes, _ = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        return _SubprocessResult(returncode=proc.returncode or 0, stdout=stdout)
    except FileNotFoundError as e:
        return _SubprocessResult(
            returncode=127,
            stdout=f"Command not found: {cmd_parts[0]}\n{e}",
        )
    except Exception as e:
        return _SubprocessResult(
            returncode=1,
            stdout=f"Oracle error: {e}",
        )


@dataclass
class _SubprocessResult:
    returncode: int
    stdout: str


def _classify_failure(result: _SubprocessResult, default_msg: str) -> OracleResult:
    """Classify a test failure as either a test failure or an oracle infrastructure error.

    Oracle errors are infrastructure crashes (import errors, missing files, etc.)
    as opposed to test assertion failures which are normal operation.
    """
    output = result.stdout
    is_oracle_error = (
        "Traceback" in output
        and "AssertionError" not in output
        and "assert " not in output
        and "FAILED" not in output
    ) or result.returncode == 127  # command not found

    if is_oracle_error:
        return OracleResult(
            passed=False,
            error=True,
            error_message=f"Oracle error: {default_msg}",
            output=output,
        )

    return OracleResult(
        passed=False,
        error=False,
        error_message=default_msg,
        output=output,
    )

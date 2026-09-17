"""Cycle-by-cycle HTTP producer for the local FD001 application."""

from __future__ import annotations

from dataclasses import dataclass
import sys
import time
from typing import Any, Callable, Protocol

import httpx


class PredictionTransport(Protocol):
    """Small transport contract that also makes tests independent of HTTP."""

    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class SimulationConfig:
    api_base_url: str = "http://127.0.0.1:8000"
    unit_id: int = 1
    horizon: int = 30
    model: str = "fusion"
    telemetry_policy: str = "full"
    cadence: str = "each_cycle"
    interval_seconds: float = 1.0
    mode: str = "real_time_simulated"
    speed: float = 1.0
    start_cycle: int = 1
    max_cycles: int | None = None

    def __post_init__(self) -> None:
        if self.unit_id <= 0:
            raise ValueError("unit_id must be positive")
        if self.horizon <= 0:
            raise ValueError("horizon must be positive")
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds cannot be negative")
        if self.speed <= 0:
            raise ValueError("speed must be positive")
        if self.start_cycle <= 0:
            raise ValueError("start_cycle must be positive")
        if self.max_cycles is not None and self.max_cycles <= 0:
            raise ValueError("max_cycles must be positive when provided")
        if self.mode not in {"real_time_simulated", "fast"}:
            raise ValueError("mode must be real_time_simulated or fast")


@dataclass(frozen=True)
class SimulationResult:
    cycles_sent: tuple[int, ...]
    stopped_reason: str


class TelemetrySimulator:
    """Generate monotonically increasing cycle requests for one unit."""

    def __init__(
        self,
        config: SimulationConfig,
        transport: PredictionTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        output: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport or httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._output = output or sys.stdout
        self._paused = False
        self._stopped = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stopped = True

    def _url(self, path: str) -> str:
        return f"{self.config.api_base_url.rstrip('/')}{path}"

    def _payload(self, cycle: int) -> dict[str, Any]:
        return {
            "unit_id": self.config.unit_id,
            "cycle": cycle,
            "horizon": self.config.horizon,
            "model": self.config.model,
            "telemetry_policy": self.config.telemetry_policy,
            "cadence": self.config.cadence,
        }

    def _show(self, payload: dict[str, Any]) -> None:
        risk = payload.get("risk_score")
        risk_text = "unavailable" if risk is None else f"{float(risk):.4f}"
        print(
            f"cycle={payload.get('cycle')} risk_score={risk_text} "
            f"alert_level={payload.get('alert_level', 'n/a')} "
            f"prediction_status={payload.get('prediction_status', 'unknown')}",
            file=self._output,
            flush=True,
        )

    def run(self) -> SimulationResult:
        """Send one POST per cycle and stop cleanly on interruption/errors."""

        sent: list[int] = []
        try:
            metadata = self.transport.get(self._url(f"/api/v1/units/{self.config.unit_id}"))
            metadata.raise_for_status()
            last_cycle = int(metadata.json()["last_cycle"])
            if last_cycle < 1:
                return SimulationResult((), "empty_unit")

            stop_cycle = last_cycle
            if self.config.max_cycles is not None:
                stop_cycle = min(last_cycle, self.config.start_cycle + self.config.max_cycles - 1)
            for cycle in range(self.config.start_cycle, stop_cycle + 1):
                while self._paused and not self._stopped:
                    self._sleep(0.05)
                if self._stopped:
                    return SimulationResult(tuple(sent), "stopped")
                response = self.transport.post(
                    self._url("/api/v1/predict"), json=self._payload(cycle),
                )
                response.raise_for_status()
                self._show(response.json())
                sent.append(cycle)
                if cycle < stop_cycle and self.config.mode == "real_time_simulated":
                    self._sleep(self.config.interval_seconds / self.config.speed)
            return SimulationResult(tuple(sent), "last_cycle")
        except KeyboardInterrupt:
            return SimulationResult(tuple(sent), "interrupted")
        except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            print(f"simulação interrompida: API indisponível ou resposta inválida ({exc})", file=self._output)
            return SimulationResult(tuple(sent), "api_unavailable")
        finally:
            close = getattr(self.transport, "close", None)
            if callable(close):
                close()


def _parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(description="Simulador local de telemetria FD001")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--unit-id", type=int, required=True)
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--model", default="fusion")
    parser.add_argument("--telemetry-policy", default="full")
    parser.add_argument("--cadence", default="each_cycle")
    parser.add_argument("--interval", dest="interval_seconds", type=float, default=1.0)
    parser.add_argument("--mode", choices=("real_time_simulated", "fast"), default="real_time_simulated")
    parser.add_argument("--speed", type=float, default=1.0, choices=(1.0, 2.0, 5.0))
    parser.add_argument("--start-cycle", type=int, default=1)
    parser.add_argument("--max-cycles", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = TelemetrySimulator(SimulationConfig(**vars(args))).run()
    except (ValueError, httpx.HTTPError) as exc:
        print(f"simulação não iniciada: {exc}", file=sys.stderr)
        return 2
    return 0 if result.stopped_reason in {"last_cycle", "stopped", "interrupted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

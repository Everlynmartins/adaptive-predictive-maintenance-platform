from __future__ import annotations

from io import StringIO

from predictive_maintenance.simulator.telemetry_producer import (
    SimulationConfig,
    TelemetrySimulator,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _Transport:
    def __init__(self, last_cycle: int = 3, fail_post: bool = False) -> None:
        self.last_cycle = last_cycle
        self.fail_post = fail_post
        self.posts: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        return _Response({"last_cycle": self.last_cycle})

    def post(self, url: str, **kwargs: object) -> _Response:
        if self.fail_post:
            raise RuntimeError("API down")
        payload = kwargs["json"]
        assert isinstance(payload, dict)
        self.posts.append((url, payload))
        return _Response({
            "cycle": payload["cycle"], "risk_score": 0.2,
            "alert_level": "normal", "prediction_status": "valid",
        })

    def close(self) -> None:
        return None


def _config(**overrides: object) -> SimulationConfig:
    values: dict[str, object] = {"unit_id": 7, "mode": "fast"}
    values.update(overrides)
    return SimulationConfig(**values)


def test_cycles_are_ordered_and_payload_has_no_future_data() -> None:
    transport = _Transport(last_cycle=3)
    result = TelemetrySimulator(_config(), transport=transport, output=StringIO()).run()

    assert result.cycles_sent == (1, 2, 3)
    assert [payload["cycle"] for _, payload in transport.posts] == [1, 2, 3]
    assert all(set(payload) == {
        "unit_id", "cycle", "horizon", "model", "telemetry_policy", "cadence",
    } for _, payload in transport.posts)
    assert all(payload["unit_id"] == 7 for _, payload in transport.posts)


def test_stops_at_last_cycle_without_delay_in_fast_mode() -> None:
    transport = _Transport(last_cycle=2)
    sleeps: list[float] = []
    result = TelemetrySimulator(_config(interval_seconds=4), transport=transport,
                                sleep=sleeps.append, output=StringIO()).run()

    assert result.stopped_reason == "last_cycle"
    assert len(transport.posts) == 2
    assert sleeps == []


def test_small_cycle_window_preserves_sequence_and_unit() -> None:
    transport = _Transport(last_cycle=20)
    result = TelemetrySimulator(
        _config(start_cycle=7, max_cycles=3), transport=transport, output=StringIO()
    ).run()

    assert result.cycles_sent == (7, 8, 9)
    assert [payload["cycle"] for _, payload in transport.posts] == [7, 8, 9]
    assert {payload["unit_id"] for _, payload in transport.posts} == {7}


def test_api_unavailable_is_reported_without_traceback() -> None:
    transport = _Transport(fail_post=True)
    output = StringIO()
    result = TelemetrySimulator(_config(), transport=transport, output=output).run()

    assert result.stopped_reason == "api_unavailable"
    assert "simulação interrompida" in output.getvalue()

from __future__ import annotations

import os
import sys
import types

from paperful.critique_ai_model import run_ai_model


def test_run_ai_model_stays_offline_when_weights_missing(monkeypatch):
    seen: dict[str, str | None] = {}

    class Boom:
        def __init__(self, *args, **kwargs):
            seen["hf"] = os.environ.get("HF_HUB_OFFLINE")
            seen["tf"] = os.environ.get("TRANSFORMERS_OFFLINE")
            raise OSError("offline: falcon-7b-instruct not found")

        def compute_score(self, text: str) -> float:
            raise AssertionError("should not score")

    fake = types.ModuleType("binoculars")
    fake.Binoculars = Boom
    monkeypatch.setitem(sys.modules, "binoculars", fake)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    assert run_ai_model("hello", timeout_s=0) is None
    assert seen["hf"] == "1"
    assert seen["tf"] == "1"
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ


def test_run_ai_model_returns_score(monkeypatch):
    class Ok:
        def __init__(self, *args, **kwargs):
            assert os.environ.get("HF_HUB_OFFLINE") == "1"

        def compute_score(self, text: str) -> float:
            return 0.42

    fake = types.ModuleType("binoculars")
    fake.Binoculars = Ok
    monkeypatch.setitem(sys.modules, "binoculars", fake)

    assert run_ai_model("hello", timeout_s=0) == {
        "backend": "binoculars",
        "score": 0.42,
    }


def test_run_ai_model_restores_prior_offline_env(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no")

        def compute_score(self, text: str) -> float:
            return 0.1

    fake = types.ModuleType("binoculars")
    fake.Binoculars = Boom
    monkeypatch.setitem(sys.modules, "binoculars", fake)

    assert run_ai_model("hello", timeout_s=0) is None
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "0"


def test_run_ai_model_timeout_terminates_child(monkeypatch):
    class FakeParent:
        def poll(self, timeout: float) -> bool:
            assert timeout == 0.05
            return False

        def recv(self) -> object:
            raise AssertionError("timed-out child must not be read")

        def close(self) -> None:
            return None

    class FakeChild:
        def close(self) -> None:
            return None

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.alive = True
            self.terminated = False

        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.terminated = True
            self.alive = False

        def kill(self) -> None:
            self.alive = False

        def join(self, timeout: float | None = None) -> None:
            self.alive = False

    class FakeCtx:
        def Pipe(self, duplex: bool = True):
            return FakeParent(), FakeChild()

        def Process(self, **kwargs):
            return FakeProc(**kwargs)

    monkeypatch.setattr(
        "paperful.critique_ai_model.multiprocessing.get_context",
        lambda _name: FakeCtx(),
    )
    monkeypatch.setattr(
        "paperful.critique_ai_model.importlib.util.find_spec",
        lambda _name: object(),
    )
    assert run_ai_model("hello", timeout_s=0.05) is None


def test_run_ai_model_recv_score_and_eof(monkeypatch):
    class Parent:
        def __init__(self, payload):
            self.payload = payload

        def poll(self, timeout: float) -> bool:
            return True

        def recv(self):
            if self.payload is EOFError:
                raise EOFError
            return self.payload

        def close(self) -> None:
            return None

    class Child:
        def close(self) -> None:
            return None

    class Proc:
        def __init__(self, *args, **kwargs):
            self.alive = False

        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            return None

    def install(payload):
        class Ctx:
            def Pipe(self, duplex: bool = True):
                return Parent(payload), Child()

            def Process(self, **kwargs):
                return Proc(**kwargs)

        monkeypatch.setattr(
            "paperful.critique_ai_model.multiprocessing.get_context",
            lambda _name: Ctx(),
        )
        monkeypatch.setattr(
            "paperful.critique_ai_model.importlib.util.find_spec",
            lambda _name: object(),
        )

    install({"backend": "binoculars", "score": 0.2})
    assert run_ai_model("hello", timeout_s=1) == {
        "backend": "binoculars",
        "score": 0.2,
    }
    install(EOFError)
    assert run_ai_model("hello", timeout_s=1) is None


def test_run_ai_model_missing_spec_is_none(monkeypatch):
    monkeypatch.delitem(sys.modules, "binoculars", raising=False)
    monkeypatch.setattr(
        "paperful.critique_ai_model.importlib.util.find_spec", lambda _n: None
    )
    assert run_ai_model("hello", timeout_s=5) is None

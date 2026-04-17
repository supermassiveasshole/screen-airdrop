"""Registry-backed factory for pluggable receiver pipelines."""

from __future__ import annotations

from screen_airdrop.receiver.pipeline.interfaces import PipelineFactoryProtocol
from screen_airdrop.receiver.runtime.live_factory import create_live_pipeline
from screen_airdrop.receiver.runtime.replay_factory import create_replay_pipeline
from screen_airdrop.receiver.runtime.simulated_live_factory import create_simulated_live_pipeline

_PIPELINE_FACTORIES: dict[str, PipelineFactoryProtocol] = {
    "live": create_live_pipeline,
    "replay": create_replay_pipeline,
    "simulated_live": create_simulated_live_pipeline,
}


def register_pipeline_factory(name: str, factory: PipelineFactoryProtocol) -> None:
    """Register or replace a named pipeline factory."""
    _PIPELINE_FACTORIES[str(name)] = factory


def get_pipeline_factory(name: str) -> PipelineFactoryProtocol:
    """Return the registered pipeline factory for a pipeline kind."""
    try:
        return _PIPELINE_FACTORIES[str(name)]
    except KeyError as exc:
        raise ValueError(f"Unknown pipeline kind: {name}") from exc


def create_registered_pipeline(name: str, /, **kwargs):
    """Instantiate a pipeline using the named registered factory."""
    factory = get_pipeline_factory(name)
    return factory(**kwargs)


def registered_pipeline_kinds():
    """Return registered pipeline kinds in deterministic order."""
    return tuple(sorted(_PIPELINE_FACTORIES))

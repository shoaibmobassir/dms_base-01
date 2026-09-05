"""Production architecture simulator for FirmOS document intelligence.

Simulates:
  async hierarchical ingest → immutable versions → content anchors
  → hybrid hierarchical retrieval → Map/Reduce/Verify review
"""
from architecture_sim.pipeline import PipelineResult, SimConfig, run_pipeline
from architecture_sim.store import FirmStore

__all__ = [
    "FirmStore",
    "PipelineResult",
    "SimConfig",
    "run_pipeline",
]

__version__ = "0.1.0"

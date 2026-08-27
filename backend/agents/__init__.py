"""Agent modules for the Tentoro Forge platform.

Agent roster:
  #0  Orchestrator  — intent classification (Haiku)
  #1  Planner       — structured plan output (Sonnet)
  #2  Refiner       — targeted code edits (Sonnet)
  #3  Explainer     — answers questions (Haiku)
  #4  Code Generator— full-stack app from description (Sonnet)
  #5  Code Editor   — single-file precision edits (Sonnet)
  #6  Scaffolder    — add feature to existing module (Sonnet)
  #7  Indexer       — produces app-model.json (Haiku)
  #8  Validator     — build check + iterative fix (Haiku)
  #9  Seed Generator— realistic seed data (Sonnet)
  #12 Discovery     — requirement discovery (Sonnet)
"""

from agents.orchestrator import classify_intent
from agents.planner import run_planner
from agents.refiner import run_refiner
from agents.explainer import run_explainer
from agents.code_generator import run_code_generator
from agents.code_editor import run_code_editor
from agents.scaffolder import run_scaffolder
from agents.indexer import run_indexer
from agents.validator import run_validator
from agents.seed_generator import run_seed_generator

__all__ = [
    "classify_intent",
    "run_planner",
    "run_refiner",
    "run_explainer",
    "run_code_generator",
    "run_code_editor",
    "run_scaffolder",
    "run_indexer",
    "run_validator",
    "run_seed_generator",
]

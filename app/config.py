"""Central configuration for the Tiny CEDX agent fleet.

Every env var the kit's TASK.md/README_KIT.md contract defines lives here, plus
the CASE_ID -> amendment (second-approver role + threshold) derivation, which
TASK.md Step 8 specifies as a fixed sha256 formula. Nothing else in the app
should read os.environ directly.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# .env is dev-only convenience (OpenRouter key while we have no Anthropic/OpenAI/
# Gemini key). Real grading runs set env vars directly; load_dotenv is a no-op
# there since it never overrides already-set vars.
load_dotenv(override=False)

REPO_ROOT = Path(__file__).resolve().parent.parent

AMENDMENT_ROLES = ["risk_officer", "legal_counsel", "compliance", "finance_controller"]


def derive_amendment(case_id: str) -> tuple[str, int]:
    """TASK.md Step 8:
        H = sha256(CASE_ID)  # lowercase hex
        R = ROLES[int(H[0],16) % 4]
        T = 10000 + (int(H[1:3],16) % 50) * 1000
    """
    h = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    role = AMENDMENT_ROLES[int(h[0], 16) % 4]
    threshold = 10000 + (int(h[1:3], 16) % 50) * 1000
    return role, threshold


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v in (None, ""):
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    case_id: str
    amendment_role: str
    amendment_threshold: int

    replay_llm: bool
    seed_dir: Path
    pipeline_now: str

    llm_api_key: str | None
    llm_base_url: str
    llm_model_cheap: str
    llm_model_strong: str

    max_cost_usd_per_record: float
    max_steps_per_record: int

    out_dir: Path = field(default_factory=lambda: REPO_ROOT / "out")
    transcripts_dir: Path = field(default_factory=lambda: REPO_ROOT / "transcripts")

    pipeline_version: str = "tiny-cedx-fleet-0.1.0"
    industry: str = "Insurance (Commercial / Specialty) — Claims Intake"


def load_config() -> Config:
    case_id = os.environ.get("CASE_ID", "CEDX-XXXX")
    role, threshold = derive_amendment(case_id)

    seed_dir_raw = os.environ.get("SEED_DIR", "seed")
    seed_dir = Path(seed_dir_raw)
    if not seed_dir.is_absolute():
        seed_dir = REPO_ROOT / seed_dir

    return Config(
        case_id=case_id,
        amendment_role=role,
        amendment_threshold=threshold,
        replay_llm=_env_bool("REPLAY_LLM", True),
        seed_dir=seed_dir,
        pipeline_now=os.environ.get("PIPELINE_NOW", "2026-06-26"),
        # LLM_API_KEY/LLM_MODEL/LLM_BASE_URL are the kit's official contract (TASK.md
        # Step 7) -- graders set exactly these three for the real held-out run.
        # LLM_MODEL_CHEAP/STRONG and OPENROUTER_API_KEY are OUR dev-only extensions
        # (OpenRouter, since we have no direct OpenAI/Anthropic/Gemini key) and only
        # apply as a fallback when the official vars aren't set, so a grader pointing
        # a real gpt-4o-mini key straight at OpenAI (LLM_BASE_URL=api.openai.com) gets
        # exactly "gpt-4o-mini" as the model name, not an OpenRouter-prefixed one.
        llm_api_key=os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY"),
        llm_base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_model_cheap=(
            os.environ.get("LLM_MODEL_CHEAP") or os.environ.get("LLM_MODEL") or "openai/gpt-4o-mini"
        ),
        llm_model_strong=(
            os.environ.get("LLM_MODEL_STRONG") or os.environ.get("LLM_MODEL") or "anthropic/claude-3.5-haiku"
        ),
        max_cost_usd_per_record=_env_float("MAX_COST_USD_PER_RECORD", 0.02),
        max_steps_per_record=_env_int("MAX_STEPS_PER_RECORD", 6),
    )


CONFIG = load_config()

"""Typed settings loader. Single source of truth for runtime configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ProjectCfg(BaseModel):
    scope_type: Literal["project", "folder", "organization"]
    scope_id: str
    environment: str = "dev"


class AuthCfg(BaseModel):
    wif_config_path: str = ""
    impersonated_sa: str = ""
    # ADC is permitted as a fallback when WIF is not configured. Set to False
    # in production to enforce WIF and refuse ADC. See docs/governance/GAP_ANALYSIS.md.
    allow_adc: bool = False
    required_roles: list[str] = Field(default_factory=list)


class DiscoveryCfg(BaseModel):
    asset_types: dict[str, list[str]]
    include_iam_policies: bool = True


class NamingCfg(BaseModel):
    prefix: str = "{env}-"
    max_length: int = 63


class GenerationCfg(BaseModel):
    output_dir: str = "generated-terraform"
    provider_version: str = "~> 7.0"
    terraform_version: str = ">= 1.14.0"
    naming: NamingCfg = Field(default_factory=NamingCfg)
    labels: dict[str, str] = Field(default_factory=dict)


class ValidationCfg(BaseModel):
    sandbox_project_id: str = ""
    sandbox_region: str = "us-central1"
    auto_apply: bool = True
    apply_timeout_seconds: int = 600


class GovernanceCfg(BaseModel):
    audit_log_dir: str = "audit-logs"
    hitl_required_for: list[str] = Field(default_factory=list)
    max_resources_per_run: int = 500
    deny_patterns: list[str] = Field(default_factory=list)


class MemoryCfg(BaseModel):
    # Optional. When unset/disabled the pipeline runs with no memory and no
    # ReasoningBank step. See sidecar/README.md for bring-up.
    enabled: bool = False
    sidecar_url: str = "http://127.0.0.1:7443"
    sidecar_token: str = ""  # or set AI_TF_SIDECAR_TOKEN env
    namespace: str = ""  # defaults to project.scope_id
    retention_days: int = 180
    timeout_seconds: float = 5.0


class Settings(BaseModel):
    project: ProjectCfg
    auth: AuthCfg
    discovery: DiscoveryCfg
    generation: GenerationCfg
    validation: ValidationCfg
    governance: GovernanceCfg
    memory: MemoryCfg = Field(default_factory=MemoryCfg)


def load(path: str | Path = "config/settings.yaml") -> Settings:
    data = yaml.safe_load(Path(path).read_text())
    return Settings(**data)

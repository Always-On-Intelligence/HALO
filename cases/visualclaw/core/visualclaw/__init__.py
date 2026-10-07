"""
VisualClaw — modular AI agent gateway with skill injection and RL training.

Quick start:
    visualclaw start    # launch the gateway on port 30100
    visualclaw setup    # interactive configuration wizard

New module-based API:
    from visualclaw.config import VisualClawConfig, load_config
    from visualclaw.gateway.app import create_app
    from visualclaw.modules.skill.manager import SkillManager
    from visualclaw.modules.rl.scorer import PRMScorer
"""

from .config import VisualClawConfig, load_config
from .config_store import ConfigStore

__all__ = [
    "VisualClawConfig",
    "load_config",
    "ConfigStore",
]

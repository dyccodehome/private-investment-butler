"""private_investment_butler 的初始化路径辅助。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS_DIR = PROJECT_ROOT / "frameworks"
SKILLS_DIR = PROJECT_ROOT / "skills"
RUNTIME_DIR = PROJECT_ROOT / "runtime"

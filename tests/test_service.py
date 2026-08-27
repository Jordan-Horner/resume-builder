from datetime import UTC, datetime, timedelta

from job_puller.config import InventoryConfig
from job_puller.database import InventoryDatabase
from job_puller.service import InventoryService


def config():
    return InventoryConfig.model_validate(
        {
            "search": {"families": [{"name": "backend", "titles": ["backend engineer"]}]},
            "providers": {
                "linkedin": {"enabled": True},
                "indeed": {"enabled": False},
                "greenhouse": {"enabled": False},
                "lever": {"enabled": False},
                "ashby": {"enabled": False},
                "smartrecruiters": {"enabled": False},
                "workday": {"enabled": False},
            },
        }
    )


def test_initial_cutoff_is_seven_days(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    service = InventoryService(config(), db)
    now = datetime(2026, 8, 27, tzinfo=UTC)
    assert service.cutoff("jobspy:linkedin", now) == now - timedelta(days=7)

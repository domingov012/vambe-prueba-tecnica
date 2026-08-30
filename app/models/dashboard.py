from datetime import datetime, timezone

from beanie import Document
from pydantic import Field

# Fixed _id for the single precomputed dashboard payload — there is only ever one
# "latest" blob, so a constant key makes reads/upserts trivial.
LATEST_KEY = "latest"


class DashboardInsights(Document):
    id: str = LATEST_KEY
    payload: dict
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "dashboard_insights"

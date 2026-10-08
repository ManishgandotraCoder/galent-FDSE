from typing import Literal

from pydantic import BaseModel, Field


class IntakeStatus(BaseModel):
    status: Literal["idle", "running", "done", "failed"] = "idle"
    uploaded: int = 0
    total: int = 0
    processed: int = 0
    accepted: int = 0
    rejected: int = 0
    current: str | None = None
    message: str = ""
    run_id: str | None = None
    file_ids: list[str] = Field(default_factory=list)

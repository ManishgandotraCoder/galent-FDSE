from pydantic import BaseModel, ConfigDict, Field


class FileSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    size: int
    type: str
    uploaded_at: str = Field(serialization_alias="uploadedAt")


class RejectedFile(BaseModel):
    name: str
    reason: str


class StoredFile(FileSummary):
    stored_name: str


class FileListResponse(BaseModel):
    files: list[FileSummary]
    limit: int
    added: list[FileSummary] | None = None
    rejected: list[RejectedFile] | None = None
    error: str | None = None


class SaveResult(BaseModel):
    files: list[FileSummary]
    added: list[FileSummary]
    rejected: list[RejectedFile]

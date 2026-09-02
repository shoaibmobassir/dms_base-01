from pydantic import BaseModel


class RetrieveRequest(BaseModel):
    query: str
    k: int = 20


class AskRequest(BaseModel):
    query: str
    k: int = 10


class ProjectCreate(BaseModel):
    title: str
    matter_id: str
    practice_team: str
    lead_member_id: str | None = None
    lead_lawyer: str | None = None
    deadline: str | None = None
    scope: str | None = None
    milestones: list[dict] | None = None


class ProjectMilestoneUpdate(BaseModel):
    milestone_index: int
    done: bool


class MilestoneToggleRequest(BaseModel):
    done: bool


class IngestDocumentRequest(BaseModel):
    title: str
    matter_id: str
    document_type: str = "Contract Draft"
    author_name: str | None = None
    body: str
    version: str = "v1.0"
    status: str = "Draft"


class IngestJobRequest(BaseModel):
    source_root: str
    manifest: str
    workers: int = 1
    run_immediately: bool = True


class FolderCreate(BaseModel):
    name: str
    parent_folder_id: str | None = None


class FolderUpdate(BaseModel):
    name: str | None = None
    parent_folder_id: str | None = None


class DocumentFolderMove(BaseModel):
    folder_id: str | None = None


class VersionCreate(BaseModel):
    body: str
    title: str | None = None
    author_name: str | None = None
    source: str = "edit"
    version_status: str = "developing"
    version_label: str | None = None


class DevelopingVersionRequest(BaseModel):
    author_name: str | None = None


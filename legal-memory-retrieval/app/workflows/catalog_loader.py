"""
Workflow Catalog Loader: Loads declarative YAML playbooks from disk.
Clean-room independent implementation.
"""

from pathlib import Path
from typing import Dict, List, Optional
import yaml

from app.workflows.engine import WorkflowDefinition, WorkflowStep


class WorkflowCatalogLoader:
    """Discovers and parses legal workflow playbooks."""

    def __init__(self, catalog_dir: Optional[Path] = None):
        self.catalog_dir = catalog_dir or Path(__file__).parent / "catalog"
        self.catalog_dir.mkdir(parents=True, exist_ok=True)

    def list_workflows(self) -> List[WorkflowDefinition]:
        workflows: List[WorkflowDefinition] = []
        for yaml_file in sorted(self.catalog_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if not data or "id" not in data:
                        continue
                    steps = [
                        WorkflowStep(
                            id=s["id"],
                            type=s["type"],
                            title=s.get("title"),
                            query=s.get("query"),
                            prompt=s.get("prompt"),
                            template=s.get("template"),
                            k=s.get("k", 5),
                        )
                        for s in data.get("steps", [])
                    ]
                    wf = WorkflowDefinition(
                        id=data["id"],
                        title=data.get("title", data["id"]),
                        description=data.get("description", ""),
                        category=data.get("category", "general"),
                        inputs=data.get("inputs", []),
                        steps=steps,
                    )
                    workflows.append(wf)
            except Exception as exc:
                continue
        return workflows

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        for wf in self.list_workflows():
            if wf.id == workflow_id:
                return wf
        return None


_catalog_loader: Optional[WorkflowCatalogLoader] = None


def get_catalog_loader() -> WorkflowCatalogLoader:
    global _catalog_loader
    if _catalog_loader is None:
        _catalog_loader = WorkflowCatalogLoader()
    return _catalog_loader

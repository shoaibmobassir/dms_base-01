"""
Workflow API Router: Endpoints for Legal Playbooks and Declarative AI Execution.
Clean-room independent implementation.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.workflows.catalog_loader import get_catalog_loader
from app.workflows.engine import get_workflow_engine

router = APIRouter(tags=["Legal Workflows"])

_RUNS_DB: Dict[str, Dict[str, Any]] = {}


class RunWorkflowRequest(BaseModel):
    workflow_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    provider: Optional[str] = None
    model: Optional[str] = None


@router.get("/health")
async def health():
    return {"status": "ok", "service": "legal_workflows"}


@router.get("/")
async def list_workflows():
    """Lists all available legal workflow playbooks."""
    loader = get_catalog_loader()
    wfs = loader.list_workflows()
    return [
        {
            "id": w.id,
            "title": w.title,
            "description": w.description,
            "category": w.category,
            "inputs": w.inputs,
            "step_count": len(w.steps),
        }
        for w in wfs
    ]


@router.get("/{workflow_id}")
async def get_workflow_details(workflow_id: str):
    """Retrieves full definition and step schema for a playbook."""
    loader = get_catalog_loader()
    wf = loader.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {
        "id": wf.id,
        "title": wf.title,
        "description": wf.description,
        "category": wf.category,
        "inputs": wf.inputs,
        "steps": [
            {
                "id": s.id,
                "type": s.type,
                "title": s.title,
                "query": s.query,
                "prompt": s.prompt,
            }
            for s in wf.steps
        ],
    }


@router.post("/run")
async def run_workflow(
    req: RunWorkflowRequest,
    x_member_id: Optional[str] = Header(None),
):
    """Executes a multi-step declarative legal playbook."""
    loader = get_catalog_loader()
    wf = loader.get_workflow(req.workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    engine = get_workflow_engine()
    res = await engine.run_workflow(
        workflow=wf,
        inputs=req.inputs,
        member_id=x_member_id,
        provider=req.provider,
        model=req.model,
    )

    run_dict = {
        "run_id": res.run_id,
        "workflow_id": res.workflow_id,
        "title": wf.title,
        "status": res.status,
        "inputs": res.inputs,
        "step_outputs": res.step_outputs,
        "final_output": res.final_output,
        "created_at": res.created_at,
        "member_id": x_member_id,
    }
    _RUNS_DB[res.run_id] = run_dict
    return run_dict


@router.get("/runs/{run_id}")
async def get_workflow_run(run_id: str):
    """Retrieves execution results and step outputs for a run."""
    if run_id not in _RUNS_DB:
        raise HTTPException(status_code=404, detail="Run not found")
    return _RUNS_DB[run_id]

"""
Workflow Engine: Declarative Multi-Step Legal Playbook Execution.
Clean-room independent implementation.
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional
import uuid
import jinja2

from app.db.connection import connect
from app.llm.model_router import LLMMessage, get_model_router
from app.retrieval.engine import retrieve

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    id: str
    type: str  # retrieve | ask | extract_entities | compose
    title: Optional[str] = None
    query: Optional[str] = None
    prompt: Optional[str] = None
    template: Optional[str] = None
    k: int = 5


@dataclass
class WorkflowDefinition:
    id: str
    title: str
    description: str
    category: str  # drafting | review | litigation | corporate
    inputs: List[Dict[str, Any]]
    steps: List[WorkflowStep]


@dataclass
class WorkflowRunResult:
    run_id: str
    workflow_id: str
    status: str  # completed | error | running
    inputs: Dict[str, Any]
    step_outputs: Dict[str, Any]
    final_output: str
    created_at: str


class WorkflowEngine:
    """Executes declarative legal playbooks step-by-step with state passing."""

    def __init__(self):
        self.router = get_model_router()
        self.jinja_env = jinja2.Environment(autoescape=False)

    def _render_template(self, tmpl_str: str, context: Dict[str, Any]) -> str:
        """Renders dynamic Jinja2 expressions safely."""
        if not tmpl_str:
            return ""
        try:
            tmpl = self.jinja_env.from_string(tmpl_str)
            return tmpl.render(**context)
        except Exception as exc:
            logger.warning("Template render warning: %s. Using raw string.", exc)
            return tmpl_str

    async def run_workflow(
        self,
        workflow: WorkflowDefinition,
        inputs: Dict[str, Any],
        member_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> WorkflowRunResult:
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        step_outputs: Dict[str, Any] = {}
        context: Dict[str, Any] = {"inputs": inputs, "steps": step_outputs}

        for step in workflow.steps:
            logger.info("Executing workflow step: %s (%s)", step.id, step.type)

            if step.type == "retrieve":
                # Render query with inputs and prior steps
                rendered_query = self._render_template(step.query or "", context)
                with connect() as conn:
                    hits, _ = retrieve(
                        conn,
                        query=rendered_query,
                        member_id=member_id,
                        k=step.k,
                    )
                hits_summary = "\n\n".join(
                    f"[{h.get('chunk_id', 'CHK-0')} - {h.get('title', '')}]: {h.get('snippet', h.get('text', ''))}"
                    for h in hits
                )
                step_outputs[step.id] = {
                    "query": rendered_query,
                    "hit_count": len(hits),
                    "chunk_ids": [h.get("chunk_id", f"CHK-{i}") for i, h in enumerate(hits)],
                    "hits_summary": hits_summary,
                }


            elif step.type == "ask":
                rendered_prompt = self._render_template(step.prompt or "", context)
                # Combine prior retrieved contexts
                evidence_blocks = [
                    v.get("hits_summary", "")
                    for v in step_outputs.values()
                    if isinstance(v, dict) and "hits_summary" in v
                ]
                combined_evidence = "\n\n".join(filter(None, evidence_blocks))

                system_msg = (
                    "You are FirmOS, a world-class legal AI partner at a top commercial law firm.\n"
                    "Provide precise, professional, and actionable legal analysis grounded strictly on the firm's evidence."
                )
                user_content = f"{rendered_prompt}\n\nInstitutional Evidence:\n{combined_evidence}"

                llm_resp = await self.router.complete(
                    messages=[
                        LLMMessage(role="system", content=system_msg),
                        LLMMessage(role="user", content=user_content),
                    ],
                    provider=provider,
                    model=model,
                )
                step_outputs[step.id] = {
                    "prompt": rendered_prompt,
                    "answer": llm_resp.content,
                    "model": llm_resp.model,
                }

            elif step.type == "extract_entities":
                rendered_prompt = self._render_template(step.prompt or "Extract key legal entities, dates, and covenants.", context)
                evidence_blocks = [
                    v.get("hits_summary", "")
                    for v in step_outputs.values()
                    if isinstance(v, dict) and "hits_summary" in v
                ]
                user_content = f"{rendered_prompt}\n\nEvidence:\n" + "\n\n".join(evidence_blocks)

                llm_resp = await self.router.complete(
                    messages=[
                        LLMMessage(role="system", content="Extract structured entities as JSON."),
                        LLMMessage(role="user", content=user_content),
                    ],
                    provider=provider,
                    model=model,
                    json_mode=True,
                )
                try:
                    step_outputs[step.id] = json.loads(llm_resp.content)
                except Exception:
                    step_outputs[step.id] = {"raw": llm_resp.content}

            elif step.type == "compose":
                rendered_output = self._render_template(step.template or "", context)
                step_outputs[step.id] = {"output": rendered_output}

            # Update context for subsequent steps
            context["steps"] = step_outputs

        # Determine final output (prefer compose step, else last ask step)
        final_text = ""
        for s_id, s_data in reversed(list(step_outputs.items())):
            if "output" in s_data:
                final_text = s_data["output"]
                break
            elif "answer" in s_data:
                final_text = s_data["answer"]
                break

        return WorkflowRunResult(
            run_id=run_id,
            workflow_id=workflow.id,
            status="completed",
            inputs=inputs,
            step_outputs=step_outputs,
            final_output=final_text,
            created_at=datetime.utcnow().isoformat(),
        )


_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine

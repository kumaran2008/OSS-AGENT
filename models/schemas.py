
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class RepositoryInfo(BaseModel):
    owner: str
    name: str
    full_name: str
    clone_url: str
    ssh_url: str
    default_branch: str
    description: Optional[str] = ""
    stargazers_count: int = 0
    language: Optional[str] = ""


class IssueInfo(BaseModel):
    number: int
    title: str
    body: str
    html_url: str
    repository_full_name: str
    labels: List[str] = []


class ImplementationPlan(BaseModel):
    summary: str
    files_to_modify: List[str] = []
    steps: List[str] = []


class ReviewResult(BaseModel):
    approved: bool
    feedback: str
    suggested_changes: Optional[str] = None
 

class ModelCallLog(BaseModel):
    task: str
    model_used: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    succeeded: bool = True
    error: Optional[str] = None


class RunLog(BaseModel):
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    repository: Optional[str] = None
    issue_number: Optional[int] = None
    issue_title: Optional[str] = None
    outcome: str = "in_progress"  # in_progress | pr_created | pushed_no_pr | aborted | failed
    dry_run: bool = False
    model_calls: List[ModelCallLog] = []
    test_pass: Optional[bool] = None
    review_approved: Optional[bool] = None
    debug_retries_used: int = 0
    notes: List[str] = []

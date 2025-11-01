from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ReviewState(BaseModel):
    # Existing fields
    user_input: str
    user_id: str
    slack_channel: str
    slack_thread_ts: Optional[str] = None
    
    repo_url: Optional[str] = None
    review_intent: Optional[str] = Field(default="deep_review")
    
    is_valid_repo: bool = False
    validation_error: Optional[str] = None
    ask_for_repo: bool = False
    
    issue_key: Optional[str] = None
    jira_created: bool = False
    
    repo_path: Optional[str] = None
    files_to_review: List[str] = []
    agent_status: str = "initialized"
    
    review_report: Optional[Dict[str, Any]] = None
    score: int = 0
    critical_issues: List[Dict[str, Any]] = []
    high_priority: List[Dict[str, Any]] = []
    
    error: Optional[str] = None
    
    # Add boolean flags to avoid dynamic attribute errors
    review_started: bool = False
    deep_reviewed: bool = False
    report_generated: bool = False
    jira_updated: bool = False
    slack_updated: bool = False
    
    class Config:
        arbitrary_types_allowed = True

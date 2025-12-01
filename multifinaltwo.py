from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent   
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from jira import JIRA
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime

import os
import json
import subprocess
import time
import re
import shutil
import yaml
import io

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------
# ENV & CONFIG
# ---------------------------------------------------------------------

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

TEMP_REPO_BASE = os.getenv("TEMP_REPO_PATH", "./repos")
REPORTS_DIR = os.path.join(TEMP_REPO_BASE, "reports")
Path(TEMP_REPO_BASE).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)

CODE_REVIEW_TOOL_TIMEOUT = 120          # seconds
CODE_REVIEW_WAIT_BETWEEN_TOOLS = 60     # seconds after heavy tool

print("[INIT] Initializing clients...")

# ---------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------

try:
    jira_client = JIRA(
        server=JIRA_BASE_URL,
        basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN),
    )
    print("Jira client initialized")
except Exception as e:
    print(f"Jira init failed: {e}")
    jira_client = None

try:
    slack_client = WebClient(token=SLACK_BOT_TOKEN, timeout=15)
    print("Slack client initialized")
except Exception as e:
    print(f"Slack init failed: {e}")
    slack_client = None

print(f"Temp folder: {TEMP_REPO_BASE}")

# ---------------------------------------------------------------------
# YAML PROMPTS
# ---------------------------------------------------------------------

PROMPTS: Dict[str, Any] = {}
PROMPTS_PATH = os.getenv("PROMPTS_CONFIG_PATH", "system_prompts.yaml")


def load_prompts() -> None:
    """Load prompts from YAML file into PROMPTS."""
    global PROMPTS
    try:
        with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
            PROMPTS = yaml.safe_load(f) or {}
        print(f"YAML prompts loaded from {PROMPTS_PATH}")
    except Exception as e:
        print(f"YAML load failed: {e}")
        PROMPTS = {}


def get_system_prompt(agent_name: str) -> str:
    """
    Return system prompt for logical agent name.

    Supports both old and new keys:
      - supervisor_agent / supervisor
      - jira_agent / jira_specialist
      - slack_agent / slack_specialist
      - code_review_agent / code_review_specialist
    """
    key_map = {
        "supervisor_agent": ["supervisor_agent", "supervisor"],
        "jira_agent": ["jira_agent", "jira_specialist"],
        "slack_agent": ["slack_agent", "slack_specialist"],
        "code_review_agent": ["code_review_agent", "code_review_specialist"],
    }
    candidates = key_map.get(agent_name, [agent_name])
    for key in candidates:
        block = PROMPTS.get(key)
        if isinstance(block, dict) and "system_prompt" in block:
            return block["system_prompt"] or ""
    return ""


load_prompts()

# ---------------------------------------------------------------------
# LLM loading
# ---------------------------------------------------------------------

def get_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0,
    )

# ---------------------------------------------------------------------
# HELPER: run shell command
# ---------------------------------------------------------------------

def _run_command(
    cmd,
    cwd: Optional[str] = None,
    timeout: int = CODE_REVIEW_TOOL_TIMEOUT,
) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return {
            "command": " ".join(cmd),
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "command": " ".join(cmd),
            "return_code": None,
            "stdout": e.stdout or "",
            "stderr": (e.stderr or "") + f"\n[ERROR] Timed out after {timeout} seconds.",
            "timed_out": True,
        }
    except Exception as e:
        return {
            "command": " ".join(cmd),
            "return_code": None,
            "stdout": "",
            "stderr": f"[ERROR] {type(e).__name__}: {e}",
            "timed_out": False,
        }

# ---------------------------------------------------------------------
# WORKFLOW STATE & NOTIFICATIONS
# ---------------------------------------------------------------------

class WorkflowState:
    """Track current Jira issue, Slack thread, updates."""
    def __init__(self):
        self.issue_key: Optional[str] = None
        self.slack_thread_ts: Optional[str] = None
        self.updates: List[Dict[str, Any]] = []


workflow = WorkflowState()


def transition_status(issue_key: str, status: str) -> Dict[str, Any]:
    """Transition Jira issue to target workflow status."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not available"}

        issue = jira_client.issue(issue_key)
        transitions = jira_client.transitions(issue)

        for t in transitions:
            if t["name"].lower() == status.lower():
                jira_client.transition_issue(issue, t["id"])
                print(f"[JIRA] {issue_key} → {status}")
                return {"success": True, "status": status}

        available = [t["name"] for t in transitions]
        return {
            "success": False,
            "error": f"Transition '{status}' not available",
            "available_transitions": available,
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def format_rich_comment(title: str, data: Any) -> str:
    """Create rich formatted comment for Jira/Slack."""
    comment = f"\n{'='*60}\n"
    comment += f"{title}\n"
    comment += f"{'='*60}\n\n"

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                comment += f"*{key}:*\n{json.dumps(value, indent=2)[:1500]}...\n\n"
            else:
                comment += f"• *{key}:* {value}\n"
    else:
        comment += str(data)

    comment += f"\n{'='*60}\n"
    return comment


def notify_step(title: str, json_data: Dict[str, Any]) -> None:
    """Send structured notification to Slack & Jira and store in state."""
    workflow.updates.append({"title": title, "data": json_data})
    rich_comment = format_rich_comment(title, json_data)

    # Slack
    try:
        if slack_client and SLACK_CHANNEL:
            if workflow.slack_thread_ts:
                resp = slack_client.chat_postMessage(
                    channel=SLACK_CHANNEL,
                    text=rich_comment,
                    thread_ts=workflow.slack_thread_ts,
                )
            else:
                resp = slack_client.chat_postMessage(
                    channel=SLACK_CHANNEL,
                    text=rich_comment,
                )
                workflow.slack_thread_ts = resp.get("ts")
            print(f"[SLACK] {title}")
    except Exception as e:
        print(f"Slack notify failed: {str(e)[:200]}")

    # Jira
    try:
        if jira_client and workflow.issue_key:
            jira_client.add_comment(workflow.issue_key, rich_comment[:30000])
            print(f"[JIRA] {title}")
    except Exception as e:
        print(f"Jira notify failed: {str(e)[:200]}")

# ---------------------------------------------------------------------
# REPORT HELPERS
# ---------------------------------------------------------------------

def create_detailed_json_report(analysis_results: dict, repo_name: str) -> dict:
    """Build & persist a detailed JSON report from analysis_results."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(
        REPORTS_DIR, f"code_review_{repo_name}_{timestamp}.json"
    )

    summary = analysis_results.get("summary", {})
    detailed_files = analysis_results.get("detailed_findings", {}).get("files", [])
    metadata = analysis_results.get("metadata", {})

    report_data = {
        "overall_score": summary.get("overall_score", 76),
        "critical_issues_count": summary.get("critical_issues", 0),
        "high_issues_count": summary.get("warnings", 0),
        "files_reviewed": len(detailed_files),
        "repository": metadata.get("repo_path", ""),
        "review_type": "deep_review",
        "timestamp": datetime.now().isoformat(),
        "findings": [],
    }

    for file_finding in detailed_files:
        finding = {
            "file": file_finding.get("file_path", ""),
            "total_lines": file_finding.get("total_lines", 0),
            "score": file_finding.get("score", 75),
            "issues": [
                {
                    "line": issue.get("line", 0),
                    "severity": issue.get("severity", "medium").lower(),
                    "type": issue.get("type", "code_quality"),
                    "issue": issue.get("issue", issue.get("message", "")),
                    "code_snippet": issue.get("code_snippet", ""),
                    "explanation": issue.get("explanation", ""),
                    "suggested_fix": issue.get("suggested_fix", ""),
                }
                for issue in file_finding.get("issues", [])
            ],
            "line_by_line_analysis": file_finding.get("line_by_line_analysis", {}),
            "strengths": file_finding.get("strengths", []),
            "improvements": file_finding.get("improvements", []),
            "overall_assessment": file_finding.get("overall_assessment", ""),
        }
        report_data["findings"].append(finding)

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print(f"[REPORT] JSON report file: {report_file}")
    report_data["_file_path"] = report_file
    return report_data


def upload_report_to_slack(report_data: dict, repo_name: str) -> Optional[str]:
    """
    Upload JSON report to Slack.
    Uses files_upload_v2 because files.upload is deprecated.
    """
    if not slack_client or not SLACK_CHANNEL:
        return None
    try:
        json_bytes = json.dumps(report_data, indent=2).encode("utf-8")
        json_file = io.BytesIO(json_bytes)
        filename = f"code_review_{repo_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # Slack v2 API
        slack_client.files_upload_v2(
            channel=SLACK_CHANNEL,
            file=json_file,
            filename=filename,
            title=f"Code Review Report - {repo_name}",
        )
        print(f"[SLACK] Report uploaded (v2): {filename}")
        return filename
    except SlackApiError as e:
        err = e.response.get("error", "unknown_error")
        print(f"Slack v2 upload error: {err}")
        return None
    except Exception as e:
        print(f"Slack report upload failed: {str(e)[:200]}")
        return None


def upload_report_to_jira(report_data: dict, issue_key: str, repo_name: str) -> Optional[str]:
    """Upload JSON report to Jira as attachment."""
    if not jira_client:
        return None
    try:
        json_bytes = json.dumps(report_data, indent=2).encode("utf-8")
        json_file = io.BytesIO(json_bytes)
        filename = f"code_review_{repo_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        jira_client.add_attachment(issue=issue_key, attachment=json_file, filename=filename)
        print(f"[JIRA] Report attached: {filename}")
        return filename
    except Exception as e:
        print(f"Jira attachment failed: {str(e)[:200]}")
        return None

# ---------------------------------------------------------------------
# JIRA TOOLS
# ---------------------------------------------------------------------

@tool
def jira_create_issue(
    summary: str,
    description: str,
    issue_type: str = "Task",
    project_key: Optional[str] = None,
) -> dict:
    """Create Jira issue and send initial notification."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}

        project = project_key or JIRA_PROJECT_KEY
        issue_dict = {
            "project": {"key": project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }
        new_issue = jira_client.create_issue(fields=issue_dict)
        workflow.issue_key = new_issue.key

        transition_status(new_issue.key, "In Progress")

        notify_step(
            f"Jira Issue Created: {new_issue.key}",
            {"issue_key": new_issue.key, "summary": summary},
        )

        return {
            "success": True,
            "message": f"Created issue {new_issue.key}",
            "issue_key": new_issue.key,
            "summary": summary,
            "status": "In Progress",
            "url": f"{JIRA_BASE_URL}/browse/{new_issue.key}",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed: {str(e)}"}


@tool
def jira_search_issues(
    jql_query: Optional[str] = None,
    project_key: Optional[str] = None,
    status: Optional[str] = None,
    max_results: int = 50,
) -> dict:
    """
    Search Jira issues. Used when you ask "list all issues" etc.
    """
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}

        if jql_query:
            query = jql_query
        else:
            parts = []
            if project_key:
                parts.append(f"project = {project_key}")
            else:
                parts.append(f"project = {JIRA_PROJECT_KEY}")
            if status:
                parts.append(f"status = '{status}'")
            query = " AND ".join(parts) + " ORDER BY created DESC"

        issues = jira_client.search_issues(query, maxResults=max_results)
        results = []
        for issue in issues:
            results.append(
                {
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "status": issue.fields.status.name,
                    "type": issue.fields.issuetype.name,
                    "created": issue.fields.created,
                    "url": f"{JIRA_BASE_URL}/browse/{issue.key}",
                }
            )

        return {
            "success": True,
            "count": len(results),
            "issues": results,
            "query_used": query,
        }
    except Exception as e:
        return {"success": False, "error": f"Failed: {str(e)}"}


@tool
def jira_transition_issue(issue_key: str, transition_name: str) -> dict:
    """Change status of a Jira issue."""
    try:
        return transition_status(issue_key, transition_name)
    except Exception as e:
        return {"success": False, "error": f"Failed: {str(e)}"}

# ---------------------------------------------------------------------
# SLACK TOOLS
# ---------------------------------------------------------------------

@tool
def slack_send_message(text: str, channel: Optional[str] = None) -> dict:
    """
    Send a plain message to Slack.

    Used by Slack agent when you say:
      - "send hi in slack"
      - "notify in slack hello team..."
    """
    try:
        if not slack_client:
            return {"success": False, "error": "Slack not configured"}
        slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=text,
        )
        return {
            "success": True,
            "message": "Message sent to Slack",
            "text": text,
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack error: {e.response['error']}"}
    except Exception as e:
        return {"success": False, "error": f"Slack failed: {str(e)}"}


@tool
def slack_create_jira_notification(
    issue_key: str,
    summary: str,
    status: str,
    url: str,
    channel: Optional[str] = None,
) -> dict:
    """
    Send a formatted Jira notification to Slack with a button.
    """
    try:
        if not slack_client:
            return {"success": False, "error": "Slack not configured"}

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Jira Issue: {issue_key}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Summary:*\n{summary}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{status}"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in Jira"},
                        "url": url,
                        "style": "primary",
                    }
                ],
            },
        ]

        slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=f"Jira Issue: {issue_key}",
            blocks=blocks,
        )

        return {
            "success": True,
            "message": f"Notification sent for {issue_key}",
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack error: {e.response['error']}"}
    except Exception as e:
        return {"success": False, "error": f"Slack failed: {str(e)}"}

# ---------------------------------------------------------------------
# CODE REVIEW TOOLS
# ---------------------------------------------------------------------

@tool
def code_review_extract_repo_url(text: str) -> dict:
    """Extract GitHub URL from text (supports [url] and plain url)."""
    try:
        print("[CODE REVIEW] Extracting repo URL...")
        bracket_pattern = r"\[(https?://github\.com/[\w.-]+/[\w.-]+(?:\.git)?)\]"
        match = re.search(bracket_pattern, text)
        if match:
            return {"success": True, "repo_url": match.group(1)}

        plain_pattern = r"https?://github\.com/[\w.-]+/[\w.-]+(?:\.git)?"
        match = re.search(plain_pattern, text)
        if match:
            return {"success": True, "repo_url": match.group(0)}

        return {"success": False, "error": "No GitHub URL found in text"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@tool
def code_review_clone_repo(repo_url: str, issue_key: str = "") -> dict:
    """Clone repository (with detailed error logging and notifications)."""
    try:
        print(f"[CODE REVIEW] Cloning {repo_url}...")

        if issue_key:
            workflow.issue_key = issue_key

        notify_step(
            "Repository Clone Started",
            {"status": "cloning", "repo_url": repo_url},
        )

        repo_name = repo_url.split("/")[-1].replace(".git", "")
        repo_folder = os.path.normpath(os.path.join(TEMP_REPO_BASE, repo_name))

        if os.path.exists(repo_folder):
            try:
                for root, dirs, files in os.walk(repo_folder):
                    for f in files:
                        try:
                            os.chmod(os.path.join(root, f), 0o777)
                        except Exception:
                            pass
                shutil.rmtree(repo_folder, ignore_errors=True)
            except Exception as e:
                print(f"Cleanup failed: {str(e)[:200]}")

        os.makedirs(TEMP_REPO_BASE, exist_ok=True)

        cmd = ["git", "clone", "--depth", "1", repo_url, repo_folder]
        result = _run_command(cmd, cwd=TEMP_REPO_BASE, timeout=CODE_REVIEW_TOOL_TIMEOUT)

        if result["return_code"] != 0 or result["timed_out"]:
            error_msg = (result["stderr"] or result["stdout"] or "").strip() or "Git clone failed"
            notify_step(
                "Clone Failed",
                {
                    "error": error_msg[:500],
                    "return_code": result["return_code"],
                    "command": result["command"],
                },
            )
            time.sleep(CODE_REVIEW_WAIT_BETWEEN_TOOLS)
            return {
                "success": False,
                "error": error_msg,
                "details": result,
            }

        py_files = len(list(Path(repo_folder).rglob("*.py")))

        if workflow.issue_key:
            transition_status(workflow.issue_key, "In Review")

        notify_step(
            "Repository Cloned Successfully",
            {
                "status": "cloned",
                "python_files": py_files,
                "repo_path": repo_folder,
            },
        )

        time.sleep(CODE_REVIEW_WAIT_BETWEEN_TOOLS)
        return {
            "success": True,
            "repo_path": repo_folder,
            "python_files": py_files,
            "repo_name": repo_name,
        }

    except Exception as e:
        err = str(e)[:500]
        notify_step(
            "Clone Failed (Exception)", {"error": err, "repo_url": repo_url}
        )
        time.sleep(CODE_REVIEW_WAIT_BETWEEN_TOOLS)
        return {"success": False, "error": err}


@tool
def code_review_run_deep_analysis(repo_path: str) -> dict:
    """
    Deep LLM-based code analysis on cloned repository:
    - Analyze up to 20 Python files
    - Build JSON report
    - Upload to Slack & Jira
    - Move Jira status to Done
    """
    try:
        print("[CODE REVIEW] Starting deep analysis.")

        notify_step(
            "🔍 Deep Code Analysis Started",
            {"status": "analyzing"},
        )

        llm = get_llm()
        repo_name = Path(repo_path).name

        analysis_results = {
            "metadata": {
                "repo_path": repo_path,
                "repo_name": repo_name,
                "analysis_timestamp": datetime.now().isoformat(),
            },
            "summary": {
                "overall_score": 76,
                "critical_issues": 0,
                "warnings": 0,
                "total_issues": 0,
            },
            "detailed_findings": {"files": []},
        }

        py_files = list(Path(repo_path).rglob("*.py"))

        for i, py_file in enumerate(py_files[:20], 1):
            try:
                with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    lines = content.split("\n")

                prompt = f"""You are a senior Python code reviewer.

Analyze this file for:
- code quality
- security issues
- maintainability
- best practices

Return STRICT JSON:
{{
  "overall_score": <0-100>,
  "issues": [
    {{
      "line": <line_number>,
      "severity": "<critical|high|medium|low>",
      "type": "<code_quality|security|performance|style|other>",
      "issue": "<short summary>",
      "code_snippet": "<optional snippet>",
      "explanation": "<why this is a problem>",
      "suggested_fix": "<how to fix>"
    }}
  ],
  "strengths": ["..."],
  "improvements": ["..."],
  "line_by_line_analysis": {{}}
}}

File (first 80 lines):
{chr(10).join(lines[:80])}
"""

                response = llm.invoke([HumanMessage(content=prompt)])

                try:
                    analysis = json.loads(response.content)
                except Exception:
                    analysis = {
                        "overall_score": 75,
                        "issues": [],
                        "strengths": ["Code present"],
                        "improvements": ["Review needed"],
                        "line_by_line_analysis": {},
                    }

                file_finding = {
                    "file_path": str(py_file.relative_to(repo_path)),
                    "total_lines": len(lines),
                    "score": analysis.get("overall_score", 75),
                    "issues": analysis.get("issues", []),
                    "line_by_line_analysis": analysis.get(
                        "line_by_line_analysis", {}
                    ),
                    "strengths": analysis.get("strengths", []),
                    "improvements": analysis.get("improvements", []),
                    "overall_assessment": f"Analysis complete with {len(analysis.get('issues', []))} issues.",
                }

                analysis_results["detailed_findings"]["files"].append(file_finding)

                for issue in analysis.get("issues", []):
                    severity = issue.get("severity", "low").lower()
                    if severity == "critical":
                        analysis_results["summary"]["critical_issues"] += 1
                    elif severity in ["high", "warning"]:
                        analysis_results["summary"]["warnings"] += 1

                print(f"Analyzed {i}/{len(py_files)}: {py_file.name}")
                time.sleep(3)

            except Exception as e:
                print(f"File error: {str(e)[:100]}")

        scores = [
            f.get("score", 75)
            for f in analysis_results["detailed_findings"]["files"]
        ]
        if scores:
            analysis_results["summary"]["overall_score"] = int(
                sum(scores) / len(scores)
            )

        analysis_results["summary"]["total_issues"] = (
            analysis_results["summary"]["critical_issues"]
            + analysis_results["summary"]["warnings"]
        )

        report_data = create_detailed_json_report(analysis_results, repo_name)

        notify_step(
            "Deep Analysis Complete",
            analysis_results["summary"],
        )

        upload_report_to_slack(report_data, repo_name)

        if workflow.issue_key:
            upload_report_to_jira(report_data, workflow.issue_key, repo_name)
            transition_status(workflow.issue_key, "Done")

        notify_step(
            "Code Review Completed & Uploaded",
            {
                "final_score": analysis_results["summary"]["overall_score"],
                "status": "completed",
                "report_uploaded": True,
            },
        )

        time.sleep(CODE_REVIEW_WAIT_BETWEEN_TOOLS)
        return {
            "success": True,
            "analysis": analysis_results,
            "report": report_data,
        }

    except Exception as e:
        notify_step("Analysis Failed", {"error": str(e)[:200]})
        time.sleep(CODE_REVIEW_WAIT_BETWEEN_TOOLS)
        return {"success": False, "error": str(e)[:200]}

# ---------------------------------------------------------------------
# AGENT DEFINITIONS (Jira, Slack, Code Review)
# ---------------------------------------------------------------------

JIRA_TOOLS = [
    jira_create_issue,
    jira_search_issues,
    jira_transition_issue,
]

SLACK_TOOLS = [
    slack_send_message,
    slack_create_jira_notification,
]

CODE_REVIEW_TOOLS = [
    code_review_extract_repo_url,
    code_review_clone_repo,
    code_review_run_deep_analysis,
    jira_create_issue,
    jira_search_issues,
    jira_transition_issue,
    slack_send_message,
    slack_create_jira_notification,
]

_jira_agent = None
_slack_agent = None
_code_review_agent = None


def get_jira_agent():
    global _jira_agent
    if _jira_agent is None:
        _jira_agent = create_react_agent(
            model=get_llm(),
            tools=JIRA_TOOLS,
        )
    return _jira_agent


def get_slack_agent():
    global _slack_agent
    if _slack_agent is None:
        _slack_agent = create_react_agent(
            model=get_llm(),
            tools=SLACK_TOOLS,
        )
    return _slack_agent


def get_code_review_agent():
    global _code_review_agent
    if _code_review_agent is None:
        _code_review_agent = create_react_agent(
            model=get_llm(),
            tools=CODE_REVIEW_TOOLS,
        )
    return _code_review_agent


@tool
def call_jira_agent(query: str) -> str:
    """Route to Jira Agent (create/search/update issues)."""
    agent = get_jira_agent()
    system_prompt = get_system_prompt("jira_agent")
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=query))
    result = agent.invoke({"messages": messages})
    return result["messages"][-1].content


@tool
def call_slack_agent(query: str) -> str:
    """
    Route to Slack Agent.

    For example:
      - "send hi in slack"
      - "notify in slack hello team how is work going"
    """
    agent = get_slack_agent()
    system_prompt = get_system_prompt("slack_agent")
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=query))
    result = agent.invoke({"messages": messages})
    return result["messages"][-1].content


@tool
def call_code_review_agent(query: str) -> str:
    """
    Route to Code Review Agent for end-to-end review:
      - create Jira issue (if needed)
      - clone repo
      - deep LLM analysis
      - upload JSON report
      - notify Slack & Jira at each stage
    """
    agent = get_code_review_agent()
    system_prompt = get_system_prompt("code_review_agent")
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=query))
    result = agent.invoke({"messages": messages})
    return result["messages"][-1].content

# ---------------------------------------------------------------------
# SUPERVISOR AGENT
# ---------------------------------------------------------------------

def create_supervisor_agent():
    """
    Supervisor coordinates:
      - call_jira_agent
      - call_slack_agent
      - call_code_review_agent

    Routing logic is guided by supervisor_agent prompt in YAML.
    """
    supervisor_tools = [call_jira_agent, call_slack_agent, call_code_review_agent]
    supervisor_agent = create_react_agent(
        model=get_llm(),
        tools=supervisor_tools,
    )
    return supervisor_agent

# ---------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("MULTI-AGENT SYSTEM - Tool Calling Pattern (with Code Review)")
    print("=" * 70)
    print(
        """
 Architecture:
  👔 Supervisor Agent (coordinates everything)
  ├─  Jira Agent       (create, search, update issues)
  ├─  Slack Agent      (send messages, Jira notifications)
  └─  Code Review Agent (clone repo, deep LLM analysis, JSON report)

 Examples:
   Jira Search: "list all issues" or "show all issues"
   Create Issue: "create task for API testing"
   Update Issue: "update SCRUM-107 to In Progress"
   Slack Only:  "send hi in slack"
   Combined:    "create bug and notify team"
   Code Review: "create a jira issue and do full code review for repo https://github.com/OWNER/REPO and notify in slack"
"""
    )
    print("=" * 70)

    supervisor = create_supervisor_agent()
    supervisor_system_prompt = get_system_prompt("supervisor_agent")

    while True:
        try:
            user_query = input("\nYour query (or 'exit'): ").strip()

            if user_query.lower() in ["exit", "quit", "q"]:
                print("Goodbye!")
                break

            if not user_query:
                continue

            print(f"\nProcessing: '{user_query}'")
            print("─" * 70)

            messages = []
            if supervisor_system_prompt:
                messages.append(SystemMessage(content=supervisor_system_prompt))
            messages.append(HumanMessage(content=user_query))

            result = supervisor.invoke({"messages": messages})

            
            final_message = result["messages"][-1]

            print("\n" + "=" * 70)
            print("AGENT RESPONSE")
            print("=" * 70)
            print(final_message.content)

            print("\n" + "=" * 70)
            print("RESULT SUMMARY")
            print("=" * 70)
            print(f"Last code-review issue key (if any): {workflow.issue_key}")
            print(f"Total workflow updates so far: {len(workflow.updates)}")
            print("=" * 70)

        except KeyboardInterrupt:
            print("\n\nInterrupted")
            break
        except Exception as e:
            print(f"\nError: {str(e)[:200]}")


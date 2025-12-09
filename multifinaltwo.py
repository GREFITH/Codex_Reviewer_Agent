from langchain_openai import AzureChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from jira import JIRA
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
import os
import json
import subprocess
import shutil
import re
import yaml
from dotenv import load_dotenv
import io
import time

load_dotenv()

# =====================================================================
# CONFIGURATION
# =====================================================================

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
TEMP_REPO_BASE = os.getenv("TEMP_REPO_PATH", r"./repos")
REPORTS_DIR = os.path.join(TEMP_REPO_BASE, "reports")
CODE_REVIEW_TOOL_LIST = os.getenv("CODE_REVIEW_TOOL_LIST", "")
CODE_REVIEW_TOOL_TIMEOUT = int(os.getenv("CODE_REVIEW_TOOL_TIMEOUT", "300"))
CODE_REVIEW_WAIT_BETWEEN_TOOLS = float(os.getenv("CODE_REVIEW_WAIT_BETWEEN_TOOLS", "0.5"))

# YAML Configuration File
YAML_CONFIG_FILE = "system_prompts.yaml"

Path(TEMP_REPO_BASE).mkdir(parents=True, exist_ok=True)
Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)

print("[INIT] Initializing patched v8.1 with external tool runner and report attachments...")

# =====================================================================
# YAML CONFIGURATION LOADER
# =====================================================================

class SystemPromptsConfig:
    """Load and manage system prompts from YAML configuration."""
    
    def __init__(self, config_file: str = YAML_CONFIG_FILE):
        """Load YAML configuration."""
        self.config_file = config_file
        self.config = {}
        self.load_config()
    
    def load_config(self):
        """Load YAML file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                print(f"Loaded system prompts from: {self.config_file}")
            else:
                print(f"Config file not found: {self.config_file}")
        except Exception as e:
            print(f"Failed to load YAML: {e}")
            self.config = {}
    
    def get_prompt(self, agent_name: str) -> str:
        """Get system prompt for agent."""
        if agent_name in self.config:
            agent_config = self.config[agent_name]
            if isinstance(agent_config, dict) and "system_prompt" in agent_config:
                return agent_config["system_prompt"]
        
        print(f"Prompt not found for {agent_name}, using default")
        return f"You are a {agent_name} agent. Use your tools effectively."
    
    def get_all_agents(self) -> List[str]:
        """Get all configured agent names."""
        agents = [key for key in self.config.keys() if isinstance(self.config[key], dict)]
        return agents

# Load configuration
prompts_config = SystemPromptsConfig(YAML_CONFIG_FILE)

print("[INIT] Initializing clients...")

# Clients
try:
    jira_client = JIRA(server=JIRA_BASE_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
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

# Workflow state
class WorkflowState:
    def __init__(self):
        self.slack_thread_ts: Optional[str] = None
        self.jira_issue_key: Optional[str] = None
        self.current_repo_path: Optional[str] = None
        self.report_file: Optional[str] = None  

workflow = WorkflowState()

# =====================================================================
# Utility helpers
# =====================================================================

def transition_status_local(issue_key: str, target_status: str) -> dict:
    """Local helper to transition Jira using jira_client directly (used inside tools)."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}
        issue = jira_client.issue(issue_key)
        transitions = jira_client.transitions(issue)
        for t in transitions:
            if t["name"].lower() == target_status.lower():
                jira_client.transition_issue(issue, t["id"])
                return {"success": True, "issue_key": issue_key, "new_status": t["name"]}
        for t in transitions:
            if target_status.lower() in t["name"].lower():
                jira_client.transition_issue(issue, t["id"])
                return {"success": True, "issue_key": issue_key, "new_status": t["name"]}
        return {"success": False, "error": f"Status '{target_status}' not found", "available_transitions": [t["name"] for t in transitions]}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

# =====================================================================
# LLM FACTORY
# =====================================================================

def get_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0,
    )

# =====================================================================
# GIT AGENT TOOLS
# =====================================================================

@tool
def git_execute_command(command: str, working_directory: str = ".") -> dict:
    """
    Execute ANY git command in specified directory.
    Args:
        command: Complete git command to execute
        working_directory: Where to run the command
    Returns:
        Dict with return_code, stdout, stderr
    """
    try:
        print(f"[GIT] Executing: {command}")
        os.makedirs(working_directory, exist_ok=True)
        
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        
        output = {
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command,
            "working_directory": working_directory,
        }
        
        if result.returncode == 0:
            print(f"Command successful")
        else:
            print(f"Command failed: {result.stderr[:100]}")
        
        return output
    except Exception as e:
        return {
            "return_code": 1,
            "stdout": "",
            "stderr": str(e),
            "command": command,
            "working_directory": working_directory,
        }

# =====================================================================
# External tool runner 
# =====================================================================

def run_external_tools(repo_path: str) -> List[Dict[str, Any]]:
    """
    Run external analysis tools defined via env CODE_REVIEW_TOOL_LIST.
    Format in .env: CODE_REVIEW_TOOL_LIST=flake8:flake8 --format=json .,bandit:bandit -r -f json .
    Each item is NAME:COMMAND (comma-separated). Commands run in repo_path.
    Returns list of results for each tool.
    """
    raw = CODE_REVIEW_TOOL_LIST
    if not raw:
        return []

    results = []
    items = [it.strip() for it in raw.split(",") if it.strip()]
    for item in items:
        if ":" not in item:
            continue
        name, cmd_str = item.split(":", 1)
        name = name.strip()
        cmd = cmd_str.strip()
        notify_text = f"Tool Started: {name} - `{cmd}`"
        # send a Slack/Jira notification about tool start
        try:
            slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=notify_text, thread_ts=workflow.slack_thread_ts)
        except Exception:
            pass
        print(f"[TOOLS] Running {name}: {cmd}")
        try:
            proc = subprocess.run(cmd, shell=True, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=CODE_REVIEW_TOOL_TIMEOUT)
            tool_report = {
                "tool": name,
                "command": cmd,
                "return_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as e:
            tool_report = {"tool": name, "command": cmd, "return_code": 1, "stdout": "", "stderr": str(e)}

        # Save per-tool report
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        tool_file = os.path.join(REPORTS_DIR, f"{os.path.basename(repo_path)}_{name}_report_{timestamp}.json")
        try:
            with open(tool_file, 'w', encoding='utf-8') as tf:
                json.dump(tool_report, tf, indent=2)
            print(f"[TOOLS] Saved report: {tool_file}")
        except Exception as e:
            print(f"[TOOLS] Failed to save report: {e}")

        # Attach to Jira and Slack if issue exists
        if workflow.jira_issue_key and jira_client:
            try:
                with open(tool_file, 'rb') as fh:
                    jira_client.add_attachment(issue=workflow.jira_issue_key, attachment=fh)
                jira_client.add_comment(workflow.jira_issue_key, f"{name} completed (rc={tool_report['return_code']})")
            except Exception as e:
                print(f"[TOOLS] Jira attach/comment failed: {e}")
        try:
            with open(tool_file, 'rb') as fh:
                slack_client.files_upload_v2(channel=SLACK_CHANNEL, file=fh, filename=os.path.basename(tool_file), title=f"{name} report", thread_ts=workflow.slack_thread_ts)
        except Exception:
            pass

        results.append({"tool": name, "report_file": tool_file, "result": tool_report})
        time.sleep(CODE_REVIEW_WAIT_BETWEEN_TOOLS)

    return results

# =====================================================================
# CODE REVIEW AGENT TOOLS
# =====================================================================

@tool
def code_review_analyze_repository(repository_path: str) -> dict:
    """
    Perform DEEP CODE ANALYSIS on given repository path.
    Returns: JSON report with findings
    """
    try:
        print(f"[CODE REVIEW] Starting analysis of: {repository_path}")
        
        if not os.path.exists(repository_path):
            return {
                "success": False,
                "report": None,
                "error": f"Path not found: {repository_path}",
            }
        
        workflow.current_repo_path = repository_path
        
        py_files = list(Path(repository_path).rglob("*.py"))[:50]
        
        if not py_files:
            return {
                "success": False,
                "report": None,
                "error": "No Python files found",
            }
        
        print(f"[CODE REVIEW] Found {len(py_files)} Python files to analyze")

        
        tool_results = run_external_tools(repository_path)

        file_contents = {}
        for py_file in py_files:
            try:
                with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    rel_path = str(py_file.relative_to(repository_path))
                    file_contents[rel_path] = content[:2000]
            except Exception as e:
                print(f"[WARNING] Failed to read {py_file}: {str(e)[:50]}")

        # Transition Jira to In Review now that analysis is starting
        if workflow.jira_issue_key:
            res = transition_status_local(workflow.jira_issue_key, "In Review")
            if not res.get("success"):
                print(f"Couldn't transition to In Review: {res.get('error')}")

        llm = get_llm()
        
        analysis_prompt = f"""Analyze these Python files and generate a comprehensive JSON report.

Files to analyze:
{json.dumps({k: f'<{len(v)} chars>' for k, v in file_contents.items()})}

For each file, analyze:
1. Code quality (0-100 score)
2. Security issues (if any)
3. Performance issues (if any)
4. Best practice violations (if any)
5. Line-by-line issues (line number, issue type, severity, fix suggestion)
6. Strengths (what's good about the code)
7. Improvements (recommendations)

Return ONLY a valid JSON object with this structure:
{{
  "metadata": {{"repository": "{repository_path}", "files_analyzed": {len(py_files)}, "analysis_timestamp": "", "analysis_tools": ["azure_llm"]}},
  "summary": {{"overall_score": 75, "files_with_issues": 2, "total_issues": 5, "critical_issues": 0, "high_issues": 1, "medium_issues": 2, "low_issues": 2, "recommendations": ["Use type hints", "Add error handling", "Improve logging"]}},
  "detailed_findings": [{{"file": "example.py", "score": 75, "issues": [{{"line": 10, "type": "quality", "severity": "medium", "message": "Long function", "fix": "Break into smaller functions"}}], "strengths": ["Good structure"], "improvements": ["Add comments"]}}]
}}

Analyze these file contents:
{json.dumps(file_contents)}

Return ONLY the JSON, no explanations."""
        
        print("[CODE REVIEW] Sending to LLM for analysis...")
        response = llm.invoke([HumanMessage(content=analysis_prompt)])
        
        json_match = re.search(r"\{.*\}", response.content, re.DOTALL)
        if not json_match:
            return {
                "success": False,
                "report": None,
                "error": "LLM did not return valid JSON",
            }
        
        report_json = json.loads(json_match.group())
        
        # Save report with timestamp
        report_file = os.path.join(
            REPORTS_DIR,
            f"code_review_{os.path.basename(repository_path)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_json, f, indent=2)
        
        # Store report file in workflow for later use
        workflow.report_file = report_file
        
        print(f"Analysis complete. Report saved: {report_file}")
        
        # Attach report to Jira (if available) and upload to Slack thread
        if workflow.jira_issue_key:
            try:
                res_attach = jira_attach_file_impl(workflow.jira_issue_key, report_file)
                if not res_attach.get("success"):
                    print(f"[WARN] jira_attach_file_impl failed: {res_attach.get('error')}")
            except Exception as e:
                print(f"[WARN] jira_attach_file_impl failed (exception): {e}")
        try:
            res_slack = slack_upload_file_impl(report_file, title=os.path.basename(report_file), channel=SLACK_CHANNEL)
            if not res_slack.get("success"):
                print(f"[WARN] slack_upload_file_impl failed: {res_slack.get('error')}")
        except Exception as e:
            print(f"[WARN] slack_upload_file_impl failed: {e}")

        # Transition to Done after attempting attachments
        if workflow.jira_issue_key:
            res_done = transition_status_local(workflow.jira_issue_key, "Done")
            if not res_done.get("success"):
                print(f"Couldn't transition to Done: {res_done.get('error')}")
            else:
                print(f"Issue {workflow.jira_issue_key} transitioned to Done")

        # Post a final Slack message in the thread summarizing completion
        try:
            if slack_client and SLACK_CHANNEL:
                slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=f":tada: Code review completed for {os.path.basename(repository_path)}. Report: {os.path.basename(report_file)}", thread_ts=workflow.slack_thread_ts)
        except Exception as e:
            print(f"[WARN] final slack notification failed: {e}")

        # Return success
        return {
            "success": True,
            "report": json.dumps(report_json),
            "report_file": report_file,
            "overall_score": report_json.get("summary", {}).get("overall_score", 0),
            "total_issues": report_json.get("summary", {}).get("total_issues", 0),
            "tool_results": tool_results,
        }
    
    except Exception as e:
        print(f"[ERROR] Analysis failed: {str(e)}")
        return {
            "success": False,
            "report": None,
            "error": str(e)[:200],
        }

# =====================================================================
# JIRA AGENT TOOLS 
# =====================================================================

@tool
def jira_create_issue(
    summary: str,
    description: str,
    issue_type: str = "Task",
    project_key: str = None,
) -> dict:
    """Create a Jira issue."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}
        
        project_key = os.getenv("JIRA_PROJECT_KEY")
        
        issue_dict = {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }
        
        new_issue = jira_client.create_issue(fields=issue_dict)
        workflow.jira_issue_key = new_issue.key
        
        print(f"Jira issue created: {new_issue.key}")
        
        return {
            "success": True,
            "issue_key": new_issue.key,
            "url": f"{JIRA_BASE_URL}/browse/{new_issue.key}",
        }
    
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

@tool
def jira_add_comment(issue_key: str, comment_text: str) -> dict:
    """Add comment to Jira issue."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}
        
        jira_client.add_comment(issue_key, comment_text)
        
        print(f"Comment added to {issue_key}")
        
        return {"success": True, "issue_key": issue_key}
    
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@tool
def jira_transition_issue(issue_key: str, target_status: str) -> dict:
    """Transition Jira issue to target status (DYNAMIC - NO HARDCODING)."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}
        
        issue = jira_client.issue(issue_key)
        transitions = jira_client.transitions(issue)
        
        print(f"[JIRA] Available transitions for {issue_key}:")
        for t in transitions:
            print(f" - {t['name']} (ID: {t['id']})")
        
       
        for t in transitions:
            if t["name"].lower() == target_status.lower():
                jira_client.transition_issue(issue, t["id"])
                print(f" {issue_key} transitioned to: {target_status}")
                return {
                    "success": True,
                    "issue_key": issue_key,
                    "new_status": target_status,
                }
        
        
        for t in transitions:
            if target_status.lower() in t["name"].lower():
                jira_client.transition_issue(issue, t["id"])
                print(f" {issue_key} transitioned to: {t['name']}")
                return {
                    "success": True,
                    "issue_key": issue_key,
                    "new_status": t['name'],
                }
        
        return {
            "success": False,
            "error": f"Status '{target_status}' not found",
            "available_transitions": [t["name"] for t in transitions],
        }
    
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def jira_attach_file_impl(issue_key: str, file_path: str, filename: str = None) -> dict:
    """Implementation: Attach file (JSON report) to Jira issue."""
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured"}
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        filename = filename or os.path.basename(file_path)
        with open(file_path, "rb") as f:
            # jira-python expects file-like for attachment
            jira_client.add_attachment(issue=issue_key, attachment=f)
        print(f"File attached to {issue_key}: {filename}")
        return {"success": True, "issue_key": issue_key, "filename": filename, "file_size": os.path.getsize(file_path)}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@tool
def jira_attach_file(issue_key: str, file_path: str, filename: str = None) -> dict:
    """Tool wrapper that calls implementation."""
    return jira_attach_file_impl(issue_key, file_path, filename)


@tool
def jira_search_issues(project: str = None, status: str = None) -> dict:
    """Search for issues in Jira project or fetch a single issue by key.

    Behavior improvements:
    - If `project` looks like a full issue key (contains a dash, e.g. SCRUM-150), try fetching that issue directly via jira_client.issue().
    - Otherwise, treat `project` as a project key and run a JQL query (project = KEY [AND status = '...']).
    - Returns a single-issue result when fetching by key.
    """
    try:
        if not jira_client:
            return {"success": False, "error": "Jira not configured", "issues": []}

        # Use project from env if not specified
        project = project or JIRA_PROJECT_KEY

        # If the caller passed a full issue key like SCRUM-150, fetch that single issue
        if project and isinstance(project, str) and "-" in project:
            issue_key = project.strip().upper()
            try:
                issue = jira_client.issue(issue_key)
                issue_entry = {
                    "key": issue.key,
                    "summary": getattr(issue.fields, "summary", ""),
                    "status": getattr(issue.fields.status, "name", ""),
                    "assignee": issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned",
                    "url": f"{JIRA_BASE_URL}/browse/{issue.key}",
                }
                return {"success": True, "issues": [issue_entry], "count": 1}
            except Exception as e:
                return {"success": False, "error": f"Issue not found: {issue_key} ({e})", "issues": []}

        # Otherwise build a JQL query for the project
        proj_key = project
        conditions = [f"project = {proj_key}"]
        if status:
            conditions.append(f"status = '{status}'")
        jql_query = " AND ".join(conditions)

        print(f"[JIRA] Executing JQL: {jql_query}")
        issues = jira_client.search_issues(jql_query, maxResults=200)

        issue_list = [
            {
                "key": issue.key,
                "summary": issue.fields.summary,
                "status": issue.fields.status.name,
                "assignee": issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned",
                "url": f"{JIRA_BASE_URL}/browse/{issue.key}",
            }
            for issue in issues
        ]

        print(f"Found {len(issue_list)} issues")
        return {"success": True, "issues": issue_list, "count": len(issue_list)}

    except Exception as e:
        return {"success": False, "error": str(e)[:200], "issues": []}

# ======================================================================
# SLACK AGENT TOOLS 
# =====================================================================

@tool
def slack_send_message(message_text: str, channel: str = None) -> dict:
    """Send text message to Slack."""
    try:
        if not slack_client:
            return {"success": False, "error": "Slack not configured"}
        
        channel = channel or SLACK_CHANNEL
        
        response = slack_client.chat_postMessage(
            channel=channel,
            text=message_text,
            thread_ts=workflow.slack_thread_ts,
        )
        
        workflow.slack_thread_ts = response.get("ts")
        
        print(f"Slack message sent")
        
        return {
            "success": True,
            "channel": channel,
            "thread_ts": workflow.slack_thread_ts,
        }
    
    except SlackApiError as e:
        return {"success": False, "error": f"Slack error: {e.response['error']}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def slack_upload_file_impl(
    file_path: str,
    title: str = None,
    channel: str = None,
) -> dict:
    """Implementation: Upload file (JSON report) to Slack channel. Attach into thread if workflow.slack_thread_ts is set."""
    try:
        if not slack_client:
            return {"success": False, "error": "Slack not configured"}
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        channel = channel or SLACK_CHANNEL
        filename = os.path.basename(file_path)
        title = title or filename
        with open(file_path, "rb") as f:
            upload_kwargs = {
                "channels": channel,
                "file": f,
                "filename": filename,
                "initial_comment": title,
            }
            # attach into thread if available
            if getattr(workflow, "slack_thread_ts", None):
                upload_kwargs["thread_ts"] = workflow.slack_thread_ts
            response = slack_client.files_upload(**upload_kwargs)
        print(f"File uploaded to Slack: {filename}")
        return {"success": True, "channel": channel, "filename": filename}
    except SlackApiError as e:
        return {"success": False, "error": f"Slack error: {e.response.get('error', 'unknown')}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@tool
def slack_upload_file(
    file_path: str,
    title: str = None,
    channel: str = None,
) -> dict:
    """Tool wrapper that calls implementation."""
    return slack_upload_file_impl(file_path, title=title, channel=channel)

# =====================================================================
# TOOL GROUPS
# =====================================================================

GIT_TOOLS = [git_execute_command]
CODE_REVIEW_TOOLS = [code_review_analyze_repository]
JIRA_TOOLS = [
    jira_create_issue,
    jira_add_comment,
    jira_transition_issue,
    jira_attach_file,
    jira_search_issues,
]
SLACK_TOOLS = [slack_send_message, slack_upload_file]

ALL_TOOLS = GIT_TOOLS + CODE_REVIEW_TOOLS + JIRA_TOOLS + SLACK_TOOLS

# =====================================================================
# AGENT FACTORY
# =====================================================================

def create_agent_executor(tools: list, agent_name: str) -> AgentExecutor:
    """Create agent executor with YAML system prompt."""
    try:
        llm = get_llm()
        
        # Get prompt from YAML
        system_prompt = prompts_config.get_prompt(agent_name)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        agent = create_openai_tools_agent(llm, tools, prompt)
        
        return AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=10,
            early_stopping_method="force",
            handle_parsing_errors=True,
        )
    except Exception as e:
        print(f"[ERROR] Agent creation failed for {agent_name}: {e}")
        return None

# =====================================================================
# MAIN
# =====================================================================

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("MULTI-AGENT SYSTEM v8.1 PATCHED - TOOL RUNNER & REPORT ATTACHMENTS")
    print("=" * 80)

    print(f"\nLoaded agents from YAML config:")
    for agent in prompts_config.get_all_agents():
        print(f"{agent}")

    supervisor = create_agent_executor(ALL_TOOLS, "orchestrator_supervisor")

    if supervisor is None:
        print("[ERROR] Failed to create supervisor agent")
        exit(1)

    print("\nSupervisor agent created successfully with YAML prompts\n")

    while True:
        try:
            user_query = input("Your query (or 'exit'): ").strip()
            if user_query.lower() in ["exit", "quit", "q"]:
                print("Goodbye!")
                break
            if not user_query:
                continue

            print(f"\nProcessing: '{user_query}'")
            print("─" * 80)

            result = supervisor.invoke({"input": user_query})

            print("\n" + "=" * 80)
            print("RESPONSE")
            print("=" * 80)
            
            output = result.get("output", "No output")
            print(output)
            
            print("\n" + "=" * 80)

        except KeyboardInterrupt:
            print("\n\nInterrupted")
            break
        except Exception as e:
            print(f"\nError: {str(e)[:200]}")

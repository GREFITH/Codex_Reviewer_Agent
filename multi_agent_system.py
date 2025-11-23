"""
Multi-Agent System with Tool Calling Pattern
Clean, simple prompts to avoid content filtering
"""

from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from jira import JIRA
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

#########################
##### Configuration #####
#########################

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

# Initialize clients
jira_client = JIRA(server=JIRA_BASE_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
slack_client = WebClient(token=SLACK_BOT_TOKEN)

###################
##### Helpers #####
###################

def get_llm():
    """Initialize Azure OpenAI LLM"""
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0
    )

###########################
##### Jira Tools #####
###########################

@tool
def jira_create_issue(
    summary: str,
    description: str,
    issue_type: str = "Task",
    project_key: Optional[str] = None
) -> dict:
    """
    Create a new Jira issue.
    
    Args:
        summary: The title/summary of the issue
        description: Detailed description of the issue
        issue_type: Type of issue (Task, Bug, Story, Epic). Defaults to Task
        project_key: Project key (optional, uses default from config)
    
    Returns:
        dict with success status, issue_key, summary, status, and url
    """
    try:
        project = project_key or JIRA_PROJECT_KEY
        issue_dict = {
            "project": {"key": project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type}
        }
        new_issue = jira_client.create_issue(fields=issue_dict)
        return {
            "success": True,
            "message": f"Created issue {new_issue.key}",
            "issue_key": new_issue.key,
            "summary": summary,
            "status": "To Do",
            "url": f"{JIRA_BASE_URL}/browse/{new_issue.key}"
        }
    except Exception as e:
        return {"success": False, "error": f"Failed: {str(e)}"}

@tool
def jira_search_issues(
    jql_query: Optional[str] = None,
    project_key: Optional[str] = None,
    status: Optional[str] = None,
    max_results: int = 50
) -> dict:
    """
    Search for Jira issues. Can search all issues or filter by status.
    
    Args:
        jql_query: Custom JQL query (optional)
        project_key: Filter by project key (optional)
        status: Filter by status like "To Do", "In Progress", "Done" (optional)
        max_results: Maximum results to return (default 50)
    
    Returns:
        dict with success status, count, and list of issues with key, summary, status, url
    
    Examples:
        - To get all issues: jira_search_issues()
        - To get issues by status: jira_search_issues(status="To Do")
        - To get all done issues: jira_search_issues(status="Done")
    """
    try:
        if jql_query:
            query = jql_query
        else:
            query_parts = []
            if project_key:
                query_parts.append(f"project = {project_key}")
            else:
                query_parts.append(f"project = {JIRA_PROJECT_KEY}")
            
            if status:
                query_parts.append(f"status = '{status}'")
            
            # Order by created date descending (newest first)
            query = " AND ".join(query_parts) if query_parts else f"project = {JIRA_PROJECT_KEY}"
            query += " ORDER BY created DESC"
        
        issues = jira_client.search_issues(query, maxResults=max_results)
        
        results = []
        for issue in issues:
            results.append({
                "key": issue.key,
                "summary": issue.fields.summary,
                "status": issue.fields.status.name,
                "type": issue.fields.issuetype.name,
                "created": issue.fields.created,
                "url": f"{JIRA_BASE_URL}/browse/{issue.key}"
            })
        
        return {
            "success": True,
            "count": len(results),
            "issues": results,
            "query_used": query
        }
    except Exception as e:
        return {"success": False, "error": f"Failed: {str(e)}"}

@tool
def jira_transition_issue(issue_key: str, transition_name: str) -> dict:
    """
    Change status of a Jira issue.
    
    Args:
        issue_key: Issue key (e.g., SCRUM-123)
        transition_name: Target status (To Do, In Progress, Done)
    
    Returns:
        dict with success status, issue_key, summary, new_status, and url
    """
    try:
        issue = jira_client.issue(issue_key)
        transitions = jira_client.transitions(issue)
        
        transition_id = None
        for t in transitions:
            if t['name'].lower() == transition_name.lower():
                transition_id = t['id']
                break
        
        if not transition_id:
            available = [t['name'] for t in transitions]
            return {
                "success": False,
                "error": f"Transition '{transition_name}' not available",
                "available_transitions": available
            }
        
        jira_client.transition_issue(issue, transition_id)
        updated_issue = jira_client.issue(issue_key)
        
        return {
            "success": True,
            "message": f"Transitioned {issue_key} to {transition_name}",
            "issue_key": issue_key,
            "summary": updated_issue.fields.summary,
            "new_status": transition_name,
            "url": f"{JIRA_BASE_URL}/browse/{issue_key}"
        }
    except Exception as e:
        return {"success": False, "error": f"Failed: {str(e)}"}

###########################
##### Slack Tools #####
###########################

@tool
def slack_send_message(text: str, channel: Optional[str] = None) -> dict:
    """
    Send a message to Slack.
    
    Args:
        text: Message text to send
        channel: Channel ID (optional, uses default)
    
    Returns:
        dict with success status and message
    """
    try:
        response = slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=text
        )
        return {
            "success": True,
            "message": "Message sent to Slack",
            "text": text
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack error: {e.response['error']}"}

@tool
def slack_create_jira_notification(
    issue_key: str,
    summary: str,
    status: str,
    url: str,
    channel: Optional[str] = None
) -> dict:
    """
    Send a formatted Jira notification to Slack.
    
    Args:
        issue_key: Jira issue key (e.g., SCRUM-123)
        summary: Issue summary
        status: Current status
        url: URL to the issue
        channel: Channel ID (optional)
    
    Returns:
        dict with success status and message
    """
    try:
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🎫 Jira Issue: {issue_key}"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Summary:*\n{summary}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{status}"}
                ]
            },
            {
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Jira"},
                    "url": url,
                    "style": "primary"
                }]
            }
        ]
        
        response = slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=f"Jira Issue: {issue_key}",
            blocks=blocks
        )
        
        return {
            "success": True,
            "message": f"Notification sent for {issue_key}"
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack error: {e.response['error']}"}

###########################
##### Sub-Agents as Tools #####
###########################

# Tool lists
JIRA_TOOLS = [
    jira_create_issue,
    jira_search_issues,
    jira_transition_issue
]

SLACK_TOOLS = [
    slack_send_message,
    slack_create_jira_notification
]

# ⭐ AGENTS CREATED LAZILY (only when needed)
_jira_agent = None
_slack_agent = None

def get_jira_agent():
    """Get or create Jira agent"""
    global _jira_agent
    if _jira_agent is None:
        _jira_agent = create_react_agent(
            model=get_llm(),
            tools=JIRA_TOOLS
        )
    return _jira_agent

def get_slack_agent():
    """Get or create Slack agent"""
    global _slack_agent
    if _slack_agent is None:
        _slack_agent = create_react_agent(
            model=get_llm(),
            tools=SLACK_TOOLS
        )
    return _slack_agent

@tool
def call_jira_agent(query: str) -> str:
    """
    Handle Jira tasks: create, search, or update issues.
    
    Args:
        query: The Jira task description
    
    Returns:
        str with result details
    """
    # 🔧 PROMPT MODIFICATION POINT #1
    # Modify query here to change Jira agent behavior
    # Example: enhanced_query = f"Be concise. {query}"
    
    agent = get_jira_agent()
    result = agent.invoke({"messages": [HumanMessage(content=query)]})
    return result["messages"][-1].content

@tool
def call_slack_agent(query: str) -> str:
    """
    Handle Slack tasks: send messages or notifications.
    
    Args:
        query: The Slack task description
    
    Returns:
        str with result confirmation
    """
    # 🔧 PROMPT MODIFICATION POINT #2
    # Modify query here to change Slack agent behavior
    
    agent = get_slack_agent()
    result = agent.invoke({"messages": [HumanMessage(content=query)]})
    return result["messages"][-1].content

###########################
##### Supervisor Agent #####
###########################

def create_supervisor_agent():
    """Create supervisor that coordinates Jira and Slack agents"""
    supervisor_tools = [call_jira_agent, call_slack_agent]
    
    supervisor_agent = create_react_agent(
        model=get_llm(),
        tools=supervisor_tools
    )
    
    return supervisor_agent

################
##### Main #####
################

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🤖 MULTI-AGENT SYSTEM - Tool Calling Pattern")
    print("="*70)
    print("""
✨ Architecture:
  👔 Supervisor Agent (coordinates everything)
  ├─ 🎫 Jira Agent (create, search, update issues)
  └─ 💬 Slack Agent (send messages, notifications)

✅ Examples:
  📋 Search: "list all jira issues" or "show all issues"
  ➕ Create: "create task for API testing"
  🔄 Update: "update SCRUM-107 to In Progress"
  💬 Slack: "send hello to slack"
  🔗 Combined: "create bug and notify team"
    """)
    print("="*70)
    
    supervisor = create_supervisor_agent()
    
    while True:
        user_query = input("\n💭 Your query (or 'exit'): ").strip()
        
        if user_query.lower() in ['exit', 'quit', 'q']:
            print("👋 Goodbye!")
            break
        
        if not user_query:
            continue
        
        print(f"\n🚀 Processing: '{user_query}'")
        print("─" * 70)
        
        try:
            # 🔧 PROMPT MODIFICATION POINT #3
            # Modify user_query here to change supervisor behavior globally
            # Example: enhanced_query = f"Be brief. {user_query}"
            
            result = supervisor.invoke({"messages": [HumanMessage(content=user_query)]})
            
            final_message = result["messages"][-1]
            
            print("\n" + "="*70)
            print("✅ RESULT:")
            print("="*70)
            print(final_message.content)
            print("\n" + "="*70)
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()

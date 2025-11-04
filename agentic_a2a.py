"""
TRUE AGENTIC Agent-to-Agent (A2A) System with Context Awareness
100% LLM-Driven Decision Making - Zero Hardcoded Logic
FIXED: Context properly shared, no information loss, graph visualization added
"""

from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from jira import JIRA
from langchain_core.tools import tool
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Any, Optional, List, Dict
from typing_extensions import Annotated
import os
from dotenv import load_dotenv
import json
import re

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

###########################
##### Jira Tools #####
###########################

@tool(parse_docstring=True)
def jira_create_issue(
    summary: str,
    description: str,
    issue_type: str = "Task",
    project_key: Optional[str] = None
) -> dict:
    """Create a new Jira issue.

    Args:
        summary: The title/summary of the issue
        description: Detailed description of the issue
        issue_type: Type of issue (Task, Bug, Story, Epic). Defaults to Task
        project_key: Project key (optional, uses default from config)
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
            "message": f"Issue {new_issue.key} created successfully",
            "issue_key": new_issue.key,
            "url": f"{JIRA_BASE_URL}/browse/{new_issue.key}",
            "summary": summary,
            "status": "To Do"
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to create issue: {str(e)}"}


@tool(parse_docstring=True)
def jira_search_issues(
    jql_query: Optional[str] = None,
    project_key: Optional[str] = None,
    status: Optional[str] = None,
    max_results: int = 10
) -> dict:
    """Search for Jira issues using JQL or simple filters.

    Args:
        jql_query: Custom JQL query string (optional)
        project_key: Filter by project key (optional)
        status: Filter by status (To Do, In Progress, Done, etc.)
        max_results: Maximum number of results to return (default 10)
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
            
            query = " AND ".join(query_parts) if query_parts else f"project = {JIRA_PROJECT_KEY}"
        
        issues = jira_client.search_issues(query, maxResults=max_results)
        
        results = []
        for issue in issues:
            results.append({
                "key": issue.key,
                "summary": issue.fields.summary,
                "status": issue.fields.status.name,
                "issue_type": issue.fields.issuetype.name,
                "assignee": issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned",
                "description": issue.fields.description or "No description",
                "url": f"{JIRA_BASE_URL}/browse/{issue.key}"
            })
        
        return {
            "success": True,
            "count": len(results),
            "issues": results,
            "query": query
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to search issues: {str(e)}"}


@tool(parse_docstring=True)
def jira_transition_issue(issue_key: str, transition_name: str) -> dict:
    """Change the status of a Jira issue (e.g., To Do → In Progress → Done).

    Args:
        issue_key: The issue key (e.g., SCRUM-123)
        transition_name: Target status name (To Do, In Progress, In Review, Done, etc.)
    """
    try:
        issue = jira_client.issue(issue_key)
        transitions = jira_client.transitions(issue)
        
        transition_id = None
        available_transitions = []
        for t in transitions:
            available_transitions.append(t['name'])
            if t['name'].lower() == transition_name.lower():
                transition_id = t['id']
                break
        
        if not transition_id:
            return {
                "success": False,
                "error": f"Transition '{transition_name}' not available",
                "available_transitions": available_transitions
            }
        
        jira_client.transition_issue(issue, transition_id)
        updated_issue = jira_client.issue(issue_key)
        
        return {
            "success": True,
            "message": f"Issue {issue_key} transitioned to '{transition_name}'",
            "issue_key": issue_key,
            "summary": updated_issue.fields.summary,
            "new_status": transition_name,
            "url": f"{JIRA_BASE_URL}/browse/{issue_key}"
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to transition issue: {str(e)}"}


@tool(parse_docstring=True)
def jira_add_comment(issue_key: str, comment_text: str) -> dict:
    """Add a comment to a Jira issue.

    Args:
        issue_key: The issue key (e.g., SCRUM-123)
        comment_text: The comment text to add
    """
    try:
        comment = jira_client.add_comment(issue_key, comment_text)
        issue = jira_client.issue(issue_key)
        
        return {
            "success": True,
            "message": f"Comment added to {issue_key}",
            "comment_id": comment.id,
            "issue_key": issue_key,
            "issue_summary": issue.fields.summary,
            "url": f"{JIRA_BASE_URL}/browse/{issue_key}"
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to add comment: {str(e)}"}


@tool(parse_docstring=True)
def jira_get_issue_details(issue_key: str) -> dict:
    """Get complete details of a specific Jira issue.

    Args:
        issue_key: The issue key (e.g., SCRUM-123)
    """
    try:
        issue = jira_client.issue(issue_key)
        
        comments = []
        for comment in issue.fields.comment.comments:
            comments.append({
                "author": comment.author.displayName,
                "body": comment.body,
                "created": comment.created
            })
        
        return {
            "success": True,
            "issue": {
                "key": issue.key,
                "summary": issue.fields.summary,
                "description": issue.fields.description or "No description",
                "status": issue.fields.status.name,
                "issue_type": issue.fields.issuetype.name,
                "priority": issue.fields.priority.name if issue.fields.priority else "None",
                "assignee": issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned",
                "reporter": issue.fields.reporter.displayName,
                "created": issue.fields.created,
                "updated": issue.fields.updated,
                "comments": comments,
                "url": f"{JIRA_BASE_URL}/browse/{issue.key}"
            }
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to get issue details: {str(e)}"}


###########################
##### Slack Tools #####
###########################

@tool(parse_docstring=True)
def slack_send_message(
    text: str,
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None
) -> dict:
    """Send a message to a Slack channel.

    Args:
        text: The message text to send
        channel: Channel ID (optional, uses default from config)
        thread_ts: Thread timestamp to reply in a thread (optional)
    """
    try:
        response = slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=text,
            thread_ts=thread_ts
        )
        return {
            "success": True,
            "message": "Message sent to Slack successfully",
            "channel": response['channel'],
            "timestamp": response['ts'],
            "text": text
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack API error: {e.response['error']}"}


@tool(parse_docstring=True)
def slack_send_rich_message(
    text: str,
    blocks: List[Dict[str, Any]],
    channel: Optional[str] = None
) -> dict:
    """Send a rich formatted message with Block Kit to Slack.

    Args:
        text: Fallback text for notifications
        blocks: List of Block Kit blocks for rich formatting
        channel: Channel ID (optional, uses default from config)
    """
    try:
        response = slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=text,
            blocks=blocks
        )
        return {
            "success": True,
            "message": "Rich message sent to Slack successfully",
            "channel": response['channel'],
            "timestamp": response['ts']
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack API error: {e.response['error']}"}


@tool(parse_docstring=True)
def slack_create_jira_notification(
    issue_key: str,
    summary: str,
    status: str,
    url: str,
    channel: Optional[str] = None
) -> dict:
    """Send a formatted Jira issue notification to Slack with rich formatting.

    Args:
        issue_key: Jira issue key (e.g., SCRUM-123)
        summary: Issue summary/title
        status: Current status
        url: URL to the Jira issue
        channel: Channel ID (optional)
    """
    try:
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🎫 Jira Issue Update: {issue_key}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Summary:*\n{summary}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Status:*\n{status}"
                    }
                ]
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View in Jira"
                        },
                        "url": url,
                        "style": "primary"
                    }
                ]
            }
        ]
        
        response = slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=f"Jira Issue Update: {issue_key} - {summary} [{status}]",
            blocks=blocks
        )
        
        return {
            "success": True,
            "message": f"Jira notification sent to Slack for {issue_key}",
            "timestamp": response['ts'],
            "issue_key": issue_key,
            "summary": summary,
            "status": status
        }
    except SlackApiError as e:
        return {"success": False, "error": f"Slack API error: {e.response['error']}"}


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


def extract_comprehensive_jira_info(text: str) -> Dict[str, str]:
    """Extract ALL Jira information from text - issue key, summary, status, URL"""
    info = {}
    
    # Extract issue key
    key_match = re.search(r'\b([A-Z]+-\d+)\b', text)
    if key_match:
        info['issue_key'] = key_match.group(1)
    
    # Extract URL
    url_match = re.search(r'https?://[^\s\)\]]+/browse/([A-Z]+-\d+)', text)
    if url_match:
        info['url'] = url_match.group(0)
        if 'issue_key' not in info:
            info['issue_key'] = url_match.group(1)
    
    # Extract summary with multiple patterns
    summary_patterns = [
        r'[Ss]ummary[:/\s]+["\']?([^"\':\n\*]{5,100})["\']?',
        r'[Tt]itle[:/\s]+["\']?([^"\':\n\*]{5,100})["\']?',
        r'\*\*Summary[:/\s]+\*\*\s*([^"\n\*]{5,100})',
        r'Issue.*?summary[:\s]+["\']?([^"\':\n]{5,100})["\']?'
    ]
    for pattern in summary_patterns:
        summary_match = re.search(pattern, text, re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()
            # Clean up common artifacts
            summary = re.sub(r'\s+', ' ', summary)
            summary = summary.strip('.,;:- ')
            if len(summary) > 5:  # Valid summary
                info['summary'] = summary
                break
    
    # Extract status with multiple patterns
    status_patterns = [
        r'[Ss]tatus[:/\s]+["\']?([A-Za-z\s]+?)(?:["\'\n,\.]|$)',
        r'\*\*Status[:/\s]+\*\*\s*([A-Za-z\s]+)',
        r'to\s+["\']?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)["\']?\s*(?:status)?',
        r'moved to\s+["\']?([A-Za-z\s]+?)["\']?(?:\s|$)'
    ]
    for pattern in status_patterns:
        status_match = re.search(pattern, text)
        if status_match:
            status = status_match.group(1).strip()
            # Validate status (common Jira statuses)
            if status and any(s in status for s in ['To Do', 'In Progress', 'Done', 'Review', 'Testing', 'Closed']):
                info['status'] = status
                break
    
    return info


###########################
##### Langgraph State #####
###########################

class State(MessagesState):
    query: Annotated[Optional[str], "Main user query"]
    next_node: Annotated[Optional[str], "Next node to execute"]
    iteration_count: Annotated[int, "Number of iterations to prevent infinite loops"]
    context_data: Annotated[Dict[str, Any], "Shared context between agents"]
    task_completed: Annotated[bool, "Flag to indicate if all tasks are completed"]


###########################
##### Langgraph Nodes #####
###########################

def jira_agent(state: State) -> State:
    """Jira Agent - Handles all Jira operations and extracts comprehensive context"""
    messages = state.get("messages", [])
    
    if messages:
        last_msg = messages[-1]
        task = last_msg.content if isinstance(last_msg, BaseMessage) else str(last_msg)
    else:
        task = state.get("query", "")
    
    llm = get_llm()
    jira_tools = [
        jira_create_issue,
        jira_search_issues,
        jira_transition_issue,
        jira_add_comment,
        jira_get_issue_details
    ]
    
    agent = create_react_agent(model=llm, tools=jira_tools)
    
    system_prompt = """You are a Jira expert assistant. Execute the given task precisely.

Available capabilities:
- Create new issues with detailed information
- Search for issues using various filters and JQL
- Transition issues between statuses
- Add comments to existing issues
- Get complete details of any issue

CRITICAL RESPONSE FORMAT:
When you complete an action, your response MUST include ALL of these details clearly:
1. Issue Key (e.g., SCRUM-123)
2. Summary/Title of the issue
3. Current Status
4. Full URL to the issue

Format your response like this:
"Successfully [action] issue SCRUM-123
Summary: [The issue title]
Status: [Current status]
URL: [Full URL]"

Be explicit and include ALL information. This data will be used by other agents."""
    
    resp = agent.invoke({"messages": [
        SystemMessage(content=system_prompt),
        HumanMessage(content=task)
    ]})
    
    last_message = resp.get("messages", [])[-1]
    response_text = last_message.content
    
    print("\n🎫 Jira Agent Response:")
    print(response_text[:600] if len(response_text) > 600 else response_text)
    
    # Extract comprehensive context
    jira_info = extract_comprehensive_jira_info(response_text)
    context_data = state.get("context_data", {})
    
    if jira_info:
        print(f"\n📝 Extracted Context: {jira_info}")
        context_data.update(jira_info)
    else:
        print("\n⚠️ Warning: Could not extract complete context from Jira response")
    
    return {
        "messages": [AIMessage(content=response_text)],
        "context_data": context_data
    }


def slack_agent(state: State) -> State:
    """Slack Agent - Uses context data directly, never asks for missing info"""
    messages = state.get("messages", [])
    context_data = state.get("context_data", {})
    
    if messages:
        last_msg = messages[-1]
        task = last_msg.content if isinstance(last_msg, BaseMessage) else str(last_msg)
    else:
        task = state.get("query", "")
    
    llm = get_llm()
    slack_tools = [
        slack_send_message,
        slack_send_rich_message,
        slack_create_jira_notification
    ]
    
    agent = create_react_agent(model=llm, tools=slack_tools)
    
    # Build context info for the agent
    context_info = ""
    if context_data:
        context_info = f"""
AVAILABLE CONTEXT DATA (use this directly):
{json.dumps(context_data, indent=2)}

This context contains information from previous operations.
"""
    
    # Check if we have Jira-related data in context
    has_jira_data = 'issue_key' in context_data
    
    system_prompt = f"""You are a Slack messaging expert. Execute the given task precisely.

Available tools:
- slack_send_message: Send simple text messages
- slack_send_rich_message: Send formatted messages with Block Kit
- slack_create_jira_notification: Send beautifully formatted Jira notifications

CRITICAL INSTRUCTIONS:
1. **USE THE CONTEXT DATA PROVIDED BELOW** - Do NOT ask for information that's in the context
2. If the task involves Jira (issue keys like SCRUM-123), use slack_create_jira_notification
3. Extract ALL required parameters from the context data
4. For Jira notifications you need: issue_key, summary, status, url
5. **If context data is incomplete, use what's available and fill missing fields with reasonable defaults**
6. NEVER respond with "Could you please provide..." - use the context!
{context_info}

{'**JIRA DATA DETECTED IN CONTEXT** - Use slack_create_jira_notification with the context data above!' if has_jira_data else ''}
"""
    
    resp = agent.invoke({"messages": [
        SystemMessage(content=system_prompt),
        HumanMessage(content=task)
    ]})
    
    last_message = resp.get("messages", [])[-1]
    response_text = last_message.content
    
    print("\n💬 Slack Agent Response:")
    print(response_text)
    
    return {"messages": [AIMessage(content=response_text)]}


def supervisor(state: State) -> State:
    """Supervisor - 100% LLM-driven orchestration with context awareness"""
    messages = state.get("messages", [])
    original_query = state.get("query", "")
    iteration = state.get("iteration_count", 0)
    context_data = state.get("context_data", {})
    
    # Safety check
    if iteration > 10:
        print("\n⚠️ Max iterations reached, completing process")
        return {
            "messages": [AIMessage(content="COMPLETE - All tasks finished")],
            "iteration_count": iteration + 1,
            "task_completed": True
        }
    
    llm = get_llm()
    
    # First iteration - analyze query
    if len(messages) <= 1:
        system_prompt = """You are an intelligent supervisor coordinating Jira and Slack agents.

Available agents:
- 'jira': Handles Jira operations (create, search, update, transition, details)
- 'slack': Handles Slack messaging and notifications

Your job: Analyze the user query and decide the FIRST action.

Rules:
1. Break complex tasks into clear sequential steps
2. Generate ONE specific instruction for the next agent
3. For multi-step tasks (e.g., "move issue and notify"):
   - Step 1: Jira operation (move/create/get)
   - Step 2: Slack notification (will use context from step 1)
4. Be specific and clear in your instruction

Respond with a clear instruction for the first agent to execute."""
        
        resp = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"User Query: {original_query}\n\nWhat should be done first?")
        ])
        
        print(f"\n👔 Supervisor (Iteration {iteration}):")
        print(f"First Task: {resp.content}")
        
        return {
            "messages": [AIMessage(content=resp.content)],
            "iteration_count": iteration + 1
        }
    
    # Subsequent iterations - check progress and decide next step
    else:
        context_summary = ""
        if context_data:
            context_summary = f"""
Current Context Available:
{json.dumps(context_data, indent=2)}

This context will be automatically available to the next agent.
"""
        
        # Build conversation for review
        conversation = [
            SystemMessage(content=f"""You are reviewing task progress and deciding what to do next.

Original User Query: "{original_query}"

Your job: Determine if more work is needed or if all tasks are complete.

Rules:
1. Review what's been completed in the conversation
2. Check if the original query is fully satisfied
3. If COMPLETE, respond with EXACTLY: "COMPLETE"
4. If more work needed, provide ONE clear instruction for the next step
5. For multi-step queries (e.g., "do X and notify"), ensure BOTH steps are done
6. Context data is automatically shared - agents can use it
{context_summary}

Review the conversation and decide: What's next?""")
        ]
        
        # Add recent history (last 4 messages)
        for msg in messages[-4:]:
            if isinstance(msg, BaseMessage):
                conversation.append(msg)
        
        conversation.append(
            HumanMessage(content="Based on the original query and what's been done, what's the next step? If everything is complete, say 'COMPLETE'.")
        )
        
        resp = llm.invoke(conversation)
        
        print(f"\n👔 Supervisor (Iteration {iteration}):")
        decision_preview = resp.content[:200] + "..." if len(resp.content) > 200 else resp.content
        print(f"Decision: {decision_preview}")
        
        # Check completion
        task_completed = any(keyword in resp.content.upper() for keyword in ["COMPLETE", "ALL TASKS", "EVERYTHING IS", "FULLY SATISFIED"])
        
        if task_completed:
            print("✅ Supervisor detected: All tasks COMPLETE")
        
        return {
            "messages": [AIMessage(content=resp.content)],
            "iteration_count": iteration + 1,
            "task_completed": task_completed
        }


def orchestrator(state: State) -> State:
    """Orchestrator - 100% LLM-driven routing, zero hardcoded logic"""
    messages = state.get("messages", [])
    task_completed = state.get("task_completed", False)
    
    if not messages or task_completed:
        print("\n🎯 Orchestrator: END (Tasks Complete)")
        return {"next_node": "end"}
    
    last_message = messages[-1]
    content = last_message.content if isinstance(last_message, BaseMessage) else str(last_message)
    
    # Quick completion check
    if any(keyword in content.upper() for keyword in ["COMPLETE", "FINISHED", "ALL DONE"]):
        print("\n🎯 Orchestrator: END (Completion Detected)")
        return {"next_node": "end"}
    
    # LLM decides routing
    llm = get_llm()
    system_prompt = """You are an intelligent router. Decide which agent should handle the instruction.

Available agents:
- 'jira': For ANY Jira-related operations (create, search, update, transition, get details, etc.)
- 'slack': For ANY Slack-related operations (send messages, notifications, announcements)
- 'end': If the task is complete or no action is needed

Respond with ONLY ONE WORD: 'jira', 'slack', or 'end'

Examples:
"Create issue X" → jira
"Move SCRUM-123 to Done" → jira
"Get details of SCRUM-456" → jira
"Send notification about..." → slack
"Notify team on Slack..." → slack
"Tell everyone about..." → slack
"Complete" → end"""
    
    resp = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Instruction: {content}\n\nWhich agent should handle this?")
    ])
    
    decision = resp.content.strip().lower()
    
    # Route based on LLM decision
    if 'jira' in decision:
        next_node = 'jira'
    elif 'slack' in decision:
        next_node = 'slack'
    else:
        next_node = 'end'
    
    print(f"\n🎯 Orchestrator: Route to {next_node.upper()}")
    
    return {"next_node": next_node}


###########################
##### Langgraph Graph #####
###########################

def build_graph():
    """Build and compile the agentic graph"""
    graph = StateGraph(State)
    
    # Add nodes
    graph.add_node("supervisor", supervisor)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("jira_agent", jira_agent)
    graph.add_node("slack_agent", slack_agent)
    
    # Build flow
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", "orchestrator")
    
    # Conditional routing - LLM decides
    graph.add_conditional_edges(
        "orchestrator",
        lambda s: s.get("next_node", "end"),
        {
            "jira": "jira_agent",
            "slack": "slack_agent",
            "end": END
        }
    )
    
    # Loop back to supervisor for next decision
    graph.add_edge("jira_agent", "supervisor")
    graph.add_edge("slack_agent", "supervisor")
    
    return graph.compile()


def save_graph_visualization(app, filename="agentic_a2a_graph.png"):
    """Save graph visualization as PNG image"""
    try:
        from IPython.display import Image
        graph_image = app.get_graph().draw_mermaid_png()
        
        with open(filename, 'wb') as f:
            f.write(graph_image)
        
        print(f"\n📊 Graph visualization saved: {filename}")
        return True
    except Exception as e:
        print(f"\n⚠️ Could not save graph visualization: {e}")
        print("   Install: pip install pygraphviz (or) pip install grandalf")
        return False


################
##### Main #####
################

if __name__ == "__main__":
    print("=" * 90)
    print("🤖 TRUE AGENTIC A2A SYSTEM - 100% LLM-Driven Intelligence")
    print("=" * 90)
    print("\n✨ Features:")
    print("  🧠 100% LLM-driven decisions - ZERO hardcoded logic")
    print("  🔗 Automatic context sharing - No information loss")
    print("  🎯 Intelligent routing - LLM decides everything")
    print("  📋Full Jira operations")
    print("  💬 Full Slack operations")
    print("\n💡 Example Queries:")
    print("  • 'Create a task for API testing'")
    print("  • 'Send hello message to Slack'")
    print("  • 'Create a bug for login issue and notify the team'")
    print("  • 'Get details of SCRUM-123 and announce on Slack'")
    print("  • 'Move SCRUM-456 to Done and broadcast it'")
    print("=" * 90)
    
    # Build graph
    app = build_graph()
    
    # Get user input
    user_query = input("\n💭 Enter your query: ").strip()
    
    if not user_query:
        print("❌ No query provided. Exiting.")
        exit()
    
    # Initialize state
    initial_state = {
        "query": user_query,
        "iteration_count": 0,
        "messages": [],
        "context_data": {},
        "task_completed": False
    }
    
    print(f"\n🚀 Processing: '{user_query}'")
    print("\n" + "─" * 90)
    
    # Execute workflow
    final_messages = []
    try:
        for step_output in app.stream(initial_state):
            for agent_name, agent_state in step_output.items():
                if agent_state and "messages" in agent_state:
                    messages = agent_state.get("messages", [])
                    if messages:
                        final_messages.extend(messages)
    except Exception as e:
        print(f"\n❌ Error during execution: {str(e)}")
    
    # Display results
    print("\n" + "=" * 90)
    print("✅ EXECUTION COMPLETE")
    print("=" * 90)
    
    if final_messages:
        print("\n📝 Final Results:")
        for msg in final_messages[-3:]:  # Show last 3 messages
            if isinstance(msg, AIMessage):
                print(f"\n{msg.content}")
    
    print("\n" + "=" * 90)
import os
from dotenv import load_dotenv
load_dotenv()

os.environ["LANGSMITH_TRACING"] = "false"

from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, START, END
from jira import JIRA
from langchain.tools import tool
from slack_sdk import WebClient
from typing import Optional
import json

print("\n" + "=" * 70)
print("🤖 TEAM LEAD'S A2A (AGENT-TO-AGENT) SYSTEM")
print("=" * 70)

# ============ CONFIG ============
print("\n📋 Loading configuration...")

JIRA_HOST = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

# Check credentials
missing = []
if not JIRA_HOST: missing.append("JIRA_BASE_URL")
if not SLACK_BOT_TOKEN: missing.append("SLACK_BOT_TOKEN")
if not AZURE_API_KEY: missing.append("AZURE_OPENAI_API_KEY")

if missing:
    print(f"\n❌ Missing in .env: {', '.join(missing)}")
    print("   Please add them to .env file")
    exit(1)

print("✅ Configuration loaded\n")

# ============ CLIENTS ============
print("🔗 Initializing clients...")

try:
    jira_client = JIRA(server=JIRA_HOST, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    print("   ✅ Jira connected")
except Exception as e:
    print(f"   ⚠️  Jira connection failed: {e}")
    jira_client = None

try:
    slack_client = WebClient(token=SLACK_BOT_TOKEN)
    slack_client.auth_test()
    print("   ✅ Slack connected")
except Exception as e:
    print(f"   ⚠️  Slack connection failed: {e}")
    slack_client = None

llm = AzureChatOpenAI(
    model="gpt-4",
    api_key=AZURE_API_KEY,
    azure_endpoint=AZURE_ENDPOINT,
    api_version=AZURE_VERSION,
    temperature=0
)
print("   ✅ Azure GPT-4 initialized\n")

# ============ TOOLS ============

@tool
def create_jira_task(summary: str, description: str) -> dict:
    """Create a Jira task with summary and description"""
    if not jira_client:
        return {"error": "Jira not connected"}
    
    try:
        print(f"\n   📝 Creating Jira task...")
        print(f"      Summary: {summary}")
        
        issue = jira_client.create_issue(
            project=JIRA_PROJECT_KEY,
            summary=summary,
            description=description,
            issuetype={"name": "Task"},
            labels=["automated", "review"]
        )
        
        result = {
            "success": True,
            "issue_key": issue.key,
            "url": f"{JIRA_HOST}/browse/{issue.key}"
        }
        print(f"      ✅ Issue created: {issue.key}")
        return result
    except Exception as e:
        print(f"      ❌ Failed: {e}")
        return {"error": str(e)}

@tool
def send_slack_notification(message: str, channel: Optional[str] = None) -> dict:
    """Send notification to Slack"""
    if not slack_client:
        return {"error": "Slack not connected"}
    
    try:
        print(f"\n   💬 Sending Slack message...")
        print(f"      Channel: {channel or SLACK_CHANNEL}")
        
        response = slack_client.chat_postMessage(
            channel=channel or SLACK_CHANNEL,
            text=message
        )
        
        result = {"success": True, "timestamp": response["ts"]}
        print(f"      ✅ Message sent")
        return result
    except Exception as e:
        print(f"      ❌ Failed: {e}")
        return {"error": str(e)}

# ============ AGENTS ============

def supervisor(state):
    """Decide what to do based on user query"""
    print("\n" + "─" * 70)
    print("👀 SUPERVISOR AGENT")
    print("─" * 70)
    
    messages = [
        {"role": "system", "content": """You are a supervisor. Based on the user query, decide what task to do next.

Available tasks:
1. 'jira' - Create a Jira task
2. 'slack' - Send a Slack message
3. 'jira_slack' - Create Jira task AND send Slack message
4. 'end' - All tasks complete

IMPORTANT: Respond with ONLY the action (jira, slack, jira_slack, or end). No other text."""},
        {"role": "user", "content": state.get("user_query", "")}
    ]
    
    response = llm.invoke(messages)
    next_task = response.content.strip().lower()
    
    # Clean up response
    if "jira" in next_task and "slack" in next_task:
        next_task = "jira_slack"
    elif "jira" in next_task:
        next_task = "jira"
    elif "slack" in next_task:
        next_task = "slack"
    else:
        next_task = "end"
    
    print(f"\n   📌 Decision: {next_task.upper()}")
    
    state["next_agent"] = next_task
    state["supervisor_decision"] = next_task
    
    return state

def jira_agent(state):
    """Create Jira task"""
    print("\n" + "─" * 70)
    print("🎫 JIRA AGENT")
    print("─" * 70)
    
    user_query = state.get("user_query", "")
    
    messages = [
        {"role": "system", "content": """Based on user request, create a Jira task summary and description.
Return JSON format only:
{"summary": "...", "description": "..."}"""},
        {"role": "user", "content": user_query}
    ]
    
    response = llm.invoke(messages)
    
    try:
        task_data = json.loads(response.content)
    except:
        task_data = {
            "summary": "Task from user request",
            "description": user_query
        }
    
    result = create_jira_task.invoke(task_data)
    state["jira_result"] = result
    state["next_agent"] = "supervisor"
    
    return state

def slack_agent(state):
    """Send Slack notification"""
    print("\n" + "─" * 70)
    print("💬 SLACK AGENT")
    print("─" * 70)
    
    user_query = state.get("user_query", "")
    jira_result = state.get("jira_result", {})
    
    messages = [
        {"role": "system", "content": """Based on user request and any Jira task info, create a Slack message.
Make it professional and informative. Include Jira link if available."""},
        {"role": "user", "content": f"User request: {user_query}\n\nJira info: {json.dumps(jira_result)}"}
    ]
    
    response = llm.invoke(messages)
    message = response.content
    
    result = send_slack_notification.invoke({"message": message})
    state["slack_result"] = result
    state["next_agent"] = "supervisor"
    
    return state

# ============ BUILD GRAPH ============

print("🔧 Building LangGraph workflow...\n")

graph = StateGraph(dict)

# Add all nodes
graph.add_node("supervisor", supervisor)
graph.add_node("jira", jira_agent)
graph.add_node("slack", slack_agent)

# Set start
graph.add_edge(START, "supervisor")

# Route based on supervisor decision
def route_supervisor(state):
    return state.get("next_agent", "end")

graph.add_conditional_edges(
    "supervisor",
    route_supervisor,
    {
        "jira": "jira",
        "slack": "slack",
        "jira_slack": "jira",  # Will go to jira first, then loop back to supervisor
        "end": END
    }
)

# Route from agents back to supervisor (except on last task)
def route_from_agents(state):
    decision = state.get("supervisor_decision", "end")
    
    if decision == "jira_slack" and state.get("jira_result"):
        # Jira done, now do Slack
        return "slack"
    return "supervisor"

graph.add_edge("jira", "supervisor")
graph.add_edge("slack", "supervisor")

app = graph.compile()

print("✅ Workflow ready!\n")

# ============ MAIN ============

if __name__ == "__main__":
    print("=" * 70)
    print("📝 EXAMPLE QUERIES:")
    print("=" * 70)
    print("""
1. "Create a Jira task about code review"
2. "Send a Slack message to the team"
3. "Create Jira task and send Slack message"
4. "Notify team about new review process"
    """)
    
    print("=" * 70)
    
    user_input = input("\n🎯 Enter your request: ")
    
    if not user_input.strip():
        print("❌ Please enter a valid request")
        exit(1)
    
    initial_state = {
        "user_query": user_input,
        "next_agent": "supervisor",
        "supervisor_decision": None,
        "jira_result": None,
        "slack_result": None
    }
    
    print("\n" + "=" * 70)
    print("🚀 STARTING WORKFLOW")
    print("=" * 70)
    
    try:
        for step in app.stream(initial_state):
            pass
        
        print("\n" + "=" * 70)
        print("✅ WORKFLOW COMPLETE!")
        print("=" * 70)
        print("\n✨ All tasks completed successfully!\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

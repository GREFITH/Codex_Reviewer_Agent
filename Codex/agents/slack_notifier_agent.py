import os
from slack_sdk import WebClient
from graph.state import ReviewState
from utils.logger import logger

def notify_slack_start(state: ReviewState) -> ReviewState:
    """Create Slack thread with start notification"""
    
    logger.info(f"Posting to Slack: {state.slack_channel}")
    
    client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
    
    message = f""" **Code Review Started**

 Repository: {state.repo_url}
 Jira Issue: {state.issue_key}
 Review Type: {state.review_intent}

 Analyzing code structure and quality...
"""
    
    try:
        response = client.chat_postMessage(
            channel=state.slack_channel,
            text=message
        )
        state.slack_thread_ts = response["ts"]
        state.agent_status = "slack_notified"
        logger.info(f"Posted to Slack: {state.slack_thread_ts}")
        
        # Post progress update in thread
        client.chat_postMessage(
            channel=state.slack_channel,
            thread_ts=state.slack_thread_ts,
            text=" Running code analysis with Azure OpenAI..."
        )
    except Exception as e:
        state.error = f"Slack error: {str(e)}"
        logger.error(f"Slack error: {e}")
    
    return state

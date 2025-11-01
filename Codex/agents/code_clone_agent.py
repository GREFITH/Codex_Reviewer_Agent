import os
import tempfile
import shutil
from pathlib import Path
from git import Repo
from graph.state import ReviewState
from utils.logger import logger
from slack_sdk import WebClient
from jira import JIRA


def clone_and_analyze(state: ReviewState) -> ReviewState:
    """
    Clone repository and analyze its structure.
    Updates Jira and Slack with progress.
    """
    
    logger.info(f"Starting repo clone: {state.repo_url}")
    
    # Create base temp directory if it doesn't exist
    base_temp_dir = os.getenv("TEMP_REPO_PATH", "D:\\Langchain\\AzureCodex\\Repos")
    
    try:
        if not os.path.exists(base_temp_dir):
            os.makedirs(base_temp_dir, exist_ok=True)
            logger.info(f"Created temp directory: {base_temp_dir}")
    except Exception as e:
        state.error = f"Failed to create temp directory: {str(e)}"
        logger.error(state.error)
        return state
    
    # Create unique temp subdirectory for this repo
    temp_dir = tempfile.mkdtemp(dir=base_temp_dir)
    logger.info(f"Temp directory created: {temp_dir}")
    
    try:
        # Clone repository
        logger.info(f"Cloning from {state.repo_url}")
        Repo.clone_from(
            state.repo_url,
            temp_dir,
            branch="main",
            depth=1
        )
        state.repo_path = temp_dir
        logger.info(f"Repository cloned successfully to {temp_dir}")
        
        # Find all Python files
        py_files = list(Path(temp_dir).rglob("*.py"))
        state.files_to_review = [str(f) for f in py_files[:20]]
        logger.info(f"Found {len(state.files_to_review)} Python files")
        
        # Post to Jira
        try:
            jira = JIRA(
                server=os.getenv("JIRA_BASE_URL"),
                basic_auth=(
                    os.getenv("JIRA_EMAIL"),
                    os.getenv("JIRA_API_TOKEN")
                )
            )
            
            file_list = "\n".join([
                f"- {f.split(os.sep)[-1]}"
                for f in state.files_to_review[:5]
            ])
            
            jira_comment = f"""**Repository Cloned Successfully**

 **Cloned Location:** 
{temp_dir}

 **Python Files Found:** {len(state.files_to_review)}

 **Files to Review:**
{file_list}

 **Status:** Starting deep code analysis..."""
            
            jira.add_comment(state.issue_key, jira_comment)
            logger.info(f"Posted clone update to Jira issue {state.issue_key}")
        
        except Exception as e:
            logger.error(f"Failed to post to Jira: {e}")
        
        # Post to Slack
        try:
            if state.slack_thread_ts:
                client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
                
                slack_message = f""" Repository Cloned

 Location: `{temp_dir}`
 Python Files: {len(state.files_to_review)}
 Starting deep analysis..."""
                
                client.chat_postMessage(
                    channel=state.slack_channel,
                    thread_ts=state.slack_thread_ts,
                    text=slack_message
                )
                logger.info("Posted clone update to Slack")
        
        except Exception as e:
            logger.error(f"Failed to post to Slack: {e}")
        
        state.agent_status = "repo_cloned"
        return state
    
    except Exception as e:
        state.error = f"Repository clone failed: {str(e)}"
        logger.error(f"Clone error: {e}")
        
        # Cleanup on failure
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up failed clone directory: {temp_dir}")
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup: {cleanup_error}")
        
        return state

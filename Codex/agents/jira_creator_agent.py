import json
import os
from jira import JIRA
from graph.state import ReviewState
from utils.llm import get_llm_client
from utils.logger import logger


def create_jira_issue(state: ReviewState) -> ReviewState:
    """
    Create Jira issue with repo URL as custom field.
    Sets all fields including Repository URL.
    """
    
    logger.info(f"Creating Jira issue for: {state.repo_url}")
    
    if not state.is_valid_repo:
        state.error = "Cannot create issue without valid repo"
        return state
    
    repo_name = state.repo_url.split('/')[-1]
    llm_client = get_llm_client()
    
    system_prompt = f"""Create a Jira issue summary and description.
Repository: {state.repo_url}
Review Type: {state.review_intent}

Return ONLY JSON:
{{
    "summary": "AI Code Review: {repo_name}",
    "description": "Automated AI-powered deep code review. Review Type: {state.review_intent}",
    "labels": ["review", "ai", "{state.review_intent}"]
}}"""
    
    try:
        issue_content = llm_client.invoke(system_prompt, "Generate issue")
        logger.info(f"Generated: {issue_content}")
        
        try:
            issue_data = json.loads(issue_content)
        except json.JSONDecodeError:
            issue_data = {
                "summary": f"AI Code Review: {repo_name}",
                "description": f"Automated AI-powered deep code review.\nReview Type: {state.review_intent}",
                "labels": ["review", "ai", state.review_intent]
            }
        
        jira = JIRA(
            server=os.getenv("JIRA_BASE_URL"),
            basic_auth=(
                os.getenv("JIRA_EMAIL"),
                os.getenv("JIRA_API_TOKEN")
            )
        )
        
        # Create issue with custom field for Repository URL
        fields = {
            "project": {"key": os.getenv("JIRA_PROJECT_KEY")},
            "summary": issue_data.get("summary"),
            "description": issue_data.get("description"),
            "issuetype": {"name": "Task"},
            "labels": issue_data.get("labels", ["review", "ai"])
        }
        
        # Add custom field for Repository URL if it exists
        # Common custom field names: "customfield_10000", "Repository URL", etc.
        # First, try to find the field ID
        try:
            fields_metadata = jira.fields()
            repo_url_field = None
            
            for field in fields_metadata:
                field_name = field.get('name', '').lower()
                if 'repository' in field_name and 'url' in field_name:
                    repo_url_field = field.get('id')
                    logger.info(f"Found Repository URL field: {repo_url_field}")
                    break
            
            if repo_url_field:
                fields[repo_url_field] = state.repo_url
                logger.info(f"Added {repo_url_field} = {state.repo_url}")
        
        except Exception as e:
            logger.warning(f"Could not find Repository URL field: {e}")
        
        # Create the issue
        issue = jira.create_issue(fields=fields)
        
        state.issue_key = issue.key
        state.jira_created = True
        state.agent_status = "jira_created"
        
        logger.info(f"Issue created: {issue.key}")
        
        # Post initial comment with repo info
        initial_comment = f""" **Code Review Initiated**

 **Repository:** {state.repo_url}
 **Review Type:** {state.review_intent}
 **Status:** Starting code analysis...

---
*Review workflow started at {state.user_id}*"""
        
        jira.add_comment(issue.key, initial_comment)
        logger.info(f"Initial comment posted to {issue.key}")
        
    except Exception as e:
        state.error = f"Jira creation failed: {str(e)}"
        logger.error(f"Jira error: {e}", exc_info=True)
    
    return state

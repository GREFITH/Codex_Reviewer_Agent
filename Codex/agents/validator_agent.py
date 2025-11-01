import re
from graph.state import ReviewState
from utils.logger import logger

def validate_repo(state: ReviewState) -> ReviewState:
    """Validate repo URL"""
    
    logger.info(f"Validating repo: {state.repo_url}")
    
    if not state.repo_url or state.ask_for_repo:
        state.ask_for_repo = True
        state.agent_status = "awaiting_repo_input"
        logger.warning("No repo URL, asking user")
        return state
    
    url_pattern = r'https?://(github\.com|gitlab\.com)/[\w\-]+/[\w\-]+'
    if not re.match(url_pattern, state.repo_url):
        state.validation_error = f"Invalid URL: {state.repo_url}"
        state.ask_for_repo = True
        state.agent_status = "awaiting_repo_input"
        logger.error(f"Invalid URL format: {state.repo_url}")
        return state
    
    state.is_valid_repo = True
    state.agent_status = "validated"
    logger.info(f"Repo validated: {state.repo_url}")
    return state

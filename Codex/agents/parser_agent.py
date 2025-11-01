import json
import re
from graph.state import ReviewState
from utils.llm import get_llm_client
from utils.logger import logger


def parse_user_input(state: ReviewState) -> ReviewState:
    """
    LLM parses user input to extract repo URL and review intent.
    Handles null values and provides defaults.
    """
    
    logger.info(f"Parsing user input: {state.user_input}")
    
    llm_client = get_llm_client()
    
    system_prompt = """You are an expert at parsing user requests for code review.
From the user's message, extract:
1. Repository URL (GitHub, GitLab, etc.)
2. Review intent - MUST be one of: deep_review, security_focused, performance_focused, quality_check

IMPORTANT: Always provide a review_intent. If not specified, default to "deep_review".
DO NOT return null for review_intent.

Return ONLY valid JSON (no markdown, no code blocks):
{
    "repo_url": "https://github.com/user/repo",
    "review_intent": "deep_review"
}"""
    
    try:
        result = llm_client.invoke(system_prompt, state.user_input)
        logger.info(f"LLM Parser result: {result}")
        
        parsed = json.loads(result)
        state.repo_url = parsed.get("repo_url")
        
        # Handle null review_intent
        review_intent = parsed.get("review_intent")
        if not review_intent or review_intent == "null" or review_intent is None:
            review_intent = "deep_review"
            logger.info("review_intent was null, using default: deep_review")
        
        state.review_intent = review_intent
        
        if not state.repo_url or state.repo_url == "null":
            state.ask_for_repo = True
            logger.warning("No repo URL found in parsed input")
        else:
            logger.info(f"Extracted - Repo: {state.repo_url}, Intent: {state.review_intent}")
        
        state.agent_status = "parsed"
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}, attempting regex fallback")
        url_match = re.search(r'https://github\.com/[\w\-]+/[\w\-]+', state.user_input)
        if url_match:
            state.repo_url = url_match.group(0)
            state.review_intent = "deep_review"
            state.agent_status = "parsed"
            logger.info(f"Extracted via regex: {state.repo_url}")
        else:
            state.ask_for_repo = True
            state.error = "Could not extract repository URL"
    
    except Exception as e:
        logger.error(f"Parser error: {e}")
        state.error = str(e)
    
    return state

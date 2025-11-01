import json
from graph.state import ReviewState
from utils.llm import get_llm_client  # ← CHANGE
from utils.logger import logger

def supervisor_decide(state: ReviewState) -> ReviewState:
    """LLM supervisor decides review strategy"""
    
    logger.info("Supervisor deciding strategy")
    
    if not state.files_to_review:
        state.error = "No Python files to review"
        return state
    
    llm_client = get_llm_client()  # ← ADD
    
    files_list = "\n".join(state.files_to_review[:10])
    
    system_prompt = f"""You are a code review supervisor.
Files: {files_list}
Review type: {state.review_intent}

Decide priority files (max 3-5).

Return JSON:
{{
    "files_to_review": ["file1.py", "file2.py"],
    "depth": "deep",
    "focus_areas": ["security", "performance"]
}}"""
    
    try:
        decision = llm_client.invoke(system_prompt, "Decide")  # ← USE
        plan = json.loads(decision)
        state.files_to_review = plan.get("files_to_review", state.files_to_review[:3])
        logger.info(f"Files selected: {state.files_to_review}")
    except json.JSONDecodeError as e:
        logger.warning(f"Parse error: {e}, using default")
        state.files_to_review = state.files_to_review[:3]
    except Exception as e:
        logger.error(f"Supervisor error: {e}")
    
    state.agent_status = "supervisor_decided"
    return state

from langgraph.graph import StateGraph, END
from graph.state import ReviewState
from agents.parser_agent import parse_user_input
from agents.validator_agent import validate_repo
from agents.jira_creator_agent import create_jira_issue
from agents.slack_notifier_agent import notify_slack_start
from agents.code_clone_agent import clone_and_analyze
from agents.supervisor_agent import supervisor_decide
from agents.code_review_agent import deep_code_review
from agents.report_generator_agent import generate_report
from agents.jira_updater_agent import update_jira_results
from agents.slack_updater_agent import update_slack_results
from utils.logger import logger


def route_next_agent(state: ReviewState) -> str:
    logger.info(" Orchestrator router deciding next agent...")
    logger.info(f"Flags: ask_for_repo={state.ask_for_repo}, is_valid_repo={state.is_valid_repo}, jira_created={state.jira_created}, slack_thread_ts={bool(state.slack_thread_ts)}, repo_path={bool(state.repo_path)}, review_report={bool(state.review_report)}, agent_status={state.agent_status}")

    if state.ask_for_repo or not state.repo_url:
        return "ask_repo"
    if not state.is_valid_repo:
        return "validate_repo"
    if not state.jira_created:
        return "create_jira"
    if not state.slack_thread_ts:
        return "notify_slack"
    if not state.repo_path:
        return "clone_repo"
    if not state.review_started:
        return "mark_review_in_progress"
    if not state.deep_reviewed:
        return "deep_review"
    if not state.report_generated:
        return "generate_report"
    if not state.jira_updated:
        return "update_jira"
    if not state.slack_updated:
        return "update_slack"
    return END

# Mark review in progress by transitioning Jira to "In Review"
def mark_review_in_progress(state: ReviewState) -> ReviewState:
    from jira import JIRA
    import os
    try:
        jira = JIRA(server=os.getenv("JIRA_BASE_URL"), basic_auth=(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")))
        transitions = jira.transitions(state.issue_key)
        for t in transitions:
            if "in review" in t["name"].lower():
                jira.transition_issue(state.issue_key, t["id"])
                break
        state.review_started = True
        state.agent_status = "review_in_progress"
    except Exception as e:
        logger.warning(f"Failed Jira transition to 'In Review': {e}")
    return state


def build_agentic_workflow():
    workflow = StateGraph(ReviewState)

    workflow.add_node("parse_input", parse_user_input)
    workflow.add_node("validate_repo", validate_repo)
    workflow.add_node("ask_repo", lambda s: s)
    workflow.add_node("create_jira", create_jira_issue)
    workflow.add_node("notify_slack", notify_slack_start)
    workflow.add_node("clone_repo", clone_and_analyze)
    workflow.add_node("mark_review_in_progress", mark_review_in_progress)
    workflow.add_node("supervisor_decide", supervisor_decide)
    
    # Wrap deep_review to set flag
    def deep_review_wrapper(state):
        result = deep_code_review(state)
        result.deep_reviewed = True
        result.agent_status = "code_reviewed"
        return result
    workflow.add_node("deep_review", deep_review_wrapper)
    
    # Wrap generate_report to set flag
    def generate_report_wrapper(state):
        result = generate_report(state)
        result.report_generated = True
        return result
    workflow.add_node("generate_report", generate_report_wrapper)
    
    # Wrap update_jira to set flag and Jira "Done" transition
    def update_jira_wrapper(state):
        from jira import JIRA
        import os
        result = update_jira_results(state)
        try:
            jira = JIRA(server=os.getenv("JIRA_BASE_URL"), basic_auth=(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")))
            transitions = jira.transitions(state.issue_key)
            for t in transitions:
                if "done" in t["name"].lower():
                    jira.transition_issue(state.issue_key, t["id"])
                    break
        except Exception as e:
            logger.warning(f"Failed Jira transition to 'Done': {e}")
        result.jira_updated = True
        return result
    workflow.add_node("update_jira", update_jira_wrapper)
    workflow.add_node("update_slack", update_slack_results)

    # Orchestrator Router node
    workflow.add_node("orchestrator_router", lambda s: s)

    # Entry point
    workflow.set_entry_point("parse_input")

    # Linear flow to router
    workflow.add_edge("parse_input", "validate_repo")
    workflow.add_edge("validate_repo", "orchestrator_router")
    workflow.add_edge("ask_repo", "parse_input")

    # Conditional routing according to state
    workflow.add_conditional_edges("orchestrator_router", route_next_agent, {
        "ask_repo": "ask_repo",
        "validate_repo": "validate_repo",
        "create_jira": "create_jira",
        "notify_slack": "notify_slack",
        "clone_repo": "clone_repo",
        "mark_review_in_progress": "mark_review_in_progress",
        "supervisor_decide": "supervisor_decide",
        "deep_review": "deep_review",
        "generate_report": "generate_report",
        "update_jira": "update_jira",
        "update_slack": "update_slack",
        END: END,
    })

    # Feed nodes back to router
    for node in ["create_jira", "notify_slack", "clone_repo", "mark_review_in_progress",
                 "supervisor_decide", "deep_review", "generate_report", "update_jira"]:
        workflow.add_edge(node, "orchestrator_router")
    
    workflow.add_edge("update_slack", END)

    logger.info(" Workflow built with flags for state and transitions")
    return workflow.compile()

graph = build_agentic_workflow()

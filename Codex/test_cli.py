import os
import json
from dotenv import load_dotenv
from graph.workflow import graph, END
from graph.state import ReviewState
from agents.parser_agent import parse_user_input
from agents.validator_agent import validate_repo
from utils.logger import logger

# Load environment variables first
load_dotenv()

def prompt_repo_url():
    repo_input = ""
    while not repo_input:
        repo_input = input("\n Please enter a valid repository URL (e.g. 'https://github.com/facebook/react'): ").strip()
        if not repo_input:
            print(" You must enter a valid repo URL.")
    return repo_input

def test_workflow():
    print("\n" + "="*70)
    print("AGENTIC CODE REVIEW SYSTEM - LOCAL CLI TEST (with re-ask)")
    print("="*70)
    
    slack_channel = os.getenv("SLACK_CHANNEL", "C12345678")
    user_input = input("\nEnter message (e.g., 'Review this repo: https://github.com/facebook/react'): ")

    # Loop: parse+validate until repo_url present and valid
    while True:
        state = ReviewState(
            user_input=user_input,
            user_id="cli_test_user",
            slack_channel=slack_channel,
            slack_thread_ts=None
        )
        state = parse_user_input(state)
        state = validate_repo(state)
        if not state.ask_for_repo and state.repo_url:
            break
        print(" No repository URL found!")
        user_input = prompt_repo_url()
    
    print("\n Starting agentic code review workflow...")
    try:
        result = graph.invoke(state)
        print("\n" + "="*70)
        print(" WORKFLOW RESULTS")
        print("="*70)
        print(f"\n Status: {result.get('agent_status')}")
        print(f" Repository: {result.get('repo_url')}")
        print(f" Jira Issue: {result.get('issue_key')}")
        print(f" Score: {result.get('score')}/100")
        print(f" Critical Issues: {len(result.get('critical_issues', []))}")
        print(f" High Priority Issues: {len(result.get('high_priority', []))}")
        if result.get('error'):
            print(f"\n Error: {result.get('error')}")
        if result.get('review_report'):
            report_file = f"code_review_report_{result.get('issue_key', 'test')}.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(result.get('review_report'), f, indent=2)
            print(f"\n Full JSON report saved to: {report_file}")
        print("="*70)
    except Exception as e:
        logger.error(f"Workflow error: {e}", exc_info=True)
        print(f"\n Error: {e}")

if __name__ == "__main__":
    test_workflow()

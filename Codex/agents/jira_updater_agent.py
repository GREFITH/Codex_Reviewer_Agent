import os
import json
from jira import JIRA
from graph.state import ReviewState
from utils.logger import logger


def save_and_attach_json_report(state: ReviewState, jira, issue_key: str):
    """
    Save JSON report to file and attach to Jira issue.
    """
    try:
        # Create JSON filename
        report_filename = f"code_review_{issue_key}.json"
        report_path = os.path.join(os.getcwd(), report_filename)
        
        # Save JSON to file
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(state.review_report, f, indent=2)
        
        logger.info(f"JSON report saved to: {report_path}")
        
        # Attach to Jira
        with open(report_path, 'rb') as f:
            jira.add_attachment(
                issue=issue_key,
                attachment=f,
                filename=report_filename
            )
        
        logger.info(f"JSON report attached to Jira: {report_filename}")
        
        # Post comment with download info
        download_comment = f""" **DOWNLOADABLE JSON REPORT**

Complete code review report attached: `{report_filename}`

 **Quick Stats:**
• Overall Score: {state.review_report.get('overall_score')}/100
• Critical Issues: {state.review_report.get('critical_issues_count')}
• High Priority Issues: {state.review_report.get('high_issues_count')}
• Files Reviewed: {state.review_report.get('files_reviewed')}

Download the attachment to view full details."""
        
        jira.add_comment(issue_key, download_comment)
        logger.info("Download comment posted to Jira")
        
        return report_path
    
    except Exception as e:
        logger.error(f"Failed to attach JSON report: {e}")
        return None


def update_jira_results(state: ReviewState) -> ReviewState:
    """
    Post complete code review results to Jira issue.
    Updates status and posts all findings.
    """
    
    logger.info(f"Starting Jira update for issue: {state.issue_key}")
    
    if not state.issue_key or not state.review_report:
        logger.warning("Missing issue key or review report")
        state.agent_status = "jira_update_skipped"
        return state
    
    try:
        jira = JIRA(
            server=os.getenv("JIRA_BASE_URL"),
            basic_auth=(
                os.getenv("JIRA_EMAIL"),
                os.getenv("JIRA_API_TOKEN")
            )
        )
        
        logger.info(f"Connected to Jira for issue: {state.issue_key}")
        
        # Transition to "In Progress"
        logger.info("Transitioning to IN PROGRESS")
        transition_to_status(jira, state.issue_key, ['in progress', 'start progress', 'in review'])
        
        # Post summary
        logger.info("Posting summary comment")
        summary_comment = f""" **CODE REVIEW COMPLETE**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 **Review Summary**

 **Overall Score:** {state.score}/100
 **Average File Score:** {state.review_report.get('summary', {}).get('average_score', 0):.1f}/100
 **Files Analyzed:** {state.review_report.get('summary', {}).get('total_files', 0)}
 **Critical Issues:** {len(state.critical_issues)}
 **High Priority Issues:** {len(state.high_priority)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 **Review Details**

 Repository: {state.repo_url}
 Review Type: {state.review_intent}
 Status: Complete"""
        
        jira.add_comment(state.issue_key, summary_comment)
        logger.info("Summary posted")
        
        # Post critical issues
        if state.critical_issues:
            logger.info(f"Posting {len(state.critical_issues)} critical issues")
            critical_comment = f""" **CRITICAL ISSUES - MUST FIX**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            for idx, issue in enumerate(state.critical_issues, 1):
                if isinstance(issue, dict):
                    critical_comment += f"""
**Issue #{idx}**
 Type: {issue.get('type', 'Issue').upper()}
 Line: {issue.get('line', 'N/A')}
 Problem: {issue.get('issue', 'N/A')}
 Fix: {issue.get('suggested_fix', 'N/A')}
"""
            
            jira.add_comment(state.issue_key, critical_comment)
            logger.info("Critical issues posted")
        
        # Post high priority issues
        if state.high_priority:
            logger.info(f"Posting {len(state.high_priority)} high priority issues")
            high_comment = f""" **HIGH PRIORITY ISSUES - SHOULD FIX**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            for idx, issue in enumerate(state.high_priority, 1):
                if isinstance(issue, dict):
                    high_comment += f"""
**Issue #{idx}**
 Type: {issue.get('type', 'Issue').upper()}
 Line: {issue.get('line', 'N/A')}
 Problem: {issue.get('issue', 'N/A')}
 Fix: {issue.get('suggested_fix', 'N/A')}
"""
            
            jira.add_comment(state.issue_key, high_comment)
            logger.info("High priority issues posted")
        
        # Post line-by-line analysis
        if state.review_report.get('detailed_line_by_line'):
            logger.info("Posting line-by-line analysis")
            analysis_comment = """🔍 **LINE-BY-LINE CODE ANALYSIS**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            for analysis in state.review_report.get('detailed_line_by_line', []):
                file_name = analysis.get('file', 'Unknown').split('\\')[-1]
                analysis_comment += f"\n File: {file_name}\n\n"
                
                for line_range, description in analysis.get('analysis', {}).items():
                    analysis_comment += f"**Lines {line_range}:**\n{description}\n\n"
            
            jira.add_comment(state.issue_key, analysis_comment)
            logger.info("Line-by-line analysis posted")
        
        # Attach JSON report
        logger.info("Saving and attaching JSON report")
        report_path = save_and_attach_json_report(state, jira, state.issue_key)
        
        # Transition to "Done"
        logger.info("Transitioning to DONE")
        transition_to_status(jira, state.issue_key, ['done', 'completed', 'review complete'])
        
        state.agent_status = "jira_updated"
        logger.info(f"Jira issue {state.issue_key} updated successfully")
        return state
    
    except Exception as e:
        state.error = f"Jira update failed: {str(e)}"
        logger.error(f"Jira error: {e}", exc_info=True)
        state.agent_status = "jira_update_failed"
        return state


def transition_to_status(jira, issue_key: str, possible_status_names: list) -> bool:
    """
    Transition Jira issue to one of the possible status names.
    """
    try:
        transitions = jira.transitions(issue_key)
        
        for transition in transitions:
            trans_name = transition['name'].lower()
            for status_name in possible_status_names:
                if status_name.lower() in trans_name:
                    jira.transition_issue(issue_key, transition['id'])
                    logger.info(f" Transitioned {issue_key} to '{transition['name']}'")
                    return True
        
        logger.warning(f"No matching transition found")
        return False
    
    except Exception as e:
        logger.warning(f"Could not transition issue: {e}")
        return False

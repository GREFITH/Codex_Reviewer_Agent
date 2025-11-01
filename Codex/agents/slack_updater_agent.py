import os
import json
from slack_sdk import WebClient
from graph.state import ReviewState
from utils.logger import logger


def update_slack_results(state: ReviewState) -> ReviewState:
    """
    Post complete code review results to Slack thread.
    Uploads JSON report as downloadable file.
    """
    
    logger.info("Updating Slack with results")
    
    if not state.slack_thread_ts:
        logger.warning("No Slack thread available")
        state.agent_status = "slack_update_skipped"
        return state
    
    if not state.review_report:
        logger.warning("No review report available")
        state.agent_status = "slack_update_skipped"
        return state
    
    client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
    
    try:
        # ===== STEP 1: POST MAIN RESULTS MESSAGE =====
        logger.info("Step 1: Posting main results message")
        
        main_message = f""" **CODE REVIEW COMPLETE!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 **Overall Score:** {state.score}/100
 **Critical Issues:** {len(state.critical_issues)}
 **High Priority Issues:** {len(state.high_priority)}
 **Files Reviewed:** {state.review_report.get('files_reviewed', 0)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 **Jira Issue:** {state.issue_key}
 **Repository:** {state.repo_url}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        
        client.chat_postMessage(
            channel=state.slack_channel,
            thread_ts=state.slack_thread_ts,
            text=main_message
        )
        logger.info("Main results message posted")
        
        # ===== STEP 2: POST CRITICAL ISSUES =====
        if state.critical_issues and len(state.critical_issues) > 0:
            logger.info(f"Step 2: Posting {len(state.critical_issues)} critical issues")
            
            critical_message = " **CRITICAL ISSUES - MUST FIX:**\n\n"
            for idx, issue in enumerate(state.critical_issues[:5], 1):
                if isinstance(issue, dict):
                    critical_message += f"*{idx}. {issue.get('type', 'Issue').upper()}* (Line {issue.get('line', 'N/A')})\n"
                    critical_message += f"  • {issue.get('issue', 'N/A')}\n"
                    critical_message += f"  → {issue.get('suggested_fix', 'N/A')}\n\n"
            
            client.chat_postMessage(
                channel=state.slack_channel,
                thread_ts=state.slack_thread_ts,
                text=critical_message
            )
            logger.info("Critical issues posted")
        
        # ===== STEP 3: POST HIGH PRIORITY ISSUES =====
        if state.high_priority and len(state.high_priority) > 0:
            logger.info(f"Step 3: Posting {len(state.high_priority)} high priority issues")
            
            high_message = " **HIGH PRIORITY ISSUES - SHOULD FIX:**\n\n"
            for idx, issue in enumerate(state.high_priority[:5], 1):
                if isinstance(issue, dict):
                    high_message += f"*{idx}. {issue.get('type', 'Issue').upper()}* (Line {issue.get('line', 'N/A')})\n"
                    high_message += f"  • {issue.get('issue', 'N/A')}\n"
                    high_message += f"  → {issue.get('suggested_fix', 'N/A')}\n\n"
            
            client.chat_postMessage(
                channel=state.slack_channel,
                thread_ts=state.slack_thread_ts,
                text=high_message
            )
            logger.info("High priority issues posted")
        
        # ===== STEP 4: POST STRENGTHS & IMPROVEMENTS =====
        logger.info("Step 4: Posting strengths and improvements")
        
        all_strengths = []
        all_improvements = []
        
        for finding in state.review_report.get('findings', []):
            all_strengths.extend(finding.get('strengths', []))
            all_improvements.extend(finding.get('improvements', []))
        
        if all_strengths or all_improvements:
            strengths_message = " **STRENGTHS & IMPROVEMENTS:**\n\n"
            
            if all_strengths:
                strengths_message += "* Strengths:*\n"
                for strength in all_strengths[:3]:
                    strengths_message += f"  ✓ {strength}\n"
                strengths_message += "\n"
            
            if all_improvements:
                strengths_message += "* Areas for Improvement:*\n"
                for improvement in all_improvements[:3]:
                    strengths_message += f"  → {improvement}\n"
            
            client.chat_postMessage(
                channel=state.slack_channel,
                thread_ts=state.slack_thread_ts,
                text=strengths_message
            )
            logger.info("Strengths and improvements posted")
        
        # ===== STEP 5: UPLOAD JSON REPORT AS FILE =====
        logger.info("Step 5: Saving and uploading JSON report as file")
        
        json_report = upload_json_report_to_slack(
            client,
            state,
            state.slack_channel,
            state.slack_thread_ts
        )
        
        if json_report:
            logger.info("JSON report uploaded to Slack successfully")
        else:
            logger.warning("Failed to upload JSON report")
        
        state.agent_status = "slack_updated"
        logger.info("Slack update completed successfully")
        return state
    
    except Exception as e:
        state.error = f"Slack update failed: {str(e)}"
        logger.error(f"Slack error: {e}", exc_info=True)
        state.agent_status = "slack_update_failed"
        return state


def upload_json_report_to_slack(client: WebClient, state: ReviewState, channel: str, thread_ts: str) -> bool:
    """
    Save JSON report to file and upload to Slack as downloadable attachment.
    """
    try:
        # Create filename
        report_filename = f"code_review_{state.issue_key}.json"
        report_path = os.path.join(os.getcwd(), report_filename)
        
        logger.info(f"Creating JSON report file: {report_filename}")
        
        # Save JSON to file
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(state.review_report, f, indent=2)
        
        logger.info(f"JSON file saved to: {report_path}")
        
        # Upload to Slack
        logger.info(f"Uploading file to Slack: {report_filename}")
        
        with open(report_path, 'rb') as f:
            response = client.files_upload_v2(
                channel=channel,
                file=f,
                filename=report_filename,
                title=f" Code Review Report - {state.issue_key}",
                initial_comment=f""" **DOWNLOADABLE JSON REPORT**

Repository: {state.repo_url}
Issue: {state.issue_key}

 Stats:
• Overall Score: {state.review_report.get('overall_score')}/100
• Critical Issues: {state.review_report.get('critical_issues_count')}
• High Priority Issues: {state.review_report.get('high_issues_count')}
• Files Reviewed: {state.review_report.get('files_reviewed')}

 Click the file to download the complete JSON report with all findings and line-by-line analysis."""
            )
        
        logger.info(f"File uploaded successfully: {response}")
        
        # Post notification in thread
        file_notification = f""" **Downloadable Report Available**

Complete JSON report with all findings has been uploaded as attachment: `{report_filename}`

The report includes:
 Overall code quality score
 Critical issues with line numbers
 High priority issues with fixes
 Line-by-line code analysis
 Strengths and improvements
 Raw findings for each file"""
        
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=file_notification
        )
        
        logger.info("File upload notification posted to thread")
        return True
    
    except Exception as e:
        logger.error(f"Failed to upload JSON to Slack: {e}", exc_info=True)
        
        # Try to post error message to Slack
        try:
            error_message = f" Failed to upload JSON report: {str(e)}"
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=error_message
            )
        except Exception as msg_error:
            logger.error(f"Also failed to post error message: {msg_error}")
        
        return False

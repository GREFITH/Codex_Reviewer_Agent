import json
from graph.state import ReviewState
from utils.logger import logger

def generate_report(state: ReviewState) -> ReviewState:
    """Generate comprehensive report"""
    
    logger.info("Generating final report")
    
    if not state.review_report:
        state.error = "No review findings"
        return state
    
    findings = state.review_report.get("findings", [])
    
    if not findings:
        state.error = "No findings"
        return state
    
    scores = [f.get("score", 70) for f in findings]
    avg_score = sum(scores) / len(scores) if scores else 0
    
    critical = []
    high = []
    
    for finding in findings:
        for issue in finding.get("issues", []):
            if issue.get("severity") == "critical":
                critical.append(issue)
            elif issue.get("severity") == "high":
                high.append(issue)
    
    state.score = int(avg_score)
    state.critical_issues = critical
    state.high_priority = high
    
    # Create comprehensive report
    comprehensive_report = {
        "overall_score": state.score,
        "critical_issues_count": len(critical),
        "high_issues_count": len(high),
        "files_reviewed": len(findings),
        "repository": state.repo_url,
        "review_type": state.review_intent,
        "findings": findings,
        "summary": {
            "total_files": len(findings),
            "average_score": avg_score,
            "critical_count": len(critical),
            "high_count": len(high)
        },
        "detailed_line_by_line": []
    }
    
    # Extract line-by-line analysis
    for finding in findings:
        if finding.get("line_by_line_analysis"):
            comprehensive_report["detailed_line_by_line"].append({
                "file": finding.get("file"),
                "analysis": finding.get("line_by_line_analysis")
            })
    
    state.review_report = comprehensive_report
    state.agent_status = "report_generated"
    
    logger.info(f"Report: Score {state.score}/100, Critical: {len(critical)}, High: {len(high)}")
    return state

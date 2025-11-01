import json
from graph.state import ReviewState
from utils.llm import get_llm_client
from utils.logger import logger

def deep_code_review(state: ReviewState) -> ReviewState:
    """LLM deep code analysis with line-by-line review"""
    
    logger.info("Starting deep code review")
    
    if not state.files_to_review or not state.repo_path:
        state.error = "No files to review"
        return state
    
    llm_client = get_llm_client()
    findings = []
    
    for file_path in state.files_to_review:
        logger.info(f"Reviewing: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
            
            # Add line numbers for analysis
            lines = code.split('\n')
            code_with_lines = '\n'.join([f"{i+1:3d}: {line}" for i, line in enumerate(lines[:100])])
            
            if len(lines) > 100:
                code_with_lines += f"\n... [{len(lines) - 100} more lines]"
            
            system_prompt = """You are a senior code reviewer with 15+ years experience.
Analyze this Python code and provide DETAILED line-by-line review:

1. **Security Issues** - specific line numbers and vulnerability details
2. **Performance Issues** - which lines are inefficient and why
3. **Best Practices** - SOLID principles violations
4. **Error Handling** - missing exception handlers
5. **Code Quality** - readability, maintainability issues

For EACH issue, provide:
- Line number(s)
- Issue description
- Severity (critical/high/medium)
- Suggested fix

Return ONLY JSON (NO markdown):
{
    "file": "filename.py",
    "total_lines": 100,
    "score": 75,
    "issues": [
        {
            "line": 10,
            "severity": "critical",
            "type": "security",
            "issue": "SQL injection vulnerability",
            "code_snippet": "user_input in query",
            "explanation": "Direct string interpolation allows SQL injection. Use parameterized queries.",
            "suggested_fix": "Use cursor.execute(query, (user_input,))"
        }
    ],
    "line_by_line_analysis": {
        "10-15": "This section handles user input without sanitization. Lines 12-13 are vulnerable.",
        "20-25": "Good exception handling with try-except block",
        "30": "Performance issue: nested loop on line 30 has O(n²) complexity"
    },
    "strengths": ["Good function documentation", "Proper logging"],
    "improvements": ["Add type hints", "Extract magic numbers to constants"],
    "overall_assessment": "Code is functional but has security issues that must be addressed"
}"""
            
            result = llm_client.invoke(system_prompt, f"Review with line numbers:\n{code_with_lines}")
            
            try:
                analysis = json.loads(result)
                findings.append(analysis)
                logger.info(f"File score: {analysis.get('score', 70)}")
            except json.JSONDecodeError:
                findings.append({
                    "file": file_path,
                    "score": 70,
                    "analysis": result
                })
        
        except Exception as e:
            logger.error(f"Review error: {e}")
    
    state.review_report = {"findings": findings}
    state.agent_status = "code_reviewed"
    logger.info(f"Deep review completed for {len(findings)} files")
    return state

# 🤖 Codex Reviewer Agent - AI-Powered Agentic Code Review System

An intelligent, **fully agentic** multi-agent code review system using **LangGraph**, **Azure OpenAI**, **Jira**, and **Slack** for autonomous code analysis, deep line-by-line review, and intelligent reporting.

---

## 📋 Table of Contents 

- [Features](#features)
- [System Architecture](#system-architecture)
- [Agentic Workflow](#agentic-workflow)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Outputs](#outputs)
- [Technology Stack](#technology-stack)
- [Contributing](#contributing)
- [License](#license)

---

## ✨ Features

### 🤖 Fully Agentic System
- **Multi-Agent Orchestration**: 10+ autonomous agents working together
- **Supervisor Router**: LLM-driven decision making for dynamic workflow routing
- **Non-Linear Flow**: Conditional routing, looping, and intelligent branching via LangGraph
- **Stateful Progression**: ReviewState tracks all agent decisions and dependencies

### 🔍 Deep Code Analysis
- **LLM-Powered Review**: Azure OpenAI GPT-4 for intelligent code analysis
- **Line-by-Line Analysis**: Deep code understanding with specific line numbers and issues
- **Security Issues Detection**: Identifies vulnerabilities and security concerns
- **Performance Analysis**: Detects inefficiencies and optimization opportunities
- **Best Practices Checking**: SOLID principles, design patterns, error handling

### 📊 Jira Integration
- **Auto Issue Creation**: Generates Jira tasks automatically
- **Repository URL Field**: Populates custom field with GitHub/GitLab URL
- **Status Transitions**: 
  - ✅ In Progress (when code review starts)
  - 🔄 In Review (during analysis)
  - ✅ Done (on completion)
- **Detailed Comments**: Posts findings, line-by-line analysis, strengths, and improvements
- **JSON Report Attachment**: Attaches complete analysis report for download

### 💬 Slack Integration
- **Real-Time Notifications**: Updates in Slack thread throughout workflow
- **Downloadable Reports**: Uploads JSON file directly to Slack
- **Thread-Based Updates**: Organized conversation in dedicated threads
- **Results Summary**: Score, critical issues, high priority items, and improvements

### 🔗 GitHub Integration
- **Repository Cloning**: Autonomously clones repositories
- **Python File Discovery**: Identifies and prioritizes files for review
- **Deep File Analysis**: Analyzes up to 20 Python files per review

### 📈 LangGraph Visualization
- **Non-Linear Workflow**: Shows actual agentic decision routing
- **Conditional Edges**: Displays router logic and branching
- **PNG Export**: Saves workflow diagram as PNG and Mermaid diagram
- **Real Orchestration**: Visualizes supervisor agent controlling flow

### 🖥️ Multiple Execution Modes
- **CLI Mode** (test_cli.py): Local testing without ngrok
- **Slack Bot Mode** (main.py): Production deployment with ngrok
- **Full Automation**: Runs end-to-end without user intervention

---

## 🏗️ System Architecture

### Agents (10 Total)

| Agent | Purpose | Input | Output |
|-------|---------|-------|--------|
| **Parser** | Extract repo URL and review intent | User message | repo_url, review_intent |
| **Validator** | Validate GitHub/GitLab URL format | repo_url | is_valid_repo |
| **Jira Creator** | Create Jira issue with details | repo_url, review_intent | issue_key |
| **Slack Notifier** | Create Slack thread | issue_key | slack_thread_ts |
| **Code Cloner** | Clone repo and find Python files | repo_url | repo_path, files_to_review |
| **Supervisor** | Route to next agent based on state | ReviewState | Next agent decision |
| **Code Reviewer** | Perform deep LLM code analysis | files_to_review | review_report with issues |
| **Report Generator** | Aggregate findings into report | review_report | JSON report, scores |
| **Jira Updater** | Post results to Jira | review_report | Jira comments, attachments |
| **Slack Updater** | Post results to Slack | review_report | Slack messages, file upload |

### Orchestrator (Router)

The **Supervisor Router** is the decision-making agent that:
- Inspects current ReviewState
- Decides which agent to execute next
- Handles looping (re-asking for invalid repo URL)
- Ensures proper state progression
- Prevents infinite loops with flags

State Flags: ask_for_repo, is_valid_repo, jira_created, slack_thread_ts,
repo_path, review_started, deep_reviewed, report_generated,
jira_updated, slack_updated


### LangGraph Workflow

START
↓
parse_input
↓
validate_repo ←────┐
↓ │
orchestrator_router ─→ ask_repo (if invalid)
↓
create_jira → transition to "In Progress"
↓
notify_slack
↓
clone_repo
↓
mark_review_in_progress → transition to "In Review"
↓
deep_review (LLM analysis)
↓
generate_report
↓
update_jira (post comments + transition to "Done")
↓
update_slack (post results + upload JSON)
↓
END


---

## 🤖 Agentic Workflow

### How It Works (End-to-End)

User Input: "Review this repo: https://github.com/GREFITH/Langchain"
↓
┌─────────────────────────────────────────────────────────┐
│ FULLY AGENTIC AUTONOMOUS WORKFLOW │
├─────────────────────────────────────────────────────────┤
│ │
│ 1. PARSER AGENT extracts repo URL │
│ └─→ Parse user message using LLM │
│ │
│ 2. VALIDATOR AGENT validates URL format │
│ └─→ If invalid, ASK_REPO loop triggers │
│ └─→ If valid, proceed │
│ │
│ 3. JIRA CREATOR AGENT creates issue │
│ └─→ LLM generates summary & description │
│ └─→ Sets Repository URL custom field │
│ └─→ Jira Status: To Do → In Progress │
│ │
│ 4. SLACK NOTIFIER creates thread │
│ └─→ Posts initial notification │
│ └─→ Returns thread_ts for threading │
│ │
│ 5. CODE CLONER clones repository │
│ └─→ Git clone to temp directory │
│ └─→ Finds all .py files (max 20) │
│ └─→ Posts clone status to Jira + Slack │
│ │
│ 6. SUPERVISOR ROUTER marks review in progress │
│ └─→ Transitions Jira to "In Review" │
│ └─→ Sets review_started flag │
│ │
│ 7. DEEP REVIEW AGENT (LLM) analyzes code │
│ └─→ Line-by-line analysis for each file │
│ └─→ Identifies: │
│ - Security vulnerabilities │
│ - Performance issues │
│ - Code quality problems │
│ - Design pattern violations │
│ - Error handling gaps │
│ └─→ Calculates per-file scores │
│ │
│ 8. REPORT GENERATOR aggregates findings │
│ └─→ Calculates overall score │
│ └─→ Separates critical vs high priority │
│ └─→ Creates JSON report │
│ │
│ 9. JIRA UPDATER posts results │
│ └─→ Posts summary comment │
│ └─→ Posts critical issues │
│ └─→ Posts high priority issues │
│ └─→ Posts line-by-line analysis │
│ └─→ Posts strengths & improvements │
│ └─→ Attaches JSON report for download │
│ └─→ Transitions Jira to "Done" │
│ │
│ 10. SLACK UPDATER posts results in thread │
│ └─→ Posts summary with score & issues │
│ └─→ Posts critical issues │
│ └─→ Uploads JSON file to Slack │
│ │
│ WORKFLOW COMPLETE ✅ │
└─────────────────────────────────────────────────────────┘


---

## 📦 Installation

### Prerequisites
- Python 3.8+
- Git
- GitHub account
- Azure OpenAI API access
- Jira account
- Slack workspace

### Step 1: Clone Repository

git clone https://github.com/GREFITH/Codex_Reviewer_Agent.git
cd Codex_Reviewer_Agent


### Step 2: Create Virtual Environment

Windows
python -m venv venv
venv\Scripts\activate

Mac/Linux
python3 -m venv venv
source venv/bin/activate


### Step 3: Install Dependencies

pip install -r requirements.txt


### Step 4: Create .env File

Windows
type nul > .env

Mac/Linux
touch .env


---

## ⚙️ Configuration

### Add to .env File

Azure OpenAI
AZURE_OPENAI_API_KEY=your_azure_openai_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4

Jira
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@domain.com
JIRA_API_TOKEN=your_jira_api_token
JIRA_PROJECT_KEY=SCRUM

Slack
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_CHANNEL=C1234567890

Optional
TEMP_REPO_PATH=D:\Langchain\AzureCodex\Repos


### Get API Keys

**Azure OpenAI:**
1. Go to https://portal.azure.com
2. Create Azure OpenAI resource
3. Copy API key and endpoint

**Jira:**
1. Go to https://id.atlassian.com/manage/api-tokens
2. Create new API token
3. Copy token

**Slack:**
1. Go to https://api.slack.com/apps
2. Create new app
3. Add bot scopes: `chat:write`, `files:write`
4. Install app and copy bot token

---

## 🚀 Usage

### Mode 1: CLI Testing (Local, No ngrok)

python test_cli.py


**Input:**

review repo: https://github.com/GREFITH/Langchain


**Output:**
- ✅ Jira issue created and updated
- ✅ JSON report generated
- ✅ LangGraph PNG saved

### Mode 2: Slack Bot (Production, Requires ngrok)

**Terminal 1: Start Flask bot**

python main.py


**Terminal 2: Start ngrok tunnel**

ngrok http 5000


**Slack:**

@bot review repo: https://github.com/GREFITH/Langchain


---

## 📂 Project Structure

Codex_Reviewer_Agent/
├── agents/
│ ├── parser_agent.py # Extract repo URL
│ ├── validator_agent.py # Validate URL
│ ├── jira_creator_agent.py # Create Jira issue
│ ├── slack_notifier_agent.py # Create Slack thread
│ ├── code_clone_agent.py # Clone repo
│ ├── supervisor_agent.py # Route decisions
│ ├── code_review_agent.py # Deep LLM review
│ ├── report_generator_agent.py # Aggregate findings
│ ├── jira_updater_agent.py # Post to Jira
│ └── slack_updater_agent.py # Post to Slack
├── graph/
│ ├── workflow.py # LangGraph workflow
│ └── state.py # ReviewState model
├── utils/
│ ├── llm.py # LLM client
│ └── logger.py # Logging setup
├── test_cli.py # CLI testing
├── main.py # Slack bot server
├── requirements.txt # Dependencies
├── .env # Configuration (not committed)
├── .gitignore # Git ignore rules
└── README.md # This file


---

## 💡 How It Works

### State Management (ReviewState)

All agents share a single state object tracking:
- User input and repo details
- Validation status
- Jira and Slack integration points
- Repository path and files
- Review findings and scores
- Agent execution flags

### LangGraph Orchestration

LangGraph manages:
- **Non-linear routing**: Router decides next agent based on state
- **Conditional edges**: If conditions met, route to specific agent
- **Looping**: Handles re-asking for invalid input
- **Error handling**: Graceful failure and logging

### LLM Integration

Azure OpenAI GPT-4 is used for:
- Parsing user intent
- Generating Jira summaries
- Deep code review analysis
- Report generation

---

## 📊 Outputs

After workflow completion, you get:

### 1. Jira Issue
- **Title**: AI Code Review: [Repo Name]
- **Repository URL**: Custom field populated
- **Status**: In Progress → In Review → Done
- **Comments**: Summary, findings, analysis, JSON report
- **Attachment**: code_review_SCRUM-XX.json

### 2. Slack Thread
- **Messages**: Progress updates and results
- **File Upload**: code_review_SCRUM-XX.json (downloadable)
- **Score**: Overall code quality score

### 3. JSON Report

{
"overall_score": 70,
"critical_issues_count": 2,
"high_issues_count": 17,
"files_reviewed": 12,
"findings": [
{
"file": "example.py",
"score": 65,
"issues": [
{
"line": 45,
"severity": "critical",
"type": "security",
"issue": "...",
"suggested_fix": "..."
}
]
}
]
}


### 4. Workflow Graph
- **langgraph_workflow.png**: Visual diagram
- **langgraph_workflow.mmd**: Mermaid diagram

---

## 🛠️ Technology Stack

| Component | Technology |
|-----------|------------|
| **Orchestration** | LangGraph |
| **LLM** | Azure OpenAI GPT-4 |
| **Code Analysis** | Python AST + LLM |
| **Jira** | Atlassian Jira REST API |
| **Slack** | Slack Bot SDK |
| **Web Server** | Flask |
| **Version Control** | Git |

---

## 🎯 Agentic Characteristics

✅ **Multi-Agent**: 10 autonomous agents  
✅ **Supervisor Routing**: Dynamic decision-making based on state  
✅ **Stateful**: ReviewState tracks all progress  
✅ **Looping**: Handles user re-input and retries  
✅ **Non-Linear**: Conditional routing and branching  
✅ **LLM-Driven**: AI makes routing and analysis decisions  
✅ **Fully Autonomous**: Runs without user intervention  
✅ **Reactive**: Responds to state changes  
✅ **Integrated**: Works with external systems (Jira, Slack)  

---

## 📝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

---

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

---

## 👤 Author

**GREFITH**  
GitHub: [@GREFITH](https://github.com/GREFITH)

---

## 🙏 Acknowledgments

- Azure OpenAI for GPT-4 API
- LangGraph for orchestration framework
- Atlassian Jira and Slack for integrations
- Open source community

---

## 📞 Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check existing documentation
- Review workflow logs

---

**Built with ❤️ using LangGraph and AI**


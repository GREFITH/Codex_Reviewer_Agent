import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("RUNNING ALL CREDENTIAL TESTS")
print("=" * 60)

# Test 1: Azure
print("\n1️⃣  Testing Azure OpenAI GPT-4...")
try:
    from openai import AzureOpenAI
    
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    
    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
        messages=[{"role": "user", "content": "Hello"}]
    )
    
    print("   ✅ PASSED - Azure GPT-4 works!")
    
except Exception as e:
    print(f"   ❌ FAILED - {e}")

# Test 2: GitHub
print("\n2️⃣  Testing GitHub Token...")
try:
    token = os.getenv("GITHUB_TOKEN")
    
    if token and token.startswith("ghp_") and len(token) > 30:
        print("   ✅ PASSED - GitHub token valid!")
    else:
        print("   ❌ FAILED - GitHub token invalid!")
        
except Exception as e:
    print(f"   ❌ FAILED - {e}")

# Test 3: Jira (FIXED)
print("\n3️⃣  Testing Jira Connection...")
try:
    from jira import JIRA
    
    jira = JIRA(
        server=os.getenv("JIRA_BASE_URL"),
        basic_auth=(
            os.getenv("JIRA_EMAIL"),
            os.getenv("JIRA_API_TOKEN")
        )
    )
    
    user_info = jira.current_user()
    
    # Handle different return types
    if isinstance(user_info, str):
        user_name = user_info
    else:
        user_name = user_info.name if hasattr(user_info, 'name') else str(user_info)
    
    print(f"   ✅ PASSED - Jira connected!")
    
except Exception as e:
    print(f"   ❌ FAILED - {str(e)[:100]}")

# Test 4: Slack
print("\n4️⃣  Testing Slack Connection...")
try:
    from slack_sdk import WebClient
    
    client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
    auth = client.auth_test()
    
    print(f"   ✅ PASSED - Slack bot works!")
    
except Exception as e:
    print(f"   ❌ FAILED - {e}")

print("\n" + "=" * 60)
print("TEST SUMMARY COMPLETE")
print("=" * 60)

import os
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from utils.logger import logger

class LLMClient:
    def __init__(self):
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        
        # Debug: Check if env vars loaded
        logger.info(f"API Key loaded: {bool(api_key)}")
        logger.info(f"Endpoint loaded: {bool(endpoint)}")
        logger.info(f"Deployment loaded: {bool(deployment)}")
        
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY not set in .env")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT not set in .env")
        if not deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT_NAME not set in .env")
        
        self.llm = AzureChatOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            azure_deployment=deployment,
            api_version=api_version or "2024-08-01-preview"
        )
        logger.info("LLM Client initialized successfully")
    
    def invoke(self, system_prompt: str, user_message: str) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]
        response = self.llm.invoke(messages)
        return response.content

# DO NOT initialize here - initialize on demand
llm_client = None

def get_llm_client():
    """Get or create LLM client lazily"""
    global llm_client
    if llm_client is None:
        llm_client = LLMClient()
    return llm_client

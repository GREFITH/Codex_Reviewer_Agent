from dotenv import load_dotenv
load_dotenv()
import os
from openai import AzureOpenAI

client = AzureOpenAI(
    api_version="2024-12-01-preview",
    azure_endpoint="https://code-review-foundry-us2.cognitiveservices.azure.com/",
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)
import os
from dotenv import load_dotenv
load_dotenv()

os.environ["LANGSMITH_TRACING"] = "false"

from langgraph.graph import StateGraph, END
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage
import uuid

print("=" * 70)
print("🤖 TEAM LEAD'S AGENTIC CONVERSATION EXAMPLE")
print("=" * 70)

# Use Azure GPT-4 (FASTER than Google Gemini!)
llm = AzureChatOpenAI(
    model="gpt-4",
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

print("\n✅ Azure GPT-4 initialized\n")

def agent_a_node(state):
    messages = state.get('messages', [])
    content = messages[-1].content if messages else ''
    print(f"Agent A thinking...")
    reply = llm.invoke([HumanMessage(content=f"AgentA: {content}")])
    messages.append(HumanMessage(content=reply.content, id=str(uuid.uuid4())))
    state['messages'] = messages
    state['next_node'] = 'agent_b'
    print(f"Agent A: {reply.content[:80]}...\n")
    return state

def agent_b_node(state):
    messages = state.get('messages', [])
    content = messages[-1].content if messages else ''
    print(f"Agent B thinking...")
    reply = llm.invoke([HumanMessage(content=f"AgentB: {content}")])
    messages.append(HumanMessage(content=reply.content, id=str(uuid.uuid4())))
    state['messages'] = messages
    
    if len(messages) < 6:
        state['next_node'] = 'agent_a'
    else:
        state['next_node'] = END
    print(f"Agent B: {reply.content[:80]}...\n")
    return state

workflow = StateGraph(dict)
workflow.add_node("agent_a", agent_a_node)
workflow.add_node("agent_b", agent_b_node)
workflow.set_entry_point("agent_a")

def route_edges(state): 
    return state.get('next_node', END)

workflow.add_conditional_edges("agent_a", route_edges, {"agent_b": "agent_b", END: END})
workflow.add_conditional_edges("agent_b", route_edges, {"agent_a": "agent_a", END: END})
graph = workflow.compile()

print("🚀 STARTING CONVERSATION\n")

state = {"messages": [HumanMessage(content="How does AI help researchers?")]}
result = graph.invoke(state)

print("\n" + "=" * 70)
print("✅ CONVERSATION COMPLETE")
print("=" * 70 + "\n")

for i, msg in enumerate(result['messages']):
    print(f"Exchange {i}: {msg.content}\n")

print(f"Total exchanges: {len(result['messages'])}")

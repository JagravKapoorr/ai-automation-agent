import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import asyncio
from langchain_groq import ChatGroq
from langchain.agents import create_agent
from tools import web_search, send_email, schedule_task, get_weather, summarize_url, calculate
from langchain.agents.middleware import SummarizationMiddleware ,ModelCallLimitMiddleware,HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
api_key = os.getenv("GROQ_API_KEY").strip()
app = FastAPI(title="AI Agent", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
   api_key = os.getenv("GROQ_API_KEY").strip()
)

SYSTEM_PROMPT = """
You are ARIA — Advanced Reasoning Intelligence Assistant.
You are helpful, concise, and precise.

Available tools:

web_search       — Search the internet for news or current information.
send_email       — Send an email immediately when the user asks.
schedule_task    — Schedule a task for later. Use when the user mentions delay words
                   like 'after', 'later', 'in X minutes', 'tomorrow', etc.
get_weather      — Get current weather for a city or location.
summarize_url    — Fetch and summarize content from a URL.
calculate        — Evaluate a math expression safely.

Rules:
- Always use schedule_task if a time delay is mentioned.
- Be concise but complete in your responses.
- If unsure which tool to use, prefer web_search for factual questions.
"""

agent = create_agent(
    model=llm,
    tools=[web_search, send_email, schedule_task, get_weather, summarize_url, calculate],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver(),
    middleware=[
        SummarizationMiddleware(
            model=llm,
            trigger=("tokens", 4000),
            keep=("messages", 20),
        ),
        ModelCallLimitMiddleware(
            thread_limit=10,
            run_limit=10,
            exit_behavior="end",
        ),
        HumanInTheLoopMiddleware(
            interrupt_on={
                "send_email": True,
                "schedule_task": True,
                "web_search": False,
                "get_weather": False,
                "summarize_url": False,
                "calculate": False,
            },
            description_prefix="Approval required for tool execution",
        ),
    ],
)

graph =agent
# -------------------------
# Request Schema
# -------------------------

class ChatRequest(BaseModel):
    message: str
    history: Optional[list] = []


# -------------------------
# Chat Endpoint (non-streaming)
# -------------------------
config = {"configurable": {"thread_id": "user_1"}}
@app.post("/chat")
async def chat(req: ChatRequest):
    messages = req.history + [{"role": "user", "content": req.message}]
    config = {"configurable": {"thread_id": "user_1"}}

    try:
        result = agent.invoke(
            {"messages": messages},
            config=config,
            version="v2"   # ✅ IMPORTANT
        )

        # ✅ HANDLE INTERRUPT
        if result.interrupts:
            return {
                "type": "interrupt",
                "actions": result.interrupts[0].value["action_requests"]
            }

        # ✅ NORMAL RESPONSE
        response_text = ""
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                response_text = msg.content
                break

        return {"type": "response", "response": response_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------
# Streaming Chat Endpoint
# -------------------------

@app.post("/chat-stream")
async def chat_stream(req: ChatRequest):
    messages = req.history + [{"role": "user", "content": req.message}]

    async def generate():
        try:
            for chunk in agent.stream(
                {"messages": messages},
                stream_mode="values",
                config=config,
                version="v2"  
            ):
                if "messages" in chunk:
                    msg = chunk["messages"][-1]
                    if hasattr(msg, "content") and msg.content and hasattr(msg, "type") and msg.type == "ai":
                        yield msg.content
                        await asyncio.sleep(0)
        except Exception as e:
            yield f"[Error]: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/resume")
async def resume(decision: dict):
    config = {"configurable": {"thread_id": "user_1"}}

    try:
        result = agent.invoke(
            Command(resume=decision),  # ✅ must be dict
            config=config,
            version="v2"
        )

        response_text = ""
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                response_text = msg.content
                break

        return {"response": response_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# -------------------------
# Health Check
# -------------------------

@app.get("/")
def root():
    return {"status": "ARIA agent running", "version": "1.0.0"}


@app.get("/tools")
def list_tools():
    return {
        "tools": [
            {"name": "web_search", "description": "Search the internet"},
            {"name": "send_email", "description": "Send an email"},
            {"name": "schedule_task", "description": "Schedule a task"},
            {"name": "get_weather", "description": "Get weather for a location"},
            {"name": "summarize_url", "description": "Summarize a webpage"},
            {"name": "calculate", "description": "Evaluate a math expression"},
        ]
    }
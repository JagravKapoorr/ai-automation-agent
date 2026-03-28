# 🤖 AI Automation Agent with Human-in-the-Loop (HITL)

An intelligent AI agent built using FastAPI, LangChain, and LangGraph that can perform real-world actions like sending emails and scheduling tasks — with a built-in Human-in-the-Loop (HITL) approval system for safety and control.

---

## 🚀 Features

- 🧠 AI Agent with tool-calling capabilities
- ✉️ Send emails via natural language commands
- ⏰ Schedule tasks intelligently
- 🌐 Web search and data retrieval
- ⚡ Real-time streaming responses
- 🔐 Human-in-the-Loop (HITL) approval system
- 🔄 Resumable workflows using LangGraph
- 💻 Interactive frontend for approvals (Approve / Reject / Edit)

---

## 🧠 How It Works

1. User sends a request (e.g., "Send an email to John")
2. Agent processes intent and prepares tool action
3. HITL Middleware pauses execution
4. User reviews action:
   - ✅ Approve
   - ❌ Reject
5. Agent resumes execution based on decision

---

## 🏗️ Tech Stack

### Backend
- FastAPI
- LangChain
- LangGraph
- Python

### Frontend
- React.js
- Tailwind CSS

### AI & Tools
- LLM (Groq / OpenAI compatible)
- Tool Calling
- Streaming APIs

---

## ⚙️ Architecture

- Agent-based system using LangGraph stateful workflows
- Middleware-driven human approval layer
- Checkpointing for resumable execution
- Modular tool integration

---

## 📸 Demo Flow

```text
User → AI Agent → Tool Intent → Approval → Execute
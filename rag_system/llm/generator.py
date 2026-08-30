from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage
#from langchain.memory import ChatMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from rag_system.config import settings


# Initialize the LLM once
llm = ChatOllama(
    temperature=0,
    base_url=settings.OLLAMA_BASE_URL,
    model=settings.LLM_MODEL_NAME,
    num_predict=settings.GEN_MAX_TOKENS,
)

# Define the Prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an expert data provenance assistant.
Use the provided graph context and the conversation history to answer the question factually and precisely.
Keep the answer short.
Do not repeat previous answers unless explicilty asked.
If the answer is not explicitly supported by the context, reply "I don't know"."""),
    
    MessagesPlaceholder(variable_name="history"),
    ("human", "Question: {input}\n\nGraph Context:\n{context}")
])

# Core chain
runnable = prompt | llm

# In-memory storage for chat histories
_session_stores = {}


def get_history(session_id: str):
    """
    Get the message history for a session. Returns list of messages.
    Creates a new history if it doesn't exist.
    """
    if session_id not in _session_stores:
        _session_stores[session_id] = ChatMessageHistory()
    
        # Get the complete history for the session
    history = _session_stores[session_id]
    
    # Calculate the maximum number of individual messages to keep
    max_messages = settings.CHAT_HISTORY_WINDOW_SIZE * 2
    
    # Return only the last `max_messages` from the list
    return history.messages[-max_messages:]


def add_to_history(session_id: str, user_message: str, ai_message: str):
    """
    Add a user-AI exchange to the session history.
    """
    if session_id not in _session_stores:
        _session_stores[session_id] = ChatMessageHistory()
    
    _session_stores[session_id].add_user_message(user_message)
    _session_stores[session_id].add_ai_message(ai_message)


def clear_history(session_id: str):
    """
    Clear the history for a specific session.
    """
    if session_id in _session_stores:
        _session_stores[session_id].clear()


def get_all_sessions():
    """
    Get list of all active session IDs.
    """
    return list(_session_stores.keys())
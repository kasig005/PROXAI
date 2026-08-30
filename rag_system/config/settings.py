import os
from KEY import MY_KEY

# --- Project Root Calculation ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Neo4j Configuration ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "adminadmin")

# --- LLM Configuration (Ollama, local) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", MY_KEY)  # kept for backward compat; unused with Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")
GEN_MAX_TOKENS = 256

# --- Embedding Models & Parameters ---
# Node properties with textual info for embedding
TEXT_FIELDS = ["code", "context", "feature_name", "function_name", "instance", "name", "type", "value"] #"id"
# Text embedding model
TEXT_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# --- Node2Vec Parameters ---
NODE2VEC_DIM = 128
NODE2VEC_WALK_LENGTH = 40
NODE2VEC_ITERATIONS = 5
NODE2VEC_IN_OUT_FACTOR = 1.0
NODE2VEC_RETURN_FACTOR = 1.0
NODE2VEC_WINDOW_SIZE = 5

# --- FAISS Index Configuration ---
# Join the INDEX_PATH with our calculated PROJECT_ROOT
INDEX_PATH = os.path.join(PROJECT_ROOT, "faiss_indexes")
SEMANTIC_INDEX_FILE = os.path.join(INDEX_PATH, "semantic.idx")
STRUCTURAL_INDEX_FILE = os.path.join(INDEX_PATH, "structural.idx")
META_FILE = os.path.join(INDEX_PATH, "meta.pkl")

# --- Retrieval Configuration ---
TOP_K = 5
EXPAND_HOPS = 2
SEMANTIC_WEIGHT = 0.9
STRUCTURAL_WEIGHT = 0.1

# --- Chat Memory Conficuiration ---
CHAT_HISTORY_WINDOW_SIZE = 10
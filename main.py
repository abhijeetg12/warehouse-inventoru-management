# main.py
# Warehouse Inventory Management Chatbot System
# This system enables users to manage warehouse inventory through a conversational interface
# It connects to a MongoDB database with sectors, warehouses, and log data collections

from fastapi import FastAPI, HTTPException, Depends, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import pymongo
from pymongo import MongoClient
from bson import ObjectId, json_util
import json
from datetime import datetime
import threading
import os
import re
import logging
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationChain
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from collections import deque

# Dictionary to store user questions directly (simpler than relying on langchain memory)
user_questions = {}
user_responses = {}

# Setup logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Warehouse Inventory Chatbot API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "warehouse_inventory"

# Initialize MongoDB client
try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    # Test connection
    client.admin.command('ping')
    logger.info("Connected successfully to MongoDB")
except Exception as e:
    logger.error(f"MongoDB connection error: {str(e)}")
    raise

# Custom JSON encoder for ObjectId
class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)

# Function to convert MongoDB document to JSON
def document_to_json(document):
    if document is None:
        return None
    return json.loads(json_util.dumps(document))

# Pydantic Models
class Message(BaseModel):
    user_id: str
    content: str
    
class ChatbotResponse(BaseModel):
    response: str
    
class ConversationState(BaseModel):
    stage: str = "initial"
    warehouse_id: Optional[str] = None
    sector_id: Optional[str] = None
    pending_columns: List[Dict[str, Any]] = []
    current_column_index: int = 0
    log_data: Dict[str, Any] = Field(default_factory=lambda: {"day": datetime.now().isoformat()})

# Chat Memory and Conversation State
chat_memories = {}
conversation_states = {}

# Thread locks for memory and state access
memory_lock = threading.Lock()
state_lock = threading.Lock()

# Function to get user-specific memory
def get_user_memory(user_id: str):
    with memory_lock:
        if user_id not in chat_memories:
            chat_memories[user_id] = ConversationBufferMemory(return_messages=True)
        return chat_memories[user_id]
        
# Function to get user-specific conversation state
def get_conversation_state(user_id: str):
    with state_lock:
        if user_id not in conversation_states:
            conversation_states[user_id] = ConversationState()
        return conversation_states[user_id]

# Utility functions with improved matching
def parse_sector_id(sector_name, user_id):
    """Find sector ID by name for a specific user with improved matching"""
    try:
        object_id = ObjectId(user_id)
        logger.info(f"Looking for sector with name: '{sector_name}' and creator: {object_id}")
        
        # Try exact match first
        sector = db.sectors.find_one({
            "name": sector_name, 
            "creator": object_id, 
            "deleted": False
        })
        
        # If not found, try case-insensitive regex match
        if not sector:
            logger.info(f"Exact match not found, trying case-insensitive match")
            sector = db.sectors.find_one({
                "name": {"$regex": f"^{re.escape(sector_name)}$", "$options": "i"}, 
                "creator": object_id, 
                "deleted": False
            })
            
        # If still not found, try with just the number
        if not sector and sector_name.startswith("Sector "):
            sector_num = sector_name.replace("Sector ", "").strip()
            logger.info(f"Trying with just sector number: {sector_num}")
            
            # Find all sectors and filter by number
            all_sectors = list(db.sectors.find({"creator": object_id, "deleted": False}))
            for s in all_sectors:
                if s["name"].endswith(sector_num):
                    sector = s
                    break
        
        logger.info(f"Query result: {json.dumps(document_to_json(sector), indent=2) if sector else 'No sector found'}")
        
        if not sector:
            # Last resort: list all available sectors
            all_sectors = list(db.sectors.find({"creator": object_id, "deleted": False}))
            logger.info(f"No sector found. Available sectors for user: {[s['name'] for s in all_sectors]}")
            return None
            
        return sector["_id"]
    except Exception as e:
        logger.error(f"Error in parse_sector_id: {str(e)}")
        return None

def parse_warehouse_id(warehouse_name, sector_id, user_id):
    """Find warehouse ID by name within a sector for a specific user"""
    try:
        # Case-insensitive query for the warehouse name
        warehouse = db.warehouses.find_one({
            "name": {"$regex": f"^{re.escape(warehouse_name)}$", "$options": "i"}, 
            "sector": sector_id, 
            "creator": ObjectId(user_id)
        })
        
        logger.info(f"Warehouse query result: {document_to_json(warehouse)}")
        
        if not warehouse:
            return None
        return warehouse["_id"]
    except Exception as e:
        logger.error(f"Error in parse_warehouse_id: {str(e)}")
        return None

# Initialize LangChain components
def init_chatbot(user_id: str):
    memory = get_user_memory(user_id)
    prompt = PromptTemplate(
        input_variables=["history", "input"],
        template=CHATBOT_TEMPLATE
    )
    
    llm = ChatOpenAI(temperature=0.7)
    
    conversation = ConversationChain(
        llm=llm,
        verbose=True,
        memory=memory,
        prompt=prompt
    )
    
    return conversation

# Chatbot template
CHATBOT_TEMPLATE = """
You are a helpful AI assistant for a warehouse inventory management system. Your primary role is to help users manage their warehouse inventory across different sectors.

The database structure has:
1. Sectors collection: Contains business sectors created by users
2. Warehouses collection: Contains warehouses belonging to sectors with dynamic inventory columns
3. LogDatas collection: Stores inventory logs for warehouses

Rules:
- Users can only access sectors and warehouses they created
- Users can only add log data in their own warehouses
- For logging inventory, you should ask for values column by column

Current conversation:
{history}

Human's request: {input}

Respond in a helpful, conversational manner. If the request is about warehouses, sectors, or inventory, respond with accurate information based on the database. If asked about previous questions, mention them from the conversation history.
"""

# Database query functions
def get_user_sectors(user_id: str):
    """Retrieve all sectors created by a specific user"""
    try:
        sectors = list(db.sectors.find({"creator": ObjectId(user_id), "deleted": False}))
        logger.info(f"Found {len(sectors)} sectors for user {user_id}")
        return sectors
    except Exception as e:
        logger.error(f"Error retrieving sectors: {str(e)}")
        return []

def get_user_warehouses_in_sector(user_id: str, sector_id: ObjectId):
    """Retrieve all warehouses in a specific sector created by a user"""
    try:
        warehouses = list(db.warehouses.find({"creator": ObjectId(user_id), "sector": sector_id}))
        logger.info(f"Found {len(warehouses)} warehouses in sector {sector_id} for user {user_id}")
        return warehouses
    except Exception as e:
        logger.error(f"Error retrieving warehouses: {str(e)}")
        return []

def get_warehouse_columns(warehouse_id: ObjectId):
    """Retrieve columns structure for a specific warehouse"""
    try:
        warehouse = db.warehouses.find_one({"_id": warehouse_id})
        if not warehouse:
            return None
        return warehouse.get("columns", [])
    except Exception as e:
        logger.error(f"Error retrieving warehouse columns: {str(e)}")
        return None

def add_log_data(warehouse_id: ObjectId, user_id: str, log_data: Dict[str, Any]):
    """Add new log data for a specific warehouse"""
    try:
        log_entry = {
            "warehouse": warehouse_id,
            "creator": ObjectId(user_id),
            "logData": log_data
        }
        result = db.logdatas.insert_one(log_entry)
        logger.info(f"Added log entry with ID: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error adding log data: {str(e)}")
        return None

# Intent detection with improved patterns
def detect_intent(message: str):
    """Detect user intent from message with improved patterns"""
    message = message.lower()
    logger.info(f"Detecting intent from message: '{message}'")
    
    # Check for sector list request
    if re.search(r"show\s+.*\s+sectors?\s+list", message) or re.search(r"list\s+.*\s+sectors", message):
        logger.info(f"Detected intent: list_sectors")
        return "list_sectors"
    
    # Check for warehouses in sector request - improved pattern
    sector_match = re.search(r"warehouses?\s+in\s+sector\s+(\d+|[a-zA-Z]+\s*\d*)", message)
    if sector_match:
        sector_name = sector_match.group(1).strip()
        # Add "Sector" prefix if it's just a number
        if sector_name.isdigit():
            sector_name = f"Sector {sector_name}"
        logger.info(f"Detected intent: list_warehouses_in_sector, sector name: '{sector_name}'")
        return "list_warehouses_in_sector", sector_name
    
    # Check for adding new log - improved pattern
    log_match = re.search(r"add\s+.*\s+log\s+in\s+warehouse\s+(\d+|[a-zA-Z]+\s*\d*)\s+in\s+sector\s+(\d+|[a-zA-Z]+\s*\d*)", message)
    if log_match:
        warehouse_name = log_match.group(1).strip()
        sector_name = log_match.group(2).strip()
        
        # Add "Warehouse" prefix if it's just a number
        if warehouse_name.isdigit():
            warehouse_name = f"Warehouse {warehouse_name}"
            
        # Add "Sector" prefix if it's just a number
        if sector_name.isdigit():
            sector_name = f"Sector {sector_name}"
            
        logger.info(f"Detected intent: add_log, warehouse: '{warehouse_name}', sector: '{sector_name}'")
        return "add_log", warehouse_name, sector_name
    
    # Check for greeting or who are you
    if re.search(r"hello|hi|hey|greetings", message) or re.search(r"who\s+are\s+you", message):
        logger.info(f"Detected intent: greeting")
        return "greeting"
    
    # Check for previous questions
    if re.search(r"previous\s+questions|what\s+did\s+I\s+ask|what\s+were\s+my\s+questions", message):
        logger.info(f"Detected intent: previous_questions")
        return "previous_questions"
    
    # Default fallback
    logger.info(f"Detected intent: unknown")
    return "unknown"

@app.post("/chat", response_model=ChatbotResponse)
async def chat_endpoint(message: Message):
    user_id = message.user_id
    user_message = message.content
    
    logger.info(f"Processing chat request from user: {user_id}, message: '{user_message}'")
    
    # Initialize history tracking for this user if needed
    if user_id not in user_questions:
        user_questions[user_id] = deque(maxlen=10)  # Store last 10 questions
    if user_id not in user_responses:
        user_responses[user_id] = deque(maxlen=10)  # Store last 10 responses
    
    # Add current message to history (except if it's asking for history itself)
    if not user_message.lower().strip() in ["what were my previous questions?", "what did i ask before?"]:
        user_questions[user_id].append(user_message)
    
    # Get or initialize conversation state
    conversation_state = get_conversation_state(user_id)
    
    # Handle ongoing conversation flow for adding logs
    if conversation_state.stage == "collecting_inventory":
        try:
            # Parse user input as a number
            value = float(user_message.strip())
            
            # Get current column being processed
            current_column = conversation_state.pending_columns[conversation_state.current_column_index]
            data_index = current_column["dataIndex"]
            
            # Add the value to log data
            conversation_state.log_data[data_index] = value
            
            # Move to next column or complete the process
            conversation_state.current_column_index += 1
            
            # If all columns processed, save the log
            if conversation_state.current_column_index >= len(conversation_state.pending_columns):
                # Save log data to database
                add_log_data(
                    ObjectId(conversation_state.warehouse_id),
                    user_id,
                    conversation_state.log_data
                )
                
                # Reset conversation state
                conversation_state.stage = "initial"
                conversation_state.warehouse_id = None
                conversation_state.sector_id = None
                conversation_state.pending_columns = []
                conversation_state.current_column_index = 0
                conversation_state.log_data = {"day": datetime.now().isoformat()}
                
                response = "Thanks, your log has been added successfully."
            else:
                # Ask for the next column
                next_column = conversation_state.pending_columns[conversation_state.current_column_index]
                response = f"Thanks, now please provide inventory count for {next_column['title']}."
            
            # Store the response
            user_responses[user_id].append(response)
            return ChatbotResponse(response=response)
        except ValueError:
            response = "Please provide a valid number for the inventory count."
            user_responses[user_id].append(response)
            return ChatbotResponse(response=response)
    
    # Process normal message flow
    intent = detect_intent(user_message)
    
    if isinstance(intent, tuple):
        intent_name = intent[0]
        if intent_name == "list_warehouses_in_sector":
            sector_name = intent[1]
            logger.info(f"DEBUG: Trying to find sector with name: {sector_name}")
            logger.info(f"DEBUG: User ID: {user_id}")
            sector_id = parse_sector_id(sector_name, user_id)
            logger.info(f"DEBUG: Result sector_id: {sector_id}")
            
            if not sector_id:
                response = f"I couldn't find Sector {sector_name} in your account."
            else:
                warehouses = get_user_warehouses_in_sector(user_id, sector_id)
                if not warehouses:
                    response = f"You don't have any warehouses in Sector {sector_name}."
                else:
                    warehouse_names = [w["name"] for w in warehouses]
                    response = f"Warehouses in {sector_name} are: {', '.join(warehouse_names)}."
        
        elif intent_name == "add_log":
            warehouse_name, sector_name = intent[1], intent[2]
            sector_id = parse_sector_id(sector_name, user_id)
            
            if not sector_id:
                response = f"I couldn't find Sector {sector_name} in your account."
            else:
                warehouse_id = parse_warehouse_id(warehouse_name, sector_id, user_id)
                
                if not warehouse_id:
                    response = f"I couldn't find Warehouse {warehouse_name} in Sector {sector_name}."
                else:
                    # Get warehouse columns
                    columns = get_warehouse_columns(warehouse_id)
                    
                    # Filter out 'day' column
                    inventory_columns = [col for col in columns if col["dataIndex"] != "day"]
                    
                    if not inventory_columns:
                        response = f"This warehouse doesn't have any inventory columns defined."
                    else:
                        # Set up conversation state for column-by-column collection
                        conversation_state.stage = "collecting_inventory"
                        conversation_state.warehouse_id = str(warehouse_id)
                        conversation_state.sector_id = str(sector_id)
                        conversation_state.pending_columns = inventory_columns
                        conversation_state.current_column_index = 0
                        
                        # Ask for the first column
                        first_column = inventory_columns[0]
                        response = f"Please provide inventory count for {first_column['title']}."
    else:
        # Handle single string intents
        if intent == "list_sectors":
            sectors = get_user_sectors(user_id)
            if not sectors:
                response = "You haven't created any sectors yet."
            else:
                sector_names = [s["name"] for s in sectors]
                response = f"Your created sectors are: {', '.join(sector_names)}."
        
        elif intent == "greeting":
            response = "Hello! I'm your warehouse inventory assistant. I can help you manage sectors, warehouses, and inventory logs. What would you like to do today?"
        
        elif intent == "previous_questions":
            # Use our simple direct history mechanism
            try:
                if not user_questions.get(user_id) or len(user_questions[user_id]) == 0:
                    response = "You haven't asked me any questions yet."
                else:
                    # Format the messages - handle both lists and deques
                    previous_q = list(user_questions[user_id])
                    formatted_questions = [f"{i+1}. {q}" for i, q in enumerate(previous_q)]
                    response = "Your previous questions were:\n" + "\n".join(formatted_questions)
            except Exception as e:
                logger.error(f"Error retrieving previous questions: {str(e)}")
                response = "I encountered an issue while trying to recall our previous conversation."
        
        else:
            # Default response for unknown intent
            response = "I'm your warehouse inventory assistant. I can help with:\n- Showing your sectors list\n- Showing warehouses in a sector\n- Adding inventory logs\n\nCould you please phrase your request related to warehouse inventory management?"
    
    # Store the response
    user_responses[user_id].append(response)
    
    return ChatbotResponse(response=response)

@app.get("/test-sector/{user_id}/{sector_name}")
async def test_sector(user_id: str, sector_name: str):
    """Test endpoint to directly check sector access"""
    try:
        creator_id = ObjectId(user_id)
        sector = db.sectors.find_one({
            "name": {"$regex": f"^{re.escape(sector_name)}$", "$options": "i"},
            "creator": creator_id, 
            "deleted": False
        })
        
        if sector:
            return {"found": True, "sector": document_to_json(sector)}
        else:
            return {"found": False, "message": f"Sector {sector_name} not found for user {user_id}"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/test-warehouses/{user_id}/{sector_name}")
async def test_warehouses(user_id: str, sector_name: str):
    """Test endpoint to check warehouses in a sector"""
    try:
        sector_id = parse_sector_id(sector_name, user_id)
        if not sector_id:
            return {"found": False, "message": f"Sector {sector_name} not found for user {user_id}"}
            
        warehouses = get_user_warehouses_in_sector(user_id, sector_id)
        if warehouses:
            return {"found": True, "warehouses": document_to_json(warehouses)}
        else:
            return {"found": False, "message": f"No warehouses found in Sector {sector_name} for user {user_id}"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug-db")
async def debug_db():
    """Debug endpoint to check database state"""
    try:
        sectors = list(db.sectors.find())
        warehouses = list(db.warehouses.find())
        logs = list(db.logdatas.find())
        
        return {
            "sectors_count": len(sectors),
            "warehouses_count": len(warehouses),
            "logs_count": len(logs),
            "sample_sector": document_to_json(sectors[0]) if sectors else None,
            "sample_warehouse": document_to_json(warehouses[0]) if warehouses else None,
            "sample_log": document_to_json(logs[0]) if logs else None
        }
    except Exception as e:
        return {"error": str(e)}

# Root endpoint for health check
@app.get("/")
async def root():
    return {"status": "ok", "message": "Warehouse Inventory Chatbot API is running"}

# For local testing
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
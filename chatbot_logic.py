# chatbot_logic.py
import re
from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, List, Tuple, Union, Optional
from langchain.memory import ConversationBufferMemory
from langchain.prompts import PromptTemplate
from langchain.chains import ConversationChain
from langchain.chat_models import ChatOpenAI

from config import settings

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

class ChatbotLogic:
    """Handles the core logic for the warehouse chatbot"""
    
    def __init__(self, db):
        """Initialize the chatbot logic with database connection"""
        self.db = db
        
    def get_user_sectors(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve all sectors created by a specific user"""
        sectors = list(self.db.sectors.find({"creator": ObjectId(user_id), "deleted": False}))
        return sectors
    
    def get_user_warehouses_in_sector(self, user_id: str, sector_id: ObjectId) -> List[Dict[str, Any]]:
        """Retrieve all warehouses in a specific sector created by a user"""
        warehouses = list(self.db.warehouses.find({"creator": ObjectId(user_id), "sector": sector_id}))
        return warehouses
    
    def get_warehouse_columns(self, warehouse_id: ObjectId) -> Optional[List[Dict[str, Any]]]:
        """Retrieve columns structure for a specific warehouse"""
        warehouse = self.db.warehouses.find_one({"_id": warehouse_id})
        if not warehouse:
            return None
        return warehouse.get("columns", [])
    
    def add_log_data(self, warehouse_id: ObjectId, user_id: str, log_data: Dict[str, Any]) -> ObjectId:
        """Add new log data for a specific warehouse"""
        log_entry = {
            "warehouse": warehouse_id,
            "creator": ObjectId(user_id),
            "logData": log_data
        }
        result = self.db.logdatas.insert_one(log_entry)
        return result.inserted_id
    
    def parse_sector_id(sector_name, user_id):
        """Find sector ID by name for a specific user"""
        try:
            object_id = ObjectId(user_id)
            print(f"Successfully converted user_id to ObjectId: {object_id}")
            
            # Debug query parameters
            print(f"Looking for sector with name: {sector_name} and creator: {object_id}")
            
            sector = db.sectors.find_one({"name": sector_name, "creator": object_id, "deleted": False})
            print(f"Query result: {sector}")
            
            if not sector:
                return None
            return sector["_id"]
        except Exception as e:
            print(f"Error in parse_sector_id: {str(e)}")
            return None
    
    def parse_warehouse_id(self, warehouse_name: str, sector_id: ObjectId, user_id: str) -> Optional[ObjectId]:
        """Find warehouse ID by name within a sector for a specific user"""
        warehouse = self.db.warehouses.find_one({"name": warehouse_name, "sector": sector_id, "creator": ObjectId(user_id)})
        if not warehouse:
            return None
        return warehouse["_id"]
    
    def detect_intent(self, message: str) -> Union[str, Tuple[str, str], Tuple[str, str, str]]:
        """Detect user intent from message"""
        message = message.lower()
        
        # Check for sector list request
        if re.search(r"show\s+.*\s+sectors?\s+list", message) or re.search(r"list\s+.*\s+sectors", message):
            return "list_sectors"
        
        # Check for warehouses in sector request
        sector_match = re.search(r"warehouses?\s+in\s+sector\s+(\w+\s*\d*)", message)
        if sector_match:
            return "list_warehouses_in_sector", sector_match.group(1)
        
        # Check for adding new log
        log_match = re.search(r"add\s+.*\s+log\s+in\s+warehouse\s+(\w+\s*\d*)\s+in\s+sector\s+(\w+\s*\d*)", message)
        if log_match:
            return "add_log", log_match.group(1), log_match.group(2)
        
        # Check for greeting or who are you
        if re.search(r"hello|hi|hey|greetings", message) or re.search(r"who\s+are\s+you", message):
            return "greeting"
        
        # Check for previous questions
        if re.search(r"previous\s+questions|what\s+did\s+I\s+ask|what\s+were\s+my\s+questions", message):
            return "previous_questions"
        
        # Default fallback
        return "unknown"
    
    def init_chatbot(self, memory: ConversationBufferMemory) -> ConversationChain:
        """Initialize the chatbot with memory"""
        prompt = PromptTemplate(
            input_variables=["history", "input"],
            template=CHATBOT_TEMPLATE
        )
        
        llm = ChatOpenAI(temperature=settings.CHATBOT_TEMPERATURE)
        
        conversation = ConversationChain(
            llm=llm,
            verbose=True,
            memory=memory,
            prompt=prompt
        )
        
        return conversation
    
    def extract_previous_questions(self, history: str) -> List[str]:
        """Extract previous user questions from conversation history"""
        human_messages = re.findall(r"Human: (.*?)(?=AI:|$)", history, re.DOTALL)
        return [q.strip() for q in human_messages if q.strip()]
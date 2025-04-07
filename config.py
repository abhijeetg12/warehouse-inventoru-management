# config.py
import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    """Application settings"""
    # MongoDB configurations
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    DB_NAME: str = os.getenv("DB_NAME", "warehouse_inventory")
    
    # API configurations
    API_TITLE: str = "Warehouse Inventory Chatbot API"
    API_DESCRIPTION: str = "API for managing warehouse inventory through a chatbot interface"
    API_VERSION: str = "1.0.0"
    
    # Chatbot configurations
    CHATBOT_NAME: str = "Warehouse Assistant"
    CHATBOT_TEMPERATURE: float = 0.7
    
    # Security
    API_ALLOW_ORIGINS: list = ["*"]
    
    class Config:
        env_file = ".env"

# Create settings instance
settings = Settings()
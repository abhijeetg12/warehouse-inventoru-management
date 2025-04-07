# models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from bson import ObjectId

class PyObjectId(ObjectId):
    """Custom ObjectId type for Pydantic models"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")

class ColumnSchema(BaseModel):
    """Schema for warehouse inventory columns"""
    title: str
    dataIndex: str
    dataType: str

class SectorModel(BaseModel):
    """Schema for sectors collection"""
    id: Optional[PyObjectId] = Field(alias="_id")
    name: str
    creator: PyObjectId
    location: str
    deleted: bool = False

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class WarehouseModel(BaseModel):
    """Schema for warehouses collection"""
    id: Optional[PyObjectId] = Field(alias="_id")
    name: str
    creator: PyObjectId
    sector: PyObjectId
    columns: List[ColumnSchema]

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class LogDataModel(BaseModel):
    """Schema for logdatas collection"""
    id: Optional[PyObjectId] = Field(alias="_id")
    warehouse: PyObjectId
    creator: PyObjectId
    logData: Dict[str, Any]

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
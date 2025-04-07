# debug_mongodb.py
from pymongo import MongoClient
from bson import ObjectId
import json

# MongoDB connection
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "warehouse_inventory"

# Helper function to print MongoDB documents
def print_document(doc):
    # Convert ObjectId to string for printing
    if doc is None:
        print("No document found")
        return
    
    doc_copy = doc.copy()
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc_copy[key] = str(value)
    print(json.dumps(doc_copy, indent=2))

def main():
    # Connect to MongoDB
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        
        # Test the connection
        client.admin.command('ping')
        print("✅ Connected to MongoDB successfully")
        
        # Get collections
        sectors_count = db.sectors.count_documents({})
        warehouses_count = db.warehouses.count_documents({})
        logdatas_count = db.logdatas.count_documents({})
        
        print(f"\n📊 Database Overview:")
        print(f"- Sectors: {sectors_count}")
        print(f"- Warehouses: {warehouses_count}")
        print(f"- LogDatas: {logdatas_count}")
        
        # Test user IDs
        user_id_1 = "65cb123456789abcd000a001"
        user_id_2 = "65cb123456789abcd000a002"
        
        # Check sectors for user 1
        print(f"\n🔍 Testing sectors for user {user_id_1}:")
        user1_sectors = list(db.sectors.find({"creator": ObjectId(user_id_1), "deleted": False}))
        print(f"- Found {len(user1_sectors)} sectors")
        for i, sector in enumerate(user1_sectors):
            print(f"\n  Sector {i+1}:")
            print_document(sector)
        
        # Check sectors for user 2
        print(f"\n🔍 Testing sectors for user {user_id_2}:")
        user2_sectors = list(db.sectors.find({"creator": ObjectId(user_id_2), "deleted": False}))
        print(f"- Found {len(user2_sectors)} sectors")
        for i, sector in enumerate(user2_sectors):
            print(f"\n  Sector {i+1}:")
            print_document(sector)
        
        # Direct test for Sector 1
        print(f"\n🔍 Directly testing 'Sector 1' lookup:")
        # Test exact match
        sector1_exact = db.sectors.find_one({"name": "Sector 1", "creator": ObjectId(user_id_1), "deleted": False})
        print("- Exact match result:")
        print_document(sector1_exact)
        
        # Test case-insensitive match
        import re
        sector1_regex = db.sectors.find_one({"name": {"$regex": "^Sector 1$", "$options": "i"}, "creator": ObjectId(user_id_1), "deleted": False})
        print("\n- Regex case-insensitive match result:")
        print_document(sector1_regex)
        
        # Test just by ID
        sector_by_id = db.sectors.find_one({"_id": ObjectId("65cba1a123456789abcd0001")})
        print("\n- Lookup by ID result:")
        print_document(sector_by_id)
        
        # Test without creator filter
        sectors_named_1 = list(db.sectors.find({"name": "Sector 1"}))
        print(f"\n- Sectors named 'Sector 1' (without creator filter): {len(sectors_named_1)}")
        for sector in sectors_named_1:
            print_document(sector)
        
        # Test warehouses for Sector 1
        if sector1_exact:
            warehouses = list(db.warehouses.find({"sector": sector1_exact["_id"]}))
            print(f"\n📦 Warehouses in Sector 1: {len(warehouses)}")
            for i, warehouse in enumerate(warehouses):
                print(f"\n  Warehouse {i+1}:")
                print_document(warehouse)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    finally:
        # Close the connection
        if 'client' in locals():
            client.close()
            print("\n🔒 MongoDB connection closed")

if __name__ == "__main__":
    main()
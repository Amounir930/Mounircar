import os
import re
import json
import pandas as pd
import pymongo

def get_mongo_client():
    uri = "mongodb://localhost:27017/"
    
    # Try to load MONGODB_URI from .env first
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("MONGODB_URI="):
                        uri = line.strip().split("MONGODB_URI=", 1)[1].strip()
                        return pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000), uri
        except Exception as e:
            print(f"Warning: could not read .env: {e}")
            
    # Fallback to mongodb_config.json if it exists
    config_path = "mongodb_config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                uri = config.get("mongodb_uri", uri)
        except Exception as e:
            print(f"Warning: could not read mongodb_config.json: {e}")
            
    return pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000), uri


EXCEL_FILE = "Data.xlsx"
OUTPUT_DIR = os.path.join("static", "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "data.json")

def clean_card_number(val):
    if pd.isnull(val):
        return ""
    val_str = str(val).strip()
    if val_str.endswith('.0'):
        val_str = val_str[:-2]
    return val_str

def extract_product(description):
    desc_str = str(description).lower()
    if '92' in desc_str:
        return 'بنزين 92'
    elif '95' in desc_str:
        return 'بنزين 95'
    elif '80' in desc_str:
        return 'بنزين 80'
    elif 'سولار' in desc_str or 'ديزل' in desc_str:
        return 'سولار'
    return 'وقود أخرى'

def clean_plate(plate):
    if pd.isnull(plate):
        return ""
    plate_str = str(plate).strip()
    match = re.search(r'[\u0600-\u06FF]', plate_str)
    if match:
        idx = match.start()
        before = plate_str[:idx]
        after = plate_str[idx:]
        after = after.replace('0', ' ')
        full = before + after
        full = re.sub(r'\s+', ' ', full).strip()
        return full
    return plate_str

def main():
    if not os.path.exists(EXCEL_FILE):
        print(f"Error: {EXCEL_FILE} not found. Please put your Excel file in the directory.")
        return

    print(f"Reading {EXCEL_FILE}...")
    try:
        df = pd.read_excel(EXCEL_FILE)
        
        # Clean columns
        df['رقم السيارة'] = df['رقم السيارة'].astype(str).str.strip()
        df['الادارة التشغيل'] = df['الادارة التشغيل'].astype(str).str.strip()
        df['اسم المحطة'] = df['اسم المحطة'].astype(str).str.strip()
        df['الوصف'] = df['الوصف'].astype(str).str.strip()
        df['الماركة'] = df['الماركة'].fillna('').astype(str).str.strip()
        
        # Clean movement number
        df['رقم حركة الصرف'] = df['رقم حركة الصرف'].fillna('').astype(str).str.strip().apply(lambda x: x[:-2] if x.endswith('.0') else x)
        
        # Normalize numeric columns
        df['كمية الصرف'] = pd.to_numeric(df['كمية الصرف'], errors='coerce').fillna(0.0)
        df['قيمة الصرف جم'] = pd.to_numeric(df['قيمة الصرف جم'], errors='coerce').fillna(0.0)
        
        # Format datetime
        df['تاريخ حركة الصرف'] = pd.to_datetime(df['تاريخ حركة الصرف'], errors='coerce')
        
        # Build clean records list
        records = []
        for _, row in df.iterrows():
            date_str = "غير محدد"
            if pd.notnull(row['تاريخ حركة الصرف']):
                date_str = row['تاريخ حركة الصرف'].strftime('%Y-%m-%d %H:%M:%S')
                
            desc = row['الوصف']
            product = extract_product(desc)
            
            plate = clean_plate(row['رقم السيارة'])
            if not plate or plate == 'nan' or plate == '':
                continue
                
            records.append({
                'plate': plate,
                'brand': row['الماركة'],
                'description': desc,
                'product': product,
                'date': date_str,
                'movement_number': row['رقم حركة الصرف'],
                'quantity': float(row['كمية الصرف']),
                'value': float(row['قيمة الصرف جم']),
                'department': row['الادارة التشغيل'],
                'station': row['اسم المحطة']
            })
            
        # Create output dir if not exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Save records as JSON (as fallback/cache)
        try:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            print(f"Success! Converted {len(records)} records. Saved to local {OUTPUT_FILE}.")
        except Exception as json_err:
            print(f"Warning: could not write local data.json: {json_err}")
            
        # MongoDB Connection and Data Sync
        mongo_connected = False
        db = None
        try:
            client, mongo_uri = get_mongo_client()
            db = client["fuel_db"]
            transactions_col = db["transactions"]
            
            # Clear old transactions and insert new
            transactions_col.delete_many({})
            if records:
                transactions_col.insert_many(records)
                
            # Create indexes for optimized searches
            transactions_col.create_index("plate")
            transactions_col.create_index("department")
            
            print(f"Success! Sync completed: Imported {len(records)} records into MongoDB at {mongo_uri}")
            mongo_connected = True
        except Exception as me:
            print(f"Warning: Could not sync records to MongoDB: {me}")
            
        # Passwords management
        passwords_file = os.path.join(OUTPUT_DIR, "passwords.json")
        passwords = {"admin": "admin123"}
        
        # 1. Read existing local passwords
        if os.path.exists(passwords_file):
            try:
                with open(passwords_file, 'r', encoding='utf-8') as pf:
                    passwords = json.load(pf)
            except Exception as pe:
                print(f"Warning: could not read existing local passwords: {pe}")
                
        # 2. Merge/Sync with MongoDB passwords if connected
        if mongo_connected and db is not None:
            try:
                credentials_col = db["credentials"]
                settings_col = db["settings"]
                
                # Fetch passwords from MongoDB
                mongo_passwords = {}
                for doc in credentials_col.find():
                    mongo_passwords[doc["_id"]] = doc["password"]
                    
                # Fetch blocked list from MongoDB
                deleted_doc = settings_col.find_one({"_id": "blocked_departments"})
                mongo_deleted = deleted_doc.get("list", []) if deleted_doc else []
                
                # Merge: MongoDB takes precedence, but keep anything local not in MongoDB
                for key, val in mongo_passwords.items():
                    passwords[key] = val
                
                # Merge deleted list
                if "_deleted" not in passwords:
                    passwords["_deleted"] = []
                for d in mongo_deleted:
                    if d not in passwords["_deleted"]:
                        passwords["_deleted"].append(d)
            except Exception as me:
                print(f"Warning: Could not sync passwords from MongoDB: {me}")
                
        # Get list of explicitly deleted/blocked departments
        deleted_depts = passwords.get('_deleted', [])
        if not isinstance(deleted_depts, list):
            deleted_depts = []
            
        depts = set(r['department'] for r in records if r['department'] and r['department'] != 'nan')
        updated_pw = False
        for d in depts:
            if d not in passwords and d not in deleted_depts:
                passwords[d] = "123456"
                updated_pw = True
                
        # Save passwords locally
        if updated_pw or not os.path.exists(passwords_file):
            try:
                with open(passwords_file, 'w', encoding='utf-8') as pf:
                    json.dump(passwords, pf, ensure_ascii=False, indent=2)
                print(f"Local passwords list updated at {passwords_file}.")
            except Exception as pe:
                print(f"Warning: could not write local passwords: {pe}")
                
        # Save passwords to MongoDB if connected
        if mongo_connected and db is not None:
            try:
                credentials_col = db["credentials"]
                settings_col = db["settings"]
                
                # Save credentials
                for key, val in passwords.items():
                    if not key.startswith('_'):
                        credentials_col.update_one({"_id": key}, {"$set": {"password": val}}, upsert=True)
                        
                # Save deleted list
                settings_col.update_one(
                    {"_id": "blocked_departments"},
                    {"$set": {"list": deleted_depts}},
                    upsert=True
                )
                print("Passwords and settings synchronized in MongoDB.")
            except Exception as me:
                print(f"Error saving passwords to MongoDB: {me}")
            
    except Exception as e:
        print(f"Error converting file: {e}")

if __name__ == '__main__':
    main()

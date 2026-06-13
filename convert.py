import os
import re
import json
import pymongo
import pandas as pd


def get_mongo_client():
    """Get MongoDB client — always from environment variable MONGODB_URI."""
    uri = os.environ.get("MONGODB_URI", "")
    if not uri:
        # Only for local dev: try to read from .env file
        env_path = ".env"
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("MONGODB_URI="):
                            uri = line.strip().split("MONGODB_URI=", 1)[1].strip()
                            break
            except Exception as e:
                print(f"Warning: could not read .env: {e}")
    if not uri:
        raise RuntimeError("MONGODB_URI is not set. Configure it as an environment variable on Vercel.")
    return pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000), uri


EXCEL_FILE = "Data.xlsx"


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


def main(excel_file=None, raise_on_error=False):
    if excel_file is None:
        excel_file = EXCEL_FILE

    if not os.path.exists(excel_file):
        msg = f"Error: {excel_file} not found."
        print(msg)
        if raise_on_error:
            raise FileNotFoundError(msg)
        return

    print(f"Reading {excel_file}...")
    try:
        df = pd.read_excel(excel_file)

        # Clean columns
        df['رقم السيارة']       = df['رقم السيارة'].astype(str).str.strip()
        df['الادارة التشغيل']   = df['الادارة التشغيل'].astype(str).str.strip()
        df['اسم المحطة']        = df['اسم المحطة'].astype(str).str.strip()
        df['الوصف']             = df['الوصف'].astype(str).str.strip()
        df['الماركة']           = df['الماركة'].fillna('').astype(str).str.strip()
        df['رقم حركة الصرف']   = (df['رقم حركة الصرف'].fillna('').astype(str).str.strip()
                                    .apply(lambda x: x[:-2] if x.endswith('.0') else x))
        df['كمية الصرف']        = pd.to_numeric(df['كمية الصرف'], errors='coerce').fillna(0.0)
        df['قيمة الصرف جم']     = pd.to_numeric(df['قيمة الصرف جم'], errors='coerce').fillna(0.0)
        df['تاريخ حركة الصرف'] = pd.to_datetime(df['تاريخ حركة الصرف'], errors='coerce')

        # Build records
        records = []
        for _, row in df.iterrows():
            date_str = "غير محدد"
            if pd.notnull(row['تاريخ حركة الصرف']):
                date_str = row['تاريخ حركة الصرف'].strftime('%Y-%m-%d %H:%M:%S')

            plate = clean_plate(row['رقم السيارة'])
            if not plate or plate == 'nan':
                continue

            records.append({
                'plate':           plate,
                'brand':           row['الماركة'],
                'description':     row['الوصف'],
                'product':         extract_product(row['الوصف']),
                'date':            date_str,
                'movement_number': row['رقم حركة الصرف'],
                'quantity':        float(row['كمية الصرف']),
                'value':           float(row['قيمة الصرف جم']),
                'department':      row['الادارة التشغيل'],
                'station':         row['اسم المحطة']
            })

        print(f"Converted {len(records)} records from Excel.")

        # ── MongoDB Sync ──────────────────────────────────────────────────
        try:
            client, mongo_uri = get_mongo_client()
            db = client["fuel_db"]

            # Sync transactions
            transactions_col = db["transactions"]
            transactions_col.delete_many({})
            if records:
                transactions_col.insert_many(records)
            transactions_col.create_index("plate")
            transactions_col.create_index("department")
            print(f"Imported {len(records)} records into MongoDB at {mongo_uri}")

            # Sync passwords: add new departments only
            credentials_col = db["credentials"]
            settings_col    = db["settings"]

            # Get blocked departments
            deleted_doc  = settings_col.find_one({"_id": "blocked_departments"})
            deleted_depts = deleted_doc.get("list", []) if deleted_doc else []

            # Get existing credential keys
            existing_keys = set(doc["_id"] for doc in credentials_col.find())

            # Add new departments with default password
            new_depts = set(r['department'] for r in records
                            if r['department'] and r['department'] != 'nan')
            for dept in new_depts:
                if dept not in existing_keys and dept not in deleted_depts:
                    credentials_col.insert_one({"_id": dept, "password": "123456"})

            print("Passwords synchronized in MongoDB.")

        except Exception as me:
            print(f"Error syncing to MongoDB: {me}")
            if raise_on_error:
                raise me

    except Exception as e:
        print(f"Error converting file: {e}")
        if raise_on_error:
            raise e


if __name__ == '__main__':
    main()

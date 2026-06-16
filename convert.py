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
    return pymongo.MongoClient(
        uri,
        serverSelectionTimeoutMS=8000,
        tlsAllowInvalidCertificates=True
    ), uri


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

    # ── Fetch existing odometers from MongoDB before any processing ──
    existing_odometers = {}
    try:
        client, mongo_uri = get_mongo_client()
        db = client["fuel_db"]
        transactions_col = db["transactions"]
        # Retrieve all transactions with non-empty odometer
        for doc in transactions_col.find({"odometer": {"$exists": True, "$ne": ""}}, {"movement_number": 1, "odometer": 1}):
            m_num = doc.get("movement_number")
            odo = doc.get("odometer")
            if m_num and odo:
                existing_odometers[str(m_num).strip()] = odo
        print(f"Loaded {len(existing_odometers)} existing odometer readings from MongoDB.")
    except Exception as e:
        print(f"Warning: Could not fetch existing odometer readings: {e}")

    print(f"Reading {excel_file}...")
    try:
        df = pd.read_excel(excel_file)

        # Detect serial number column
        serial_col = None
        for col in df.columns:
            col_cleaned = str(col).strip()
            if col_cleaned == 'م' or col_cleaned == 'مسلسل' or col_cleaned == 'التسلسل':
                serial_col = col
                break

        # Detect odometer column
        odometer_col = None
        for col in df.columns:
            col_cleaned = str(col).strip()
            if col_cleaned == 'قراءة العداد' or col_cleaned == 'العداد' or col_cleaned == 'قراءه العداد':
                odometer_col = col
                break

        # Clean required columns
        required_cols = ['رقم السيارة', 'الادارة التشغيل', 'اسم المحطة', 'الوصف', 'رقم حركة الصرف', 'كمية الصرف', 'قيمة الصرف جم', 'تاريخ حركة الصرف']
        for col in required_cols:
            if col not in df.columns:
                # Try fallback names or raise error
                raise KeyError(f"العمود المطلوب غير موجود في ملف الإكسيل: {col}")

        df['رقم السيارة']       = df['رقم السيارة'].astype(str).str.strip()
        df['الادارة التشغيل']   = df['الادارة التشغيل'].astype(str).str.strip()
        df['اسم المحطة']        = df['اسم المحطة'].astype(str).str.strip()
        df['الوصف']             = df['الوصف'].astype(str).str.strip()
        df['الماركة']           = df['الماركة'].fillna('').astype(str).str.strip() if 'الماركة' in df.columns else ''
        df['رقم حركة الصرف']   = (df['رقم حركة الصرف'].fillna('').astype(str).str.strip()
                                    .apply(lambda x: x[:-2] if x.endswith('.0') else x))
        df['كمية الصرف']        = pd.to_numeric(df['كمية الصرف'], errors='coerce').fillna(0.0)
        df['قيمة الصرف جم']     = pd.to_numeric(df['قيمة الصرف جم'], errors='coerce').fillna(0.0)
        df['تاريخ حركة الصرف'] = pd.to_datetime(df['تاريخ حركة الصرف'], errors='coerce')

        # Build records
        records = []
        for idx, row in df.iterrows():
            date_str = "غير محدد"
            if pd.notnull(row['تاريخ حركة الصرف']):
                date_str = row['تاريخ حركة الصرف'].strftime('%Y-%m-%d %H:%M:%S')

            plate = clean_plate(row['رقم السيارة'])
            if not plate or plate == 'nan':
                continue

            m_num = row['رقم حركة الصرف']
            m_num_str = str(m_num).strip()

            # Handle sequence (م)
            seq_val = None
            if serial_col is not None:
                val = row[serial_col]
                if pd.notnull(val):
                    try:
                        seq_val = int(float(val))
                    except:
                        pass
            if seq_val is None:
                seq_val = len(records) + 1

            # Handle odometer
            odo_val = ""
            if odometer_col is not None:
                val = row[odometer_col]
                if pd.notnull(val):
                    odo_val = str(val).strip()
                    if odo_val.endswith('.0'):
                        odo_val = odo_val[:-2]

            # Merge with existing odometer if blank in excel
            if not odo_val and m_num_str in existing_odometers:
                odo_val = existing_odometers[m_num_str]

            records.append({
                'seq':             seq_val,
                'plate':           plate,
                'brand':           row['الماركة'] if 'الماركة' in df.columns else '',
                'description':     row['الوصف'],
                'product':         extract_product(row['الوصف']),
                'date':            date_str,
                'movement_number': m_num_str,
                'quantity':        float(row['كمية الصرف']),
                'value':           float(row['قيمة الصرف جم']),
                'department':      row['الادارة التشغيل'],
                'station':         row['اسم المحطة'],
                'odometer':        odo_val
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
            transactions_col.create_index("movement_number", unique=True)
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

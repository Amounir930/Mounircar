import os
import json
import re
import pymongo
from flask import Flask, send_from_directory, redirect, url_for, request, jsonify

# Initialize Flask, serving static assets from /static
app = Flask(__name__, static_folder='static')

def get_mongo_client():
    # 1. Try system environment variables first (important for Vercel production)
    if "MONGODB_URI" in os.environ:
        uri = os.environ["MONGODB_URI"]
        return pymongo.MongoClient(uri, serverSelectionTimeoutMS=2000), uri

    uri = "mongodb://localhost:27017/"
    
    # Try to load MONGODB_URI from .env first
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("MONGODB_URI="):
                        uri = line.strip().split("MONGODB_URI=", 1)[1].strip()
                        return pymongo.MongoClient(uri, serverSelectionTimeoutMS=2000), uri
        except Exception as e:
            print(f"Warning: could not read .env in app.py: {e}")
            
    # Fallback to mongodb_config.json
    config_path = "mongodb_config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                uri = config.get("mongodb_uri", uri)
        except Exception as e:
            print(f"Warning: could not read mongodb_config.json in app.py: {e}")
            
    return pymongo.MongoClient(uri, serverSelectionTimeoutMS=2000), uri


@app.route('/')
def index():
    # Serve index.html from the root folder
    return send_from_directory('.', 'index.html')

@app.route('/login')
@app.route('/login.html')
def login():
    # Serve login.html from the root folder
    return send_from_directory('.', 'login.html')

@app.route('/admin')
@app.route('/admin.html')
def admin_page():
    # Serve admin.html from the root folder
    return send_from_directory('.', 'admin.html')

@app.route('/index.html')
def index_html():
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    return redirect(url_for('login'))

# API to get/update passwords
@app.route('/api/admin/passwords', methods=['GET', 'POST'])
def handle_passwords():
    passwords_file = os.path.join('static', 'data', 'passwords.json')
    
    # Check if MongoDB is connected
    db = None
    try:
        client, _ = get_mongo_client()
        db = client["fuel_db"]
    except Exception as e:
        print(f"Warning: Could not connect to MongoDB in handle_passwords: {e}")

    if request.method == 'GET':
        # Try to read from MongoDB first
        if db is not None:
            try:
                credentials_col = db["credentials"]
                settings_col = db["settings"]
                
                passwords = {}
                for doc in credentials_col.find():
                    passwords[doc["_id"]] = doc["password"]
                
                deleted_doc = settings_col.find_one({"_id": "blocked_departments"})
                if deleted_doc:
                    passwords["_deleted"] = deleted_doc.get("list", [])
                    
                if passwords:
                    try:
                        os.makedirs(os.path.dirname(passwords_file), exist_ok=True)
                        with open(passwords_file, 'w', encoding='utf-8') as f:
                            json.dump(passwords, f, ensure_ascii=False, indent=2)
                    except:
                        pass
                    return jsonify(passwords)
            except Exception as mongo_err:
                print(f"Warning: MongoDB error reading passwords: {mongo_err}")
                
        # Fallback to local file
        if not os.path.exists(passwords_file):
            return jsonify({"admin": "admin123"})
        try:
            with open(passwords_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif request.method == 'POST':
        try:
            new_passwords = request.json
            if not isinstance(new_passwords, dict):
                return jsonify({"error": "Invalid data format"}), 400
                
            # Make sure admin password is preserved if not provided
            if 'admin' not in new_passwords:
                new_passwords['admin'] = 'admin123'
                
            # 1. Write to local file first
            try:
                os.makedirs(os.path.dirname(passwords_file), exist_ok=True)
                with open(passwords_file, 'w', encoding='utf-8') as f:
                    json.dump(new_passwords, f, ensure_ascii=False, indent=2)
            except Exception as le:
                print(f"Warning: could not write passwords.json locally (read-only filesystem): {le}")
                
            # 2. Write to MongoDB if connected
            if db is not None:
                try:
                    credentials_col = db["credentials"]
                    settings_col = db["settings"]
                    
                    # Synchronize deletions
                    mongo_keys = [doc["_id"] for doc in credentials_col.find()]
                    for k in mongo_keys:
                        if k not in new_passwords:
                            credentials_col.delete_one({"_id": k})
                            
                    for key, val in new_passwords.items():
                        if not key.startswith('_'):
                            credentials_col.update_one({"_id": key}, {"$set": {"password": val}}, upsert=True)
                            
                    # Store blocked list
                    deleted_list = new_passwords.get("_deleted", [])
                    settings_col.update_one(
                        {"_id": "blocked_departments"},
                        {"$set": {"list": deleted_list}},
                        upsert=True
                    )
                except Exception as mongo_err:
                    print(f"Error saving passwords to MongoDB: {mongo_err}")
                    return jsonify({"success": True, "message": "تم حفظ كلمات المرور محلياً، وفشل المزامنة مع MongoDB."})
                    
            return jsonify({"success": True, "message": "تم حفظ كلمات المرور بنجاح."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# API to upload new Excel sheet and run conversion
@app.route('/api/admin/upload', methods=['POST'])
def handle_upload():
    if 'file' not in request.files:
        return jsonify({"error": "لم يتم تحديد أي ملف"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "اسم الملف فارغ"}), 400
        
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({"error": "يجب رفع ملف اكسيل فقط (.xlsx أو .xls)"}), 400
        
    try:
        # Save Excel file to the writable temporary directory (cross-platform)
        import tempfile
        temp_dir = tempfile.gettempdir()
        excel_path = os.path.join(temp_dir, "Data.xlsx")
        file.save(excel_path)
        
        # Programmatically run convert.py
        import convert
        import importlib
        importlib.reload(convert)
        convert.main(excel_path, raise_on_error=True)
        
        return jsonify({"success": True, "message": "تم رفع وتحديث ملف الاكسيل وقاعدة البيانات بنجاح!"})
    except Exception as e:
        return jsonify({"error": f"حدث خطأ أثناء حفظ الملف أو تحويله: {str(e)}"}), 500

# API to view/edit MongoDB connection URI settings
@app.route('/api/admin/mongodb_config', methods=['GET', 'POST'])
def handle_mongodb_config():
    config_path = "mongodb_config.json"
    env_path = ".env"
    
    if request.method == 'GET':
        # 1. Try to read from .env first
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("MONGODB_URI="):
                            uri = line.strip().split("MONGODB_URI=", 1)[1].strip()
                            return jsonify({"mongodb_uri": uri})
            except Exception as e:
                print(f"Warning: could not read .env: {e}")
                
        # 2. Fallback to mongodb_config.json
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return jsonify({"mongodb_uri": data.get("mongodb_uri", "")})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
                
        return jsonify({"mongodb_uri": "mongodb://localhost:27017/"})
        
    elif request.method == 'POST':
        try:
            data = request.json
            uri = data.get("mongodb_uri", "").strip()
            if not uri:
                return jsonify({"error": "يرجى إدخال رابط اتصال صالح"}), 400
                
            # Test connection to MongoDB
            test_client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=2000)
            test_client.server_info() # Will raise exception if connection fails
            
            # Save configuration to .env if writable
            try:
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write(f"MONGODB_URI={uri}\n")
            except Exception as env_err:
                print(f"Warning: could not write .env locally (read-only filesystem): {env_err}")
                
            # Delete old mongodb_config.json if it exists to clean up
            if os.path.exists(config_path):
                try:
                    os.remove(config_path)
                except:
                    pass
                
            return jsonify({"success": True, "message": "تم حفظ واختبار رابط اتصال MongoDB بنجاح في ملف .env المستبعد!"})
        except Exception as e:
            return jsonify({"error": f"فشل الاتصال بقاعدة البيانات: {str(e)}"}), 500

# API to get departments for login page dropdown selection
@app.route('/api/departments')
def get_departments():
    try:
        client, _ = get_mongo_client()
        db = client["fuel_db"]
        credentials_col = db["credentials"]
        
        keys = [doc["_id"] for doc in credentials_col.find()]
        depts = sorted([k for k in keys if k != 'admin' and not k.startswith('_')])
        if depts:
            return jsonify(depts)
    except Exception as e:
        print(f"Warning: MongoDB departments loading failed: {e}")
        
    # Fallback to local passwords.json
    passwords_file = os.path.join('static', 'data', 'passwords.json')
    if os.path.exists(passwords_file):
        try:
            with open(passwords_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            depts = sorted([k for k in data.keys() if k != 'admin' and not k.startswith('_')])
            return jsonify(depts)
        except:
            pass
    return jsonify([])

# API to securely verify user login credentials
@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.json
        department = data.get("department", "").strip()
        password = data.get("password", "").strip()
        
        if not department or not password:
            return jsonify({"error": "يرجى إدخال اسم الإدارة وكلمة المرور"}), 400
            
        correct_password = None
        
        # 1. Try MongoDB
        try:
            client, _ = get_mongo_client()
            db = client["fuel_db"]
            credentials_col = db["credentials"]
            doc = credentials_col.find_one({"_id": department})
            if doc:
                correct_password = doc.get("password")
        except Exception as mongo_err:
            print(f"Warning: MongoDB auth check failed: {mongo_err}")
            
        # 2. Try fallback to passwords.json
        if not correct_password:
            passwords_file = os.path.join('static', 'data', 'passwords.json')
            if os.path.exists(passwords_file):
                try:
                    with open(passwords_file, 'r', encoding='utf-8') as f:
                        passwords = json.load(f)
                    correct_password = passwords.get(department)
                except:
                    pass
                    
        # 3. Hardcoded admin fallback
        if not correct_password and department == "admin":
            correct_password = "admin123"
            
        if correct_password and password == correct_password:
            return jsonify({"success": True, "department": department})
        else:
            return jsonify({"error": "كلمة المرور غير صحيحة"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API for plate autocomplete search
@app.route('/api/search/autocomplete')
def autocomplete():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
        
    try:
        client, _ = get_mongo_client()
        db = client["fuel_db"]
        transactions_col = db["transactions"]
        
        # Build query for plates containing the substring (case-insensitive)
        query = {"plate": {"$regex": re.escape(q), "$options": "i"}}
        plates = transactions_col.distinct("plate", query)
        return jsonify(plates[:15])
    except Exception as e:
        print(f"Warning: Autocomplete fallback to local json: {e}")
        # Fallback to local data.json if MongoDB fails
        data_file = os.path.join('static', 'data', 'data.json')
        if os.path.exists(data_file):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Client-side filtering logic fallback
                unique_plates = list(set(tx["plate"] for tx in data if tx.get("plate")))
                matches = [p for p in unique_plates if q.lower() in p.lower()][:15]
                return jsonify(matches)
            except:
                pass
        return jsonify([])

# API for detailed Car Search and aggregations
@app.route('/api/search/car')
def search_car():
    plate = request.args.get('plate', '').strip()
    if not plate:
        return jsonify({"error": "يرجى تحديد رقم السيارة"}), 400
        
    try:
        client, _ = get_mongo_client()
        db = client["fuel_db"]
        transactions_col = db["transactions"]
        
        # Load from MongoDB
        txs = list(transactions_col.find({"plate": plate}, {"_id": 0}))
        
        if not txs:
            return jsonify({"error": "لم يتم العثور على أي حركة صرف لرقم السيارة المدخل."}), 404
            
        total_quantity = sum(tx["quantity"] for tx in txs)
        total_value = sum(tx["value"] for tx in txs)
        txs.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        depts = [tx["department"] for tx in txs if tx.get("department")]
        dominant_dept = max(set(depts), key=depts.count) if depts else "غير محدد"
        
        desc_groups = {}
        for tx in txs:
            desc = tx.get("description") or "بدون وصف"
            if desc not in desc_groups:
                desc_groups[desc] = {"quantity": 0.0, "value": 0.0}
            desc_groups[desc]["quantity"] += tx["quantity"]
            desc_groups[desc]["value"] += tx["value"]
            
        description_totals = [
            {"description": k, "quantity": v["quantity"], "value": v["value"]}
            for k, v in desc_groups.items()
        ]
        description_totals.sort(key=lambda x: x["quantity"], reverse=True)
        
        return jsonify({
            "transactions": txs,
            "total_quantity": total_quantity,
            "total_value": total_value,
            "dominant_department": dominant_dept,
            "description_totals": description_totals
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API for detailed Region/Department Search and aggregations
@app.route('/api/search/region')
def search_region():
    region = request.args.get('region', '').strip()
    if not region:
        return jsonify({"error": "يرجى تحديد المنطقة"}), 400
        
    try:
        client, _ = get_mongo_client()
        db = client["fuel_db"]
        transactions_col = db["transactions"]
        
        # Load from MongoDB
        txs = list(transactions_col.find({"department": region}, {"_id": 0}))
        
        if not txs:
            return jsonify({"error": "لم يتم العثور على أي حركات صرف لهذه المنطقة."}), 404
            
        total_quantity = sum(tx["quantity"] for tx in txs)
        total_value = sum(tx["value"] for tx in txs)
        txs.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        unique_plates = set(tx["plate"] for tx in txs if tx.get("plate"))
        vehicles_count = len(unique_plates)
        
        vehicle_groups = {}
        for tx in txs:
            desc = tx.get("description") or "بدون وصف كارت"
            if desc not in vehicle_groups:
                vehicle_groups[desc] = {
                    "description": desc,
                    "quantity": 0.0,
                    "value": 0.0,
                    "transactions": 0
                }
            vehicle_groups[desc]["quantity"] += tx["quantity"]
            vehicle_groups[desc]["value"] += tx["value"]
            vehicle_groups[desc]["transactions"] += 1
            
        vehicles_list = list(vehicle_groups.values())
        vehicles_list.sort(key=lambda x: x["quantity"], reverse=True)
        
        return jsonify({
            "transactions": txs,
            "total_quantity": total_quantity,
            "total_value": total_value,
            "vehicles_count": vehicles_count,
            "vehicles_list": vehicles_list
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("--------------------------------------------------")
    print("Starting Flask server at http://127.0.0.1:5000")
    print("Make sure you ran 'python convert.py' first.")
    print("--------------------------------------------------")
    app.run(host='0.0.0.0', port=5000, debug=True)

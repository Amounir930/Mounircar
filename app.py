import os
import re
import json
import tempfile
import pymongo
from flask import Flask, send_from_directory, redirect, url_for, request, jsonify

# Initialize Flask
app = Flask(__name__, static_folder='static')


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


def get_db():
    """Get the fuel_db database connection."""
    client, uri = get_mongo_client()
    return client["fuel_db"]


# ─── Page Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/login')
@app.route('/login.html')
def login():
    return send_from_directory('.', 'login.html')

@app.route('/admin')
@app.route('/admin.html')
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route('/index.html')
def index_html():
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    return redirect(url_for('login'))


# ─── Passwords API ───────────────────────────────────────────────────────────

@app.route('/api/admin/passwords', methods=['GET', 'POST'])
def handle_passwords():
    try:
        db = get_db()
    except Exception as e:
        return jsonify({"error": f"لم يتم الاتصال بقاعدة البيانات: {str(e)}"}), 500

    if request.method == 'GET':
        try:
            credentials_col = db["credentials"]
            settings_col    = db["settings"]
            passwords = {}
            for doc in credentials_col.find():
                passwords[doc["_id"]] = doc["password"]
            deleted_doc = settings_col.find_one({"_id": "blocked_departments"})
            if deleted_doc:
                passwords["_deleted"] = deleted_doc.get("list", [])
            if not passwords:
                passwords = {"admin": "admin123"}
            return jsonify(passwords)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif request.method == 'POST':
        try:
            new_passwords = request.json
            if not isinstance(new_passwords, dict):
                return jsonify({"error": "Invalid data format"}), 400
            if 'admin' not in new_passwords:
                new_passwords['admin'] = 'admin123'

            credentials_col = db["credentials"]
            settings_col    = db["settings"]

            # Sync deletions
            mongo_keys = [doc["_id"] for doc in credentials_col.find()]
            for k in mongo_keys:
                if k not in new_passwords:
                    credentials_col.delete_one({"_id": k})

            # Upsert all passwords
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
            return jsonify({"success": True, "message": "تم حفظ كلمات المرور بنجاح."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ─── Upload Excel ─────────────────────────────────────────────────────────────

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
        # Save to writable /tmp directory
        excel_path = os.path.join(tempfile.gettempdir(), "Data.xlsx")
        file.save(excel_path)

        # Run conversion — raise errors so we don't lie about success
        import convert
        import importlib
        importlib.reload(convert)
        result = convert.main(excel_path, raise_on_error=True)

        return jsonify({"success": True, "message": "تم رفع وتحديث ملف الاكسيل وقاعدة البيانات بنجاح!"})
    except Exception as e:
        return jsonify({"error": f"حدث خطأ أثناء التحويل أو المزامنة: {str(e)}"}), 500


# ─── MongoDB Config API ──────────────────────────────────────────────────────

@app.route('/api/admin/mongodb_config', methods=['GET', 'POST'])
def handle_mongodb_config():
    if request.method == 'GET':
        # Return the URI that is actually in use (from env var or .env file)
        uri = os.environ.get("MONGODB_URI", "")
        if not uri:
            env_path = ".env"
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("MONGODB_URI="):
                                uri = line.strip().split("MONGODB_URI=", 1)[1].strip()
                                break
                except Exception:
                    pass
        return jsonify({"mongodb_uri": uri or "غير مُعيَّن — أضف MONGODB_URI في Vercel Environment Variables"})

    elif request.method == 'POST':
        try:
            data = request.json
            uri = data.get("mongodb_uri", "").strip()
            if not uri:
                return jsonify({"error": "يرجى إدخال رابط اتصال صالح"}), 400

            # Test connection
            test_client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            test_client.server_info()

            # Try to persist locally (only works locally, not on Vercel)
            try:
                with open(".env", 'w', encoding='utf-8') as f:
                    f.write(f"MONGODB_URI={uri}\n")
            except Exception:
                pass

            return jsonify({"success": True, "message": "الاتصال ناجح! تأكد من إضافة MONGODB_URI في Vercel Environment Variables."})
        except Exception as e:
            return jsonify({"error": f"فشل الاتصال: {str(e)}"}), 500


# ─── Departments API ──────────────────────────────────────────────────────────

@app.route('/api/departments')
def get_departments():
    try:
        db = get_db()
        credentials_col = db["credentials"]
        keys = [doc["_id"] for doc in credentials_col.find()]
        depts = sorted([k for k in keys if k != 'admin' and not k.startswith('_')])
        return jsonify(depts)
    except Exception as e:
        print(f"Error loading departments: {e}")
        return jsonify([])


# ─── Login API ────────────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.json
        department = data.get("department", "").strip()
        password   = data.get("password", "").strip()
        if not department or not password:
            return jsonify({"error": "يرجى إدخال اسم الإدارة وكلمة المرور"}), 400

        # Admin hardcoded fallback
        if department == "admin" and password == "admin123":
            return jsonify({"success": True, "department": department})

        # Check MongoDB
        try:
            db = get_db()
            credentials_col = db["credentials"]
            doc = credentials_col.find_one({"_id": department})
            if doc and doc.get("password") == password:
                return jsonify({"success": True, "department": department})
        except Exception as mongo_err:
            print(f"Warning: MongoDB auth check failed: {mongo_err}")

        return jsonify({"error": "كلمة المرور غير صحيحة"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Autocomplete API ─────────────────────────────────────────────────────────

@app.route('/api/search/autocomplete')
def autocomplete():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    try:
        db = get_db()
        transactions_col = db["transactions"]
        query = {"plate": {"$regex": re.escape(q), "$options": "i"}}
        dept = request.args.get('department', '').strip()
        if dept:
            query["department"] = dept
        plates = transactions_col.distinct("plate", query)
        return jsonify(plates[:15])
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return jsonify([])


# ─── Car Search API ───────────────────────────────────────────────────────────

@app.route('/api/search/car')
def search_car():
    plate = request.args.get('plate', '').strip()
    if not plate:
        return jsonify({"error": "يرجى تحديد رقم السيارة"}), 400
    try:
        db = get_db()
        transactions_col = db["transactions"]
        query = {"plate": plate}
        dept = request.args.get('department', '').strip()
        if dept:
            query["department"] = dept
        txs = list(transactions_col.find(query, {"_id": 0}))
        if not txs:
            return jsonify({"error": "لم يتم العثور على أي حركة صرف لرقم السيارة المدخل."}), 404

        total_quantity = sum(tx["quantity"] for tx in txs)
        total_value    = sum(tx["value"] for tx in txs)
        txs.sort(key=lambda x: x.get("date", ""), reverse=True)

        depts = [tx["department"] for tx in txs if tx.get("department")]
        dominant_dept = max(set(depts), key=depts.count) if depts else "غير محدد"

        desc_groups = {}
        for tx in txs:
            desc = tx.get("description") or "بدون وصف"
            if desc not in desc_groups:
                desc_groups[desc] = {"quantity": 0.0, "value": 0.0}
            desc_groups[desc]["quantity"] += tx["quantity"]
            desc_groups[desc]["value"]    += tx["value"]

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


# ─── Region Search API ────────────────────────────────────────────────────────

@app.route('/api/search/region')
def search_region():
    region = request.args.get('region', '').strip()
    if not region:
        return jsonify({"error": "يرجى تحديد المنطقة"}), 400
    try:
        db = get_db()
        transactions_col = db["transactions"]
        txs = list(transactions_col.find({"department": region}, {"_id": 0}))
        if not txs:
            return jsonify({"error": "لم يتم العثور على أي حركات صرف لهذه المنطقة."}), 404

        total_quantity = sum(tx["quantity"] for tx in txs)
        total_value    = sum(tx["value"] for tx in txs)
        txs.sort(key=lambda x: x.get("date", ""), reverse=True)

        unique_plates  = set(tx["plate"] for tx in txs if tx.get("plate"))
        vehicle_groups = {}
        for tx in txs:
            desc = tx.get("description") or "بدون وصف كارت"
            if desc not in vehicle_groups:
                vehicle_groups[desc] = {"description": desc, "quantity": 0.0, "value": 0.0, "transactions": 0}
            vehicle_groups[desc]["quantity"]     += tx["quantity"]
            vehicle_groups[desc]["value"]        += tx["value"]
            vehicle_groups[desc]["transactions"] += 1

        vehicles_list = sorted(vehicle_groups.values(), key=lambda x: x["quantity"], reverse=True)

        return jsonify({
            "transactions": txs,
            "total_quantity": total_quantity,
            "total_value": total_value,
            "vehicles_count": len(unique_plates),
            "vehicles_list": vehicles_list
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("Starting Flask server at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)

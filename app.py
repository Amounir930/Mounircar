import os
import re
import json
import tempfile
import pymongo
import io
import pandas as pd
from flask import Flask, send_from_directory, redirect, url_for, request, jsonify, send_file

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

@app.route('/report')
@app.route('/report.html')
def report_page():
    return send_from_directory('.', 'report.html')

@app.route('/index.html')
def index_html():
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    return redirect(url_for('login'))


# ─── Passwords API ───────────────────────────────────────────────────────────

def get_all_passwords(db):
    """Retrieve all passwords, including fallbacks, and blocked/deleted list and last login dates."""
    credentials_col = db["credentials"]
    settings_col    = db["settings"]
    passwords = {}
    last_logins = {}
    
    for doc in credentials_col.find():
        passwords[doc["_id"]] = doc.get("password") or ""
        if "last_login" in doc:
            last_logins[doc["_id"]] = doc["last_login"]
            
    if not passwords.get("admin"):
        passwords["admin"] = "admin123"
    if not passwords.get("general"):
        passwords["general"] = "general123"

    deleted_doc = settings_col.find_one({"_id": "blocked_departments"})
    if deleted_doc:
        passwords["_deleted"] = deleted_doc.get("list", [])
        
    passwords["_last_login"] = last_logins
    return passwords


def save_all_passwords(db, new_passwords):
    """Save all passwords and update the blocked list."""
    if 'admin' not in new_passwords:
        new_passwords['admin'] = 'admin123'
    if 'general' not in new_passwords:
        new_passwords['general'] = 'general123'

    credentials_col = db["credentials"]
    settings_col    = db["settings"]

    for key, val in new_passwords.items():
        if not key.startswith('_'):
            credentials_col.update_one({"_id": key}, {"$set": {"password": val}}, upsert=True)

    deleted_list = new_passwords.get("_deleted", [])
    settings_col.update_one(
        {"_id": "blocked_departments"},
        {"$set": {"list": deleted_list}},
        upsert=True
    )


@app.route('/api/admin/passwords', methods=['GET', 'POST'])
def handle_passwords():
    try:
        db = get_db()
    except Exception as e:
        return jsonify({"error": f"لم يتم الاتصال بقاعدة البيانات: {str(e)}"}), 500

    if request.method == 'GET':
        try:
            return jsonify(get_all_passwords(db))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif request.method == 'POST':
        try:
            new_passwords = request.json
            if not isinstance(new_passwords, dict):
                return jsonify({"error": "Invalid data format"}), 400
            save_all_passwords(db, new_passwords)
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





# ─── Departments API ──────────────────────────────────────────────────────────

@app.route('/api/departments')
def get_departments():
    try:
        db = get_db()
        credentials_col = db["credentials"]
        keys = [doc["_id"] for doc in credentials_col.find()]
        
        # Filter active-only if requested (e.g. for login page)
        active_only = request.args.get('active_only', '').lower() == 'true'
        if active_only:
            settings_col = db["settings"]
            blocked_doc = settings_col.find_one({"_id": "blocked_departments"})
            blocked_depts = blocked_doc.get("list", []) if blocked_doc else []
            depts = sorted([k for k in keys if k not in ('admin', 'general') and k not in blocked_depts and not k.startswith('_')])
        else:
            depts = sorted([k for k in keys if k not in ('admin', 'general') and not k.startswith('_')])
            
        return jsonify(depts)
    except Exception as e:
        print(f"Error loading departments: {e}")
        return jsonify([])


# ─── Login API ────────────────────────────────────────────────────────────────

def is_department_blocked(db, department):
    """Check if the department is in the blocked list."""
    try:
        settings_col = db["settings"]
        blocked_doc = settings_col.find_one({"_id": "blocked_departments"})
        if blocked_doc and department in blocked_doc.get("list", []):
            return True
    except Exception as e:
        print(f"Warning: Block check failed: {e}")
    return False


def verify_credentials(db, department, password):
    """Verify if the credentials are valid (checks fallback first, then MongoDB)."""
    if department == "admin" and password == "admin123":
        return True
    if department == "general" and password == "general123":
        return True
        
    try:
        credentials_col = db["credentials"]
        doc = credentials_col.find_one({"_id": department})
        if doc and doc.get("password") == password:
            return True
    except Exception as e:
        print(f"Warning: MongoDB credentials check failed: {e}")
    return False


def format_arabic_datetime(dt):
    """Format datetime to include Arabic day name and 12-hour time format with ص/م."""
    arabic_weekdays = {
        0: "الإثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس",
        4: "الجمعة", 5: "السبت", 6: "الأحد"
    }
    weekday = arabic_weekdays.get(dt.weekday(), "")
    hour = dt.hour
    period = "م" if hour >= 12 else "ص"
    hour_12 = 12 if hour % 12 == 0 else hour % 12
    return f"{weekday} {dt.strftime('%Y-%m-%d')} {hour_12:02d}:{dt.minute:02d}:{dt.second:02d} {period}"


def update_last_login_time(db, department):
    """Updates the last login timestamp for the given department/user."""
    try:
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=3))
        last_login_time = format_arabic_datetime(datetime.now(tz))
        
        credentials_col = db["credentials"]
        update_query = {"$set": {"last_login": last_login_time}}
        
        if department == "admin":
            update_query["$setOnInsert"] = {"password": "admin123"}
        elif department == "general":
            update_query["$setOnInsert"] = {"password": "general123"}
            
        credentials_col.update_one(
            {"_id": department},
            update_query,
            upsert=True
        )
    except Exception as e:
        print(f"Warning: Failed to update login timestamp for {department}: {e}")


@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.json
        if not data or not isinstance(data, dict):
            return jsonify({"error": "بيانات غير صالحة"}), 400
            
        department = str(data.get("department", "")).strip()
        password   = str(data.get("password", "")).strip()
        if not department or not password:
            return jsonify({"error": "يرجى إدخال اسم الإدارة وكلمة المرور"}), 400

        db = get_db()
        
        # Check if department is blocked
        if is_department_blocked(db, department):
            return jsonify({"error": "هذا الحساب موقوف حالياً"}), 403

        if verify_credentials(db, department, password):
            update_last_login_time(db, department)
            return jsonify({"success": True, "department": department})

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
            desc = tx.get("description") or "بدون نوع الوقود المنصرف"
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


# ─── Odometer & Download API ──────────────────────────────────────────────────

@app.route('/api/transaction/odometer', methods=['POST'])
def update_odometer():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "يرجى إرسال البيانات المطلوبة"}), 400

        movement_number = data.get("movement_number", "").strip()
        odometer        = str(data.get("odometer", "")).strip()
        user_dept       = data.get("department", "").strip()

        if not movement_number:
            return jsonify({"error": "يرجى تحديد رقم الحركة"}), 400

        db = get_db()
        transactions_col = db["transactions"]

        # Verify transaction exists
        tx = transactions_col.find_one({"movement_number": movement_number})
        if not tx:
            return jsonify({"error": "الحركة غير موجودة"}), 404

        # Rule: If odometer is already set, it cannot be modified
        if tx.get("odometer"):
            return jsonify({"error": "عذراً، تم تسجيل قراءة العداد مسبقاً ولا يمكن تعديلها."}), 400

        # Authorization: if department user is logged in, they can only edit their own department's movements
        if user_dept and user_dept not in ('admin', 'general'):
            if tx.get("department") != user_dept:
                return jsonify({"error": "غير مصرح لك بتعديل قراءة عداد هذه الحركة التابعة لإدارة أخرى"}), 403

        # Update MongoDB
        transactions_col.update_one(
            {"movement_number": movement_number},
            {"$set": {"odometer": odometer}}
        )

        # Try updating the local Excel file in the background if it exists on disk
        try:
            local_path = "Data.xlsx"
            if os.path.exists(local_path):
                # We can read, update the specific row, and write it back.
                # However, since this is a quick action, it's safer to do this or log warning if it fails.
                df_disk = pd.read_excel(local_path)
                # Ensure the plate and odometer columns exist
                # If 'قراءة العداد' is not in columns, add it
                odo_col_name = 'قراءة العداد'
                for col in df_disk.columns:
                    if str(col).strip() == 'قراءة العداد':
                        odo_col_name = col
                        break
                if odo_col_name not in df_disk.columns:
                    df_disk[odo_col_name] = ""

                # Cast column to str
                df_disk[odo_col_name] = df_disk[odo_col_name].fillna("").astype(str)
                df_disk['رقم حركة الصرف'] = df_disk['رقم حركة الصرف'].fillna("").astype(str).apply(lambda x: x[:-2] if x.endswith('.0') else x)

                # Update row
                df_disk.loc[df_disk['رقم حركة الصرف'] == movement_number, odo_col_name] = odometer

                df_disk.to_excel(local_path, index=False)
                print(f"Successfully updated odometer for movement {movement_number} in local Data.xlsx.")
        except Exception as local_err:
            print(f"Warning: Could not update local Data.xlsx in place: {local_err}")

        return jsonify({"success": True, "message": "تم حفظ قراءة العداد بنجاح."})
    except Exception as e:
        return jsonify({"error": f"حدث خطأ أثناء التحديث: {str(e)}"}), 500


@app.route('/api/admin/download')
def download_updated_excel():
    try:
        db = get_db()
        transactions_col = db["transactions"]

        # Retrieve all transactions sorted by sequence number (seq)
        txs = list(transactions_col.find().sort("seq", 1))

        if not txs:
            return jsonify({"error": "لا توجد بيانات لتصديرها"}), 404

        # Build pandas DataFrame with exact original column order and names
        columns_mapping = [
            ('seq', 'م'),
            ('plate', 'رقم السيارة'),
            ('brand', 'الماركة'),
            ('description', 'الوصف'),
            ('date', 'تاريخ حركة الصرف'),
            ('movement_number', 'رقم حركة الصرف'),
            ('value', 'قيمة الصرف جم'),
            ('quantity', 'كمية الصرف'),
            ('department', 'الادارة التشغيل'),
            ('station', 'اسم المحطة'),
            ('odometer', 'قراءة العداد')
        ]

        data_list = []
        for tx in txs:
            row = {}
            for eng_key, ara_key in columns_mapping:
                val = tx.get(eng_key, "")
                if eng_key == 'date':
                    row[ara_key] = val
                elif eng_key in ('quantity', 'value'):
                    try:
                        row[ara_key] = float(val)
                    except:
                        row[ara_key] = val
                elif eng_key == 'seq':
                    try:
                        row[ara_key] = int(val)
                    except:
                        row[ara_key] = val
                else:
                    row[ara_key] = val
            data_list.append(row)

        df_out = pd.DataFrame(data_list)

        # Create in-memory file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_out.to_excel(writer, index=False, sheet_name='Sheet1')
        output.seek(0)

        # Try to sync back to the local Data.xlsx so it stays on disk
        try:
            local_path = "Data.xlsx"
            with open(local_path, "wb") as f:
                f.write(output.getvalue())
            print("Successfully synced memory state to local Data.xlsx.")
        except Exception as disk_err:
            print(f"Warning: Could not save Data.xlsx on disk: {disk_err}")

        # Return file download
        output.seek(0)
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="Data_Updated.xlsx"
        )
    except Exception as e:
        return jsonify({"error": f"حدث خطأ أثناء تصدير الملف: {str(e)}"}), 500


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("Starting Flask server at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)

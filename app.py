import os
import cups
from flask import Flask, request, jsonify, render_template_string
from flask_httpauth import HTTPBasicAuth
from werkzeug.utils import secure_filename
import time
from pypdf import PdfReader

app = Flask(__name__)
auth = HTTPBasicAuth()

# --- 1. security configurations ---
# maximum file upload size
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  

# only this formats are allowed
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'txt'}

# saving folder for uploaded file
# Get directory where app.py is located
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# UPLOAD_FOLDER = os.path.join(BASE_DIR, 'tmp', 'cups_uploads')
UPLOAD_FOLDER = '/tmp/print_buffer'

# Create directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- 2. set username and password ---
# set your username and password according to your preference
USER_DATA = {
    "admin": "SuperSecurePassword123"
}

# Helper function to get page count
def get_page_count(file_path):
    try:
        reader = PdfReader(file_path)
        return len(reader.pages)
    except Exception:
        return 1  # Default to 1 page for plain text/images

@auth.verify_password
def verify_password(username, password):
    if username in USER_DATA and USER_DATA[username] == password:
        return username
    return None

# check file extension
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- (HTML) interface---
HTML_INTERFACE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secure Wireless Printing</title>
    <style>
        body { font-family: 'Arial', sans-serif; background-color: #f4f7f6; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .container { background-color: #fff; padding: 30px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); text-align: center; max-width: 400px; width: 90%; }
        h2 { color: #333; margin-bottom: 20px; }
        input[type="file"] { display: none; }
        .custom-file-upload { border: 2px dashed #007bff; display: inline-block; padding: 20px; cursor: pointer; border-radius: 5px; color: #007bff; font-weight: bold; width: 80%; margin-bottom: 20px; }
        .custom-file-upload:hover { background-color: #e6f2ff; }
        button { background-color: #28a745; color: white; border: none; padding: 12px 24px; font-size: 16px; border-radius: 5px; cursor: pointer; width: 90%; }
        button:hover { background-color: #218838; }
        #status { margin-top: 20px; font-weight: bold; color: #555; }
        #file-name { margin-top: 5px; color: #666; font-size: 14px; }
    </style>
</head>
<body>

<div class="container">
    <h2>🔒 Secure Print Panel</h2>
    <p style="font-size:12px; color:#888;">Allowed: PDF, PNG, JPG, JPEG, TXT (Max 16MB)</p>
    <form id="upload-form" enctype="multipart/form-data">
        <label class="custom-file-upload">
            <input type="file" name="file" id="file-input" required/>
            Choose Document / Image
        </label>
        <div id="file-name"></div>
        <br>
        <button type="submit">Print Now</button>
    </form>
    <div id="status"></div>
</div>

<script>
    document.getElementById('file-input').addEventListener('change', function(e){
        if(e.target.files.length > 0) {
            var fileName = e.target.files[0].name;
            document.getElementById('file-name').textContent = "Selected: " + fileName;
        }
    });

    document.getElementById('upload-form').addEventListener('submit', function(e) {
        e.preventDefault();
        var formData = new FormData(this);
        var statusDiv = document.getElementById('status');
        statusDiv.style.color = '#007bff';
        statusDiv.textContent = 'Sending to printer... Please wait.';

        fetch('/print', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                statusDiv.style.color = '#dc3545';
                statusDiv.textContent = '❌ Error: ' + data.error;
            } else {
                statusDiv.style.color = '#28a745';
                statusDiv.textContent = '✅ Success! Job ID: ' + data.job_id + ' sent to ' + data.printer;
            }
        })
        .catch(error => {
            statusDiv.style.color = '#dc3545';
            statusDiv.textContent = '❌ Connection failed.';
        });
    });
</script>

</body>
</html>
"""

# home page (password protected)
@app.route('/')
# @auth.login_required
def home():
    return render_template_string(HTML_INTERFACE)

# API for printing (password)
@app.route('/print', methods=['POST'])
# @auth.login_required
def print_document():
    t_start = time.perf_counter()  # 1. Request arrival

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Check file format
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed! Use PDF, PNG, JPG, JPEG, or TXT."}), 400

    if file:
        f = request.files['file']
        filename = secure_filename(f.filename or 'printjob.pdf')
        file_path = os.path.join(UPLOAD_FOLDER, filename)

        # --- Phase 1: File Ingestion (Network Receive + RAM Disk Save) ---
        try:
            f.save(file_path)
        except Exception as e:
            return jsonify({'error': f'Failed to write file to disk: {str(e)}'}), 500

        t_ingest = time.perf_counter()  # End of Ingestion

        # --- Phase 2: File Parsing & Rendering ---
        # Optional: Inspect file / count pages here (e.g., using pypdf)
        # page_count = get_pdf_page_count(file_path)
        t_render = time.perf_counter()  # End of Rendering/Parsing

        # (Path Traversal)
        # filename = secure_filename(file.filename)
        # file_path = os.path.join(UPLOAD_FOLDER, filename)
        # file.save(file_path)

        file_exists = os.path.exists(file_path)

        # --- Phase 3: Hardware Dispatch via CUPS ---
        if file_exists:
            try:
                conn = cups.Connection()
                print("Cups connection established.")
                printer_name = conn.getDefault()
                
                if not printer_name:
                    printers = conn.getPrinters()
                    if printers:
                        printer_name = list(printers.keys())[0]
                    else:
                        return jsonify({"error": "No printers found on Linux"}), 500
                # TODO: We need a function to select idle printer...

                # CUPS
                # FIX: added index number 0 in printer_name
                print("Printer selected", printer_name)
                job_id = conn.printFile(printer_name, file_path, "Secure Mobile Job", {})
                print("Print job is done.", job_id)

                os.remove(file_path)

                t_dispatch = time.perf_counter()  # End of Dispatch

                # Calculate phase durations (in seconds)
                ingestion_time = t_ingest - t_start
                rendering_time = t_render - t_ingest
                dispatch_time = t_dispatch - t_render
                total_time = t_dispatch - t_start

                print(f"Ingestion: {ingestion_time:.3f}s | "
                      f"Rendering: {rendering_time:.3f}s | "
                      f"Dispatch: {dispatch_time:.3f}s | "
                      f"TOTAL: {total_time:.3f}s")

                # log the result to a file
                with open("print_log.txt", "a") as f:
                    f.write(f"Ingestion: {ingestion_time:.3f}s | "
                            f"Rendering: {rendering_time:.3f}s | "
                            f"Dispatch: {dispatch_time:.3f}s | "
                            f"TOTAL: {total_time:.3f}s\n")
                
                return jsonify({
                    "message": "Print job sent successfully",
                    "printer": printer_name,
                    "job_id": job_id,
                    "latency_breakdown": {
                        "ingestion_sec": round(ingestion_time, 4),
                        "rendering_sec": round(rendering_time, 4),
                        "dispatch_sec": round(dispatch_time, 4),
                        "total_sec": round(total_time, 4)
                    }
                }), 200
                
            except Exception as e:
                if os.path.exists(file_path):
                    os.remove(file_path)
                return jsonify({"error": f"CUPS Error: {str(e)}"}), 500
        else:
            # return jsonify({"error": f"File does not exists: {str(e)}"}), 500
            return jsonify({"error": "File failed to save to target path."}), 500

# API for getting printers
@app.route('/get-printers', methods=['GET'])
# @auth.login_required
def get_printers(): 
        try:
            conn = cups.Connection()
            printer_name = conn.getDefault()

            if not printer_name:
                printers = conn.getPrinters()
                if printers:
                    printer_name = list(printers.keys())
                else:
                    return jsonify({"error": "No printers found on Linux"}), 500
            
            return jsonify({
                "message": "Print job sent successfully",
                "printer": printer_name,
            }), 200
            
        except Exception as e:
            return jsonify({"error": f"CUPS Error: {str(e)}"}), 500

@app.route('/debug-upload', methods=['POST'])
def debug_upload():
    # 1. Inspect incoming files
    if 'file' not in request.files:
        return jsonify({'error': 'No "file" key in request.files', 'keys_received': list(request.files.keys())}), 400

    f = request.files['file']
    filename = secure_filename(f.filename or 'printjob.pdf')
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    # 2. Save
    try:
        f.save(filepath)
    except Exception as e:
        return jsonify({'error': f'Failed to write file to disk: {str(e)}'}), 500

    # 3. Verify
    file_exists = os.path.exists(filepath)
    file_size = os.path.getsize(filepath) if file_exists else 0

    return jsonify({
        'status': 'success',
        'saved_path': filepath,
        'exists_on_disk': file_exists,
        'bytes_written': file_size
    }), 200

# (Max Content Length Exceeded)
@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "File is too large! Maximum limit is 16MB."}), 413

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

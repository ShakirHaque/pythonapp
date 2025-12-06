from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS
import os
import fitz  # PyMuPDF for PDF
import docx  # python-docx for Word
import re
import requests
import bibtexparser  # For .bib files
from difflib import SequenceMatcher

app = Flask(__name__)

# ✅ Enable CORS for all routes and methods
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/', methods=['GET'])
def home():
    return "✅ Flask Reference Verifier is running!"

# --- File Extraction Functions (No Change) ---
def extract_references_from_pdf(file_path):
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    match = re.search(r'(references|bibliography)[\s\S]*', text, re.IGNORECASE)
    return match.group(0) if match else text[-2000:]

def extract_references_from_docx(file_path):
    doc = docx.Document(file_path)
    text = "\n".join(para.text for para in doc.paragraphs)
    match = re.search(r'(references|bibliography)[\s\S]*', text, re.IGNORECASE)
    return match.group(0) if match else text[-2000:]

def extract_references_from_tex(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()
    match = re.search(r'\\begin\{thebibliography\}[\s\S]*?\\end\{thebibliography\}', text)
    return match.group(0) if match else text[-2000:]

def load_bibtex_entries(file_path):
    with open(file_path, 'r') as bibfile:
        bib_database = bibtexparser.load(bibfile)
    return [entry['title'] for entry in bib_database.entries if 'title' in entry]

# --- Core Verification Logic Functions (No Change) ---
def search_reference_online(ref):
    query = '+'.join(ref.split())
    # Using a reliable crossref API URL format
    url = f"https://api.crossref.org/works?query.title={query}&rows=1" 
    try:
        response = requests.get(url, timeout=5) # Added timeout
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        if data['message']['items']:
            # Use the DOI as a reliable source identifier if URL is missing
            doi = data['message']['items'][0].get('DOI', 'Found, DOI not listed')
            return doi, True
        else:
            return 'Not found', False
    except requests.exceptions.RequestException as e:
        # Catch network errors and HTTP errors
        return f"Error connecting to CrossRef: {str(e)}", False
    except Exception as e:
        return f"General Error: {str(e)}", False

def detect_llm_generated(ref):
    # Simple heuristic: reference is too short or contains common LLM phrases
    if len(ref.split()) < 6 or SequenceMatcher(None, ref.lower(), 'this paper presents a method').ratio() > 0.6:
        return True
    return False

# --- File Verification Route (No Change) ---
def verify_references(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        refs_text = extract_references_from_pdf(file_path)
    elif ext == '.docx':
        refs_text = extract_references_from_docx(file_path)
    elif ext == '.tex':
        refs_text = extract_references_from_tex(file_path)
    elif ext == '.bib':
        references = load_bibtex_entries(file_path)
        refs_text = "\n".join(references)
    else:
        return [{"error": "Unsupported file type"}]

    # Splitting into individual references: lines longer than 20 chars
    refs = [line.strip() for line in refs_text.split('\n') if len(line.strip()) > 20]
    results = []
    for ref in refs:
        source, found = search_reference_online(ref)
        is_llm = detect_llm_generated(ref)
        results.append({
            'reference': ref,
            'source_found': source,
            'is_llm_generated': is_llm
        })
    return results

@app.route('/verify', methods=['POST', 'OPTIONS'])
def verify():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'CORS preflight'}), 200

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    uploaded_file = request.files['file']
    filename = secure_filename(uploaded_file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    uploaded_file.save(filepath)

    results = verify_references(filepath)
    
    # Clean up the file after processing
    try:
        os.remove(filepath)
    except Exception as e:
        print(f"Error removing file {filepath}: {e}")
        
    return jsonify(results)

# --- TEXT Verification Route (CORRECTED) ---
@app.route('/verify_text', methods=['POST', 'OPTIONS']) # <-- CORRECTED ENDPOINT NAME
def verify_text(): # <-- Corrected function name convention
    if request.method == 'OPTIONS':
        return jsonify({'message': 'CORS preflight'}), 200

    data = request.get_json()
    
    # Flutter sends the key 'text' containing the entire block of references
    if not data or 'text' not in data: 
        return jsonify({'error': 'JSON payload must contain the key "text"'}), 400

    input_text = data['text'].strip()
    
    # 1. Split the entire text block into individual references 
    # (using the same logic as verify_references: lines > 20 chars)
    refs = [line.strip() for line in input_text.split('\n') if len(line.strip()) > 20]
    
    if not refs:
        return jsonify({'error': 'No valid references found in the input text (Min 20 characters per line)'}), 400

    results = []
    
    # 2. Iterate through all references and verify each one
    for ref in refs:
        source, found = search_reference_online(ref)
        is_llm = detect_llm_generated(ref)

        results.append({
            'reference': ref,
            'source_found': source,
            'is_llm_generated': is_llm
        })
        
    return jsonify(results) # Return the list of all results

# --- PING Route (No Change) ---
@app.route('/ping', methods=['POST', 'OPTIONS'])
def ping():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'CORS preflight'}), 200
    return jsonify({"message": "pong"})

if __name__ == '__main__':
    # Set thread=False for production/Render compatibility
    app.run(host='0.0.0.0', debug=True, port=os.environ.get('PORT', 5002))

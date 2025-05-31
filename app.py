from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS  # ✅ CORS import
import os
import fitz  # PyMuPDF for PDF
import docx  # python-docx for Word
import re
import requests
import bibtexparser  # For .bib files
from difflib import SequenceMatcher

app = Flask(__name__)

# ✅ CORS configured to allow all origins (works with browser & Flutter Web)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/', methods=['GET'])
def home():
    return "✅ Flask Reference Verifier is running!"

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

def search_reference_online(ref):
    query = '+'.join(ref.split())
    url = f"https://api.crossref.org/works?query.title={query}&rows=1"
    try:
        response = requests.get(url)
        data = response.json()
        if data['message']['items']:
            return data['message']['items'][0].get('URL', 'Found but URL not available'), True
        else:
            return 'Not found', False
    except Exception as e:
        return f"Error: {str(e)}", False

def detect_llm_generated(ref):
    if len(ref.split()) < 6 or SequenceMatcher(None, ref.lower(), 'this paper presents a method').ratio() > 0.6:
        return True
    return False

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

@app.route('/verify', methods=['POST'])
def verify():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    uploaded_file = request.files['file']
    filename = secure_filename(uploaded_file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    uploaded_file.save(filepath)

    results = verify_references(filepath)
    return jsonify(results)

@app.route('/ping', methods=['POST'])
def ping():
    return jsonify({"message": "pong"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5002)

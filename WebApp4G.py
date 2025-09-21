import os
import json
import pdfplumber
import io
import re
from flask import Flask, request, jsonify, session, send_file
import google.generativeai as genai

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# ------------------------------
# Helper functions
# ------------------------------
def clean_ai_response(text):
    """Remove markdown-style backticks from AI response so it can be parsed as JSON."""
    if not text:
        return ""
    text = re.sub(r"^```json\s*", "", text.strip())
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()

def extract_text_from_pdf(filepath):
    text = ""
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def create_pdf(summary):
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter,
                            rightMargin=40, leftMargin=40,
                            topMargin=40, bottomMargin=40)

    styles = getSampleStyleSheet()

    # Body style
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['BodyText'],
        fontSize=11,
        leading=14,
        spaceBefore=5,
        spaceAfter=5,
    )

    # Header style
    header_style = ParagraphStyle(
        'Heading2',
        parent=styles['Heading2'],
        fontSize=14,
        leading=18,
        spaceBefore=12,
        spaceAfter=6,
    )

    elements = []

    # Title
    elements.append(Paragraph("Legal Document Summary", styles['Title']))
    elements.append(Spacer(1, 0.25*inch))

    # Elevator Summary
    elements.append(Paragraph("Elevator Summary", header_style))
    elements.append(Paragraph(summary.get('summary_elevator', ''), body_style))
    elements.append(Spacer(1, 0.2*inch))

    # Key Points
    elements.append(Paragraph("Key Points", header_style))
    key_items = [ListItem(Paragraph(str(b), body_style)) for b in summary.get('summary_bullets', [])]
    elements.append(ListFlowable(key_items, bulletType='bullet', leftIndent=20, bulletIndent=10))
    elements.append(Spacer(1, 0.2*inch))

    # Missing Information
    elements.append(Paragraph("Missing Information", header_style))
    missing_items = [ListItem(Paragraph(str(m), body_style)) for m in summary.get('missing_info', [])]
    elements.append(ListFlowable(missing_items, bulletType='bullet', leftIndent=20, bulletIndent=10))
    elements.append(Spacer(1, 0.2*inch))

    # Next Steps (numbered)
    elements.append(Paragraph("Next Steps", header_style))
    next_items = [ListItem(Paragraph(str(s), body_style)) for s in summary.get('next_steps', [])]
    elements.append(ListFlowable(next_items, bulletType='bullet', leftIndent=20, bulletIndent=10))
    elements.append(Spacer(1, 0.2*inch))

    # Confidence
    elements.append(Paragraph(f"Confidence: {summary.get('confidence', 0)}%", header_style))

    # Build PDF
    doc.build(elements)
    pdf_buffer.seek(0)
    return pdf_buffer

# ------------------------------
# Flask app setup
# ------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret")

# Configure Google API
API_KEY = "AIzaSyCLmVvSBRjkJwJIRmeA9KbnB70Mom44RwU"  # replace with your actual key
if not API_KEY:
    raise RuntimeError("Please set a valid API_KEY")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

PROMPT_JSON = """
You are a legal explainer. Simplify this legal document.
Return ONLY valid JSON with the following keys:
- "summary_elevator": a 2-3 sentence plain-English elevator pitch
- "summary_bullets": a list of 5–7 key points in bullet form
- "missing_info": a list of missing details the user must clarify
- "confidence": number 0–100 (confidence of correctness)
- "next_steps": actionable recommendations for the user
"""

# ------------------------------
# Routes
# ------------------------------
@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Legal Document Simplifier</title>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            body {
                font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: #333;
            }

            .header {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-bottom: 1px solid rgba(255, 255, 255, 0.2);
                padding: 1rem 0;
                margin-bottom: 2rem;
            }

            .header-content {
                max-width: 1200px;
                margin: 0 auto;
                padding: 0 2rem;
                display: flex;
                align-items: center;
                gap: 1rem;
            }

            .logo {
                color: white;
                font-size: 1.5rem;
                font-weight: 700;
            }

            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 0 2rem 2rem;
            }

            .main-content {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 2rem;
            }

            @media (max-width: 768px) {
                .main-content {
                    grid-template-columns: 1fr;
                    gap: 1.5rem;
                }
            }

            .card {
                background: rgba(255, 255, 255, 0.95);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 2rem;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.3);
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }

            .card:hover {
                transform: translateY(-5px);
                box-shadow: 0 30px 60px rgba(0, 0, 0, 0.15);
            }

            .card-header {
                display: flex;
                align-items: center;
                gap: 1rem;
                margin-bottom: 1.5rem;
                padding-bottom: 1rem;
                border-bottom: 2px solid #f0f0f0;
            }

            .card-icon {
                width: 50px;
                height: 50px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.5rem;
                color: white;
            }

            .upload-icon {
                background: linear-gradient(135deg, #ff6b6b, #ee5a52);
            }

            .question-icon {
                background: linear-gradient(135deg, #4ecdc4, #44a08d);
            }

            .card-title {
                font-size: 1.5rem;
                font-weight: 700;
                color: #2d3748;
            }

            .upload-area {
                border: 3px dashed #e2e8f0;
                border-radius: 16px;
                padding: 3rem 1.5rem;
                text-align: center;
                transition: all 0.3s ease;
                margin-bottom: 1.5rem;
                cursor: pointer;
                position: relative;
                overflow: hidden;
            }

            .upload-area:hover {
                border-color: #667eea;
                background: rgba(102, 126, 234, 0.05);
            }

            .upload-area.dragover {
                border-color: #667eea;
                background: rgba(102, 126, 234, 0.1);
                transform: scale(1.02);
            }

            .upload-icon-large {
                font-size: 3rem;
                color: #cbd5e0;
                margin-bottom: 1rem;
            }

            .upload-text {
                font-size: 1.1rem;
                color: #64748b;
                margin-bottom: 0.5rem;
            }

            .upload-subtext {
                font-size: 0.9rem;
                color: #94a3b8;
            }

            .file-input {
                display: none;
            }

            .btn {
                padding: 0.75rem 2rem;
                border: none;
                border-radius: 12px;
                font-weight: 600;
                font-size: 1rem;
                cursor: pointer;
                transition: all 0.3s ease;
                text-decoration: none;
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                justify-content: center;
                min-width: 120px;
            }

            .btn-primary {
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                box-shadow: 0 8px 20px rgba(102, 126, 234, 0.3);
            }

            .btn-primary:hover {
                transform: translateY(-2px);
                box-shadow: 0 12px 30px rgba(102, 126, 234, 0.4);
            }

            .btn-secondary {
                background: linear-gradient(135deg, #f093fb, #f5576c);
                color: white;
                box-shadow: 0 8px 20px rgba(245, 87, 108, 0.3);
            }

            .btn-secondary:hover {
                transform: translateY(-2px);
                box-shadow: 0 12px 30px rgba(245, 87, 108, 0.4);
            }

            .btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
                transform: none !important;
            }

            .textarea {
                width: 100%;
                min-height: 120px;
                padding: 1rem;
                border: 2px solid #e2e8f0;
                border-radius: 12px;
                font-size: 1rem;
                font-family: inherit;
                resize: vertical;
                transition: border-color 0.3s ease, box-shadow 0.3s ease;
                margin-bottom: 1rem;
            }

            .textarea:focus {
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }

            .summary-section {
                grid-column: 1 / -1;
                margin-top: 1rem;
            }

            .summary-content {
                display: none;
                animation: slideIn 0.5s ease forwards;
            }

            .summary-content.show {
                display: block;
            }

            @keyframes slideIn {
                from {
                    opacity: 0;
                    transform: translateY(20px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            .summary-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 1.5rem;
                margin-top: 1.5rem;
            }

            .summary-card {
                background: white;
                border-radius: 16px;
                padding: 1.5rem;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
                border-left: 4px solid;
            }

            .elevator-summary {
                border-left-color: #667eea;
            }

            .key-points {
                border-left-color: #4ecdc4;
            }

            .missing-info {
                border-left-color: #ffa726;
            }

            .next-steps {
                border-left-color: #66bb6a;
            }

            .summary-card h3 {
                font-size: 1.2rem;
                font-weight: 700;
                margin-bottom: 1rem;
                color: #2d3748;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .summary-card ul, .summary-card ol {
                padding-left: 1.25rem;
            }

            .summary-card li {
                margin-bottom: 0.5rem;
                line-height: 1.5;
                color: #4a5568;
            }

            .confidence-bar {
                width: 100%;
                height: 8px;
                background: #e2e8f0;
                border-radius: 4px;
                overflow: hidden;
                margin-top: 0.5rem;
            }

            .confidence-fill {
                height: 100%;
                background: linear-gradient(90deg, #ff6b6b, #ffa726, #66bb6a);
                border-radius: 4px;
                transition: width 0.8s ease;
            }

            .answer-section {
                margin-top: 1.5rem;
                padding: 1.5rem;
                background: #f8fafc;
                border-radius: 12px;
                border-left: 4px solid #667eea;
            }

            .answer-section h3 {
                font-size: 1.1rem;
                font-weight: 600;
                margin-bottom: 1rem;
                color: #2d3748;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .answer-text {
                line-height: 1.6;
                color: #4a5568;
                white-space: pre-wrap;
                word-wrap: break-word;
            }

            .loading {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                justify-content: center;
            }

            .spinner {
                width: 20px;
                height: 20px;
                border: 2px solid #ffffff;
                border-top: 2px solid transparent;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }

            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            .file-selected {
                background: rgba(102, 126, 234, 0.1);
                border-color: #667eea;
                color: #667eea;
            }

            .success-message {
                background: #d4edda;
                color: #155724;
                padding: 1rem;
                border-radius: 8px;
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .error-message {
                background: #f8d7da;
                color: #721c24;
                padding: 1rem;
                border-radius: 8px;
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .btn-actions {
                display: flex;
                gap: 1rem;
                margin-top: 1.5rem;
                flex-wrap: wrap;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="header-content">
                <i class="fas fa-balance-scale logo"></i>
                <h1 class="logo">Legal Document Simplifier</h1>
            </div>
        </div>

        <div class="container">
            <div class="main-content">
                <!-- Upload Section -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-icon upload-icon">
                            <i class="fas fa-upload"></i>
                        </div>
                        <h2 class="card-title">Upload Document</h2>
                    </div>
                    
                    <form id="uploadForm" enctype="multipart/form-data">
                        <div class="upload-area" id="uploadArea">
                            <i class="fas fa-file-pdf upload-icon-large"></i>
                            <div class="upload-text">Click to upload or drag & drop</div>
                            <div class="upload-subtext">PDF files only</div>
                        </div>
                        <input type="file" name="file" class="file-input" accept="application/pdf" required id="fileInput" style="display: none;">
                        <button type="submit" class="btn btn-primary" id="uploadBtn">
                            <i class="fas fa-magic"></i>
                            Simplify Document
                        </button>
                    </form>
                </div>

                <!-- Question Section -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-icon question-icon">
                            <i class="fas fa-question-circle"></i>
                        </div>
                        <h2 class="card-title">Ask Questions</h2>
                    </div>
                    
                    <textarea id="question" class="textarea" placeholder="Ask any question about your document..."></textarea>
                    <button onclick="askQuestion()" class="btn btn-secondary" id="askBtn">
                        <i class="fas fa-paper-plane"></i>
                        Ask Question
                    </button>
                    
                    <div class="answer-section" id="answerSection" style="display: none;">
                        <h3><i class="fas fa-lightbulb"></i> Answer</h3>
                        <div class="answer-text" id="answer"></div>
                    </div>
                </div>
            </div>

            <!-- Summary Section -->
            <div class="card summary-section">
                <div class="card-header">
                    <div class="card-icon" style="background: linear-gradient(135deg, #667eea, #764ba2);">
                        <i class="fas fa-file-alt"></i>
                    </div>
                    <h2 class="card-title">Document Summary</h2>
                </div>

                <div id="summary" class="summary-content">
                    <div style="text-align: center; padding: 3rem; color: #64748b;">
                        <i class="fas fa-arrow-up" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                        <p>Upload a document to see the simplified summary here</p>
                    </div>
                </div>
            </div>
        </div>

        <script>
        // File upload handling
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const uploadForm = document.getElementById('uploadForm');
        const uploadBtn = document.getElementById('uploadBtn');

        // Drag and drop functionality
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0 && files[0].type === 'application/pdf') {
                // Create a new FileList and assign it to the input
                const dt = new DataTransfer();
                dt.items.add(files[0]);
                fileInput.files = dt.files;
                updateFileDisplay();
            } else if (files.length > 0) {
                showError("Please upload only PDF files.");
            }
        });

        // Click to upload functionality
        uploadArea.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', updateFileDisplay);

        function updateFileDisplay() {
            const file = fileInput.files[0];
            if (file) {
                if (file.type !== 'application/pdf') {
                    showError("Please upload only PDF files.");
                    fileInput.value = '';
                    resetUploadArea();
                    return;
                }
                uploadArea.classList.add('file-selected');
                uploadArea.innerHTML = `
                    <i class="fas fa-file-pdf upload-icon-large" style="color: #667eea;"></i>
                    <div class="upload-text" style="color: #667eea;">${file.name}</div>
                    <div class="upload-subtext">Ready to upload • Click to change</div>
                `;
            } else {
                resetUploadArea();
            }
        }

        function resetUploadArea() {
            uploadArea.classList.remove('file-selected');
            uploadArea.innerHTML = `
                <i class="fas fa-file-pdf upload-icon-large"></i>
                <div class="upload-text">Click to upload or drag & drop</div>
                <div class="upload-subtext">PDF files only</div>
            `;
        }

        // Form submission
        uploadForm.onsubmit = async function(e) {
            e.preventDefault();
            
            // Check if file is actually selected
            if (!fileInput.files || !fileInput.files[0]) {
                showError("Please select a PDF file to upload.");
                return;
            }

            const file = fileInput.files[0];
            if (file.type !== 'application/pdf') {
                showError("Please upload only PDF files.");
                return;
            }
            
            uploadBtn.innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    Processing...
                </div>
            `;
            uploadBtn.disabled = true;

            try {
                let formData = new FormData();
                formData.append('file', file);
                
                let res = await fetch("/upload", { method: "POST", body: formData });
                let data = await res.json();
                
                if (data.error) {
                    showError(data.error);
                    return;
                }

                sessionStorage.setItem("last_summary", JSON.stringify(data));
                displaySummary(data);
                showSuccess("Document processed successfully!");
                
            } catch (error) {
                showError("Failed to process document. Please try again.");
                console.error("Upload error:", error);
            } finally {
                uploadBtn.innerHTML = `
                    <i class="fas fa-magic"></i>
                    Simplify Document
                `;
                uploadBtn.disabled = false;
            }
        }

        function displaySummary(data) {
            const summaryEl = document.getElementById("summary");
            summaryEl.className = "summary-content show";
            summaryEl.innerHTML = `
                <div class="summary-grid">
                    <div class="summary-card elevator-summary">
                        <h3><i class="fas fa-rocket"></i> Elevator Summary</h3>
                        <p>${data.summary_elevator}</p>
                    </div>
                    
                    <div class="summary-card key-points">
                        <h3><i class="fas fa-key"></i> Key Points</h3>
                        <ul>${data.summary_bullets.map(b => `<li>${b}</li>`).join('')}</ul>
                    </div>
                    
                    <div class="summary-card missing-info">
                        <h3><i class="fas fa-exclamation-triangle"></i> Missing Information</h3>
                        <ul>${data.missing_info.map(m => `<li>${m}</li>`).join('')}</ul>
                    </div>
                    
                    <div class="summary-card next-steps">
                        <h3><i class="fas fa-tasks"></i> Next Steps</h3>
                        <ol>${data.next_steps.map(s => `<li>${s}</li>`).join('')}</ol>
                    </div>
                </div>
                
                <div class="summary-card" style="margin-top: 1.5rem;">
                    <h3><i class="fas fa-chart-line"></i> Confidence Level: ${data.confidence}%</h3>
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: ${data.confidence}%"></div>
                    </div>
                </div>
                
                <div class="btn-actions">
                    <button onclick="downloadPDF()" class="btn btn-secondary">
                        <i class="fas fa-download"></i>
                        Download PDF Summary
                    </button>
                </div>
            `;
        }

        async function askQuestion() {
            const questionInput = document.getElementById("question");
            const askBtn = document.getElementById("askBtn");
            const answerSection = document.getElementById("answerSection");
            const answerEl = document.getElementById("answer");
            
            const question = questionInput.value.trim();
            if (!question) {
                showError("Please enter a question.");
                return;
            }

            askBtn.innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    Thinking...
                </div>
            `;
            askBtn.disabled = true;

            try {
                let res = await fetch("/ask", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({question: question})
                });
                let data = await res.json();
                
                if (data.error) {
                    showError(data.error);
                } else {
                    answerEl.textContent = data.answer;
                    answerSection.style.display = "block";
                    answerSection.scrollIntoView({ behavior: 'smooth' });
                }
                
            } catch (error) {
                showError("Failed to get answer. Please try again.");
            } finally {
                askBtn.innerHTML = `
                    <i class="fas fa-paper-plane"></i>
                    Ask Question
                `;
                askBtn.disabled = false;
            }
        }

        async function downloadPDF() {
            try {
                let res = await fetch("/download_summary");
                let blob = await res.blob();
                let url = window.URL.createObjectURL(blob);
                let a = document.createElement("a");
                a.href = url;
                a.download = "legal-summary.pdf";
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                showSuccess("PDF downloaded successfully!");
            } catch (error) {
                showError("Failed to download PDF. Please try again.");
            }
        }

        function showSuccess(message) {
            removeMessages();
            const successDiv = document.createElement('div');
            successDiv.className = 'success-message';
            successDiv.innerHTML = `<i class="fas fa-check-circle"></i> ${message}`;
            document.querySelector('.container').insertBefore(successDiv, document.querySelector('.main-content'));
            setTimeout(() => successDiv.remove(), 5000);
        }

        function showError(message) {
            removeMessages();
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error-message';
            errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
            document.querySelector('.container').insertBefore(errorDiv, document.querySelector('.main-content'));
            setTimeout(() => errorDiv.remove(), 5000);
        }

        function removeMessages() {
            const existing = document.querySelectorAll('.success-message, .error-message');
            existing.forEach(el => el.remove());
        }

        // Enter key support for question textarea
        document.getElementById('question').addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && e.ctrlKey) {
                askQuestion();
            }
        });
        </script>
    </body>
    </html>
    """

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    os.makedirs("uploads", exist_ok=True)
    filepath = os.path.join("uploads", file.filename)
    file.save(filepath)

    doc_text = extract_text_from_pdf(filepath)
    if not doc_text:
        return jsonify({"error": "Failed to extract text from PDF"}), 400

    session["last_doc"] = doc_text

    try:
        response = model.generate_content([PROMPT_JSON, doc_text])
        text_output = clean_ai_response(response.text if response else "")
        data = json.loads(text_output)
        session["last_summary"] = data
    except Exception as e:
        return jsonify({"error": f"AI call failed: {str(e)}", "raw": response.text if response else ""}), 500

    return jsonify(data)

@app.route("/ask", methods=["POST"])
def ask():
    if "last_doc" not in session:
        return jsonify({"error": "No document uploaded yet."}), 400

    payload = request.get_json()
    question = payload.get("question")
    if not question:
        return jsonify({"error": "Missing question."}), 400

    try:
        response = model.generate_content([
            "Here is the legal document:",
            session["last_doc"],
            f"User question: {question}"
        ])
        answer_text = response.text if response else "No response from AI"
    except Exception as e:
        answer_text = f"AI call failed: {str(e)}"

    return jsonify({"answer": answer_text})

@app.route("/download_summary", methods=["GET"])
def download_summary():
    if "last_summary" not in session:
        return jsonify({"error": "No summary available"}), 400

    pdf_file = create_pdf(session["last_summary"])
    return send_file(pdf_file, download_name="summary.pdf", as_attachment=True)

# ------------------------------
# Run server
# ------------------------------
if __name__ == "__main__":
    app.run()
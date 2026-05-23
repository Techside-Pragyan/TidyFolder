import re
from pathlib import Path

# Seed training data mapping filenames and extensions to target categories
TRAINING_DATA = [
    # Work Files
    ("q4_financial_report.xlsx", "Work files"),
    ("monthly_invoice_template.pdf", "Work files"),
    ("quarterly_sales_performance.pptx", "Work files"),
    ("customer_feedback_survey.csv", "Work files"),
    ("business_pitch_presentation.ppt", "Work files"),
    ("budget_forecast_2026.xlsx", "Work files"),
    ("onboarding_contract_draft.docx", "Work files"),
    ("NDA_agreement_signed.pdf", "Work files"),
    ("employee_timesheet_may.xlsx", "Work files"),
    ("project_proposal_v3.docx", "Work files"),
    
    # Study Materials
    ("algorithms_lecture_notes_3.pdf", "Study materials"),
    ("history_term_paper_draft.docx", "Study materials"),
    ("chemistry_lab_experiment_4.pdf", "Study materials"),
    ("calculus_homework_assignment.pdf", "Study materials"),
    ("machine_learning_syllabus.txt", "Study materials"),
    ("midterm_study_guide_biology.docx", "Study materials"),
    ("introduction_to_economics_notes.pdf", "Study materials"),
    ("physics_tutorial_sheet_9.pdf", "Study materials"),
    ("literature_reading_assignment.epub", "Study materials"),
    
    # Code Files
    ("App.tsx", "Code files"),
    ("server.js", "Code files"),
    ("db_connection.py", "Code files"),
    ("index.html", "Code files"),
    ("main.go", "Code files"),
    ("styles.global.css", "Code files"),
    ("webpack.config.js", "Code files"),
    ("cargo.toml", "Code files"),
    ("package.json", "Code files"),
    ("UserController.java", "Code files"),
    ("run_migrations.sh", "Code files"),
    
    # Images / Screenshots
    ("family_vacation_photo.jpg", "Images"),
    ("screenshot_2026_05_23.png", "Screenshots"),
    ("ss_dashboard_error.png", "Screenshots"),
    ("profile_avatar_glow.png", "Images"),
    ("logo_vector_draft.svg", "Images"),
    ("memes_reddit_funny.webp", "Images"),
    ("shot_4919_crop.jpg", "Screenshots"),
    
    # Music / Audio
    ("lofi_hiphop_chill_beats.mp3", "Music"),
    ("voice_memo_recording.wav", "Music"),
    ("orchestral_symphony_no9.flac", "Music"),
    ("podcast_episode_12_interview.m4a", "Music"),
    
    # Videos / Media
    ("tutorial_video_editing_walkthrough.mp4", "Videos"),
    ("movie_recording_hq.mkv", "Videos"),
    ("intro_animation_render.mov", "Videos"),
    ("gameplay_highlights.webm", "Videos"),
    
    # Archives / Compression
    ("source_code_backup.zip", "Archives"),
    ("large_dataset_compressed.tar.gz", "Archives"),
    ("application_install_files.rar", "Archives"),
    ("photoshop_project_archive.7z", "Archives")
]

class SmartFileClassifier:
    def __init__(self):
        self.ml_ready = False
        self.vectorizer = None
        self.model = None
        self._initialize_ml()

    def _initialize_ml(self):
        """Attempts to import scikit-learn and train the classifier model."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.naive_bayes import MultinomialNB
            
            print("Scikit-Learn detected! Initializing ML Categorization Model...")
            
            # Prepare data
            X = [item[0] for item in TRAINING_DATA]
            y = [item[1] for item in TRAINING_DATA]
            
            # Feature extraction using character and word n-grams
            self.vectorizer = TfidfVectorizer(
                analyzer='char_wb', 
                ngram_range=(2, 4), 
                lowercase=True
            )
            X_vectorized = self.vectorizer.fit_transform(X)
            
            # Train simple robust Naive Bayes classifier
            self.model = MultinomialNB(alpha=0.1)
            self.model.fit(X_vectorized, y)
            
            self.ml_ready = True
            print("ML Categorization Model trained and ready to classify files.")
        except ImportError:
            print("Scikit-Learn not loaded yet. Defaulting to high-performance Rules-Based classifier.")
            self.ml_ready = False

    def predict(self, filename, ext=""):
        """Predicts the category of a file based on its name and extension."""
        ext = ext.lower() or Path(filename).suffix.lower()
        filename_lower = filename.lower()

        # Rule 1: Instant extension-based overrides
        if ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
            return "Archives"
        if ext in ['.mp3', '.wav', '.flac', '.ogg', '.m4a']:
            return "Music"
        if ext in ['.mp4', '.mkv', '.mov', '.avi', '.webm']:
            return "Videos"
        if ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.json', '.go', '.rs', '.cpp', '.java']:
            return "Code files"

        # Rule 2: Screenshot detection
        if 'screenshot' in filename_lower or 'ss_' in filename_lower or re.match(r'screen[_ ]shot', filename_lower):
            return "Screenshots"

        # Rule 3: Use ML model if available
        if self.ml_ready and self.model and self.vectorizer:
            try:
                # Combine filename and extension to provide clear context
                feat = f"{filename} {ext}"
                vect = self.vectorizer.transform([feat])
                pred = self.model.predict(vect)[0]
                return pred
            except Exception as e:
                print(f"ML classification failed for {filename}: {e}. Falling back to rules.")

        # Rule 4: Heuristics / Semantic Keyword Rules (our robust fallback!)
        study_keywords = ['assignment', 'homework', 'lecture', 'class', 'syllabus', 'notes', 'study', 'exam', 'paper', 'course']
        work_keywords = ['report', 'invoice', 'financial', 'budget', 'proposal', 'agreement', 'timesheet', 'contract', 'schedule', 'client', 'tax', 'legal']
        image_keywords = ['photo', 'image', 'pic', 'logo', 'drawing', 'avatar', 'render', 'illustration', 'jpeg', 'jpg', 'png', 'svg', 'webp']

        if any(kw in filename_lower for kw in study_keywords):
            return "Study materials"
        if any(kw in filename_lower for kw in work_keywords) or ext in ['.xlsx', '.xls', '.csv']:
            return "Work files"
        if any(kw in filename_lower for kw in image_keywords) or ext in ['.jpg', '.jpeg', '.png', '.svg', '.webp']:
            return "Images"
        if ext in ['.pdf', '.docx', '.doc', '.pptx', '.ppt', '.txt', '.epub', '.md']:
            return "Documents"

        # Default fallbacks
        if ext:
            return "Documents"
        return "Work files"

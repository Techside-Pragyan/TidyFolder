import os
import shutil
from pathlib import Path
from app.db import get_db_connection
from app.ai.classifier import SmartFileClassifier

class FolderOrganizer:
    def __init__(self, target_path):
        self.target_path = Path(target_path)
        self.classifier = SmartFileClassifier()

    def organize(self):
        """Organizes all files in the target directory into smart category folders."""
        if not self.target_path.exists() or not self.target_path.is_dir():
            raise FileNotFoundError(f"Target path does not exist or is not a directory: {self.target_path}")

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Batch session ID using current timestamp/counter
        cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM cleanup_history")
        batch_id = cursor.fetchone()[0]

        files_organized = []
        errors = []

        # Find all files in the top-level target directory (we do not recursively sort by default
        # to prevent messing up deeply nested code repositories/projects, which is standard for safety)
        loose_files = [f for f in self.target_path.iterdir() if f.is_file()]

        for filepath in loose_files:
            # Skip hidden files or system files
            if filepath.name.startswith('.') or filepath.name.lower() in ['desktop.ini', 'thumbs.db']:
                continue

            try:
                # Predict target category
                category = self.classifier.predict(filepath.name, filepath.suffix)
                
                # Make target category directory
                dest_dir = self.target_path / category
                dest_dir.mkdir(exist_ok=True)

                dest_filepath = dest_dir / filepath.name

                # Handle name collisions (add numerical suffix if already exists)
                if dest_filepath.exists():
                    base = filepath.stem
                    ext = filepath.suffix
                    counter = 1
                    while dest_filepath.exists():
                        dest_filepath = dest_dir / f"{base}_{counter}{ext}"
                        counter += 1

                # Log move in SQLite BEFORE running the transaction (for safety/audit trail)
                cursor.execute("""
                    INSERT INTO cleanup_history (file_path, file_size, category, action_taken, backup_path)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(filepath), 
                    filepath.stat().st_size, 
                    category, 
                    f"organize_batch_{batch_id}", 
                    str(dest_filepath)
                ))

                # Perform native file system move
                shutil.move(str(filepath), str(dest_filepath))
                
                files_organized.append({
                    'original': str(filepath),
                    'organized': str(dest_filepath),
                    'category': category
                })

            except Exception as e:
                errors.append(f"Failed to organize {filepath.name}: {str(e)}")

        conn.commit()
        conn.close()

        return {
            'batch_id': batch_id,
            'files_organized': files_organized,
            'errors': errors
        }

    @staticmethod
    def undo_organization(batch_id):
        """Reverses an auto-organization batch operation, moving files back to original paths."""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query all operations in this organize batch
        cursor.execute("""
            SELECT id, file_path, backup_path 
            FROM cleanup_history 
            WHERE action_taken = ?
        """, (f"organize_batch_{batch_id}",))
        
        records = cursor.fetchall()
        undone_files = []
        errors = []

        for record in records:
            rec_id, original_path, organized_path = record
            
            if os.path.exists(organized_path):
                try:
                    # Ensure original folder exists if deleted in the interim
                    os.makedirs(os.path.dirname(original_path), exist_ok=True)
                    
                    # Move back to original spot
                    shutil.move(organized_path, original_path)
                    undone_files.append(original_path)

                    # Delete cleanup history record now that it is undone
                    cursor.execute("DELETE FROM cleanup_history WHERE id = ?", (rec_id,))
                except Exception as e:
                    errors.append(f"Failed to restore {os.path.basename(original_path)}: {str(e)}")
            else:
                errors.append(f"organized file not found, can't restore: {organized_path}")

        conn.commit()
        conn.close()

        return {
            'undone_files': undone_files,
            'errors': errors
        }

import os
import shutil
import asyncio
from typing import List, Dict, Any
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import get_db_connection, init_db
from app.services.scanner import SmartScanner
from app.services.organizer import FolderOrganizer
from app.services.monitor import FolderWatcher
from app.ai.recommender import RecommendationEngine
from app.ai.chatbot import StorageChatbot

app = FastAPI(title="Intelligent Folder Cleaner AI API")

# Configure CORS for Next.js and Electron
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permits localhost access from Next/Electron
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active watcher instance and connected WebSockets
active_watcher: FolderWatcher = None
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"WebSocket Client Connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"WebSocket Client Disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Handle stale connections
                pass

manager = ConnectionManager()
chatbot = StorageChatbot()

# Pydantic Schemas for API Requests
class ScanRequest(BaseModel):
    path: str

class OrganizeRequest(BaseModel):
    path: str

class UndoOrganizeRequest(BaseModel):
    batch_id: int

class DeleteRequest(BaseModel):
    paths: List[str]

class ChatRequest(BaseModel):
    message: str

class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, str]

# Helper to resolve backup path
def get_backup_directory() -> Path:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'backup_dir'")
    row = cursor.fetchone()
    conn.close()
    
    if row:
        backup_dir = Path(row[0])
    else:
        backup_dir = Path(__file__).resolve().parent.parent / "backups"
    
    backup_dir.mkdir(exist_ok=True)
    return backup_dir


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/api/health")
def health_check():
    return {"status": "running", "engine": "FastAPI + ML Classifier"}


@app.post("/api/scan")
async def start_scan(req: ScanRequest):
    target_path = Path(req.path)
    if not target_path.exists() or not target_path.is_dir():
        raise HTTPException(status_code=400, detail="Target path is not a valid directory.")

    scanner = SmartScanner(target_path)
    
    # Run scan
    results = scanner.scan()

    # Store results in Database
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Insert Scan History record
        cursor.execute("""
            INSERT INTO scan_history (target_path, total_files, total_size, health_score)
            VALUES (?, ?, ?, ?)
        """, (str(target_path), results['total_files'], results['total_size'], results['health_score']))
        scan_id = cursor.lastrowid

        # 2. Clear old metadata for this folder to prevent stale index records
        cursor.execute("DELETE FROM file_metadata WHERE file_path LIKE ?", (f"{target_path}%",))

        # 3. Populate file_metadata table (bulk insert)
        file_inserts = []
        for f in scanner.files_found:
            # Check if this file is a duplicate
            is_dup = 0
            for d in scanner.duplicates:
                # If it matches a duplicate list and isn't the first (primary) element
                if f['path'] in [item['path'] for item in d['files'][1:]]:
                    is_dup = 1
                    break
            
            # Check if matching visual similar images duplicate list
            for s in scanner.similar_images:
                if f['path'] in [item['path'] for item in s['files'][1:]]:
                    is_dup = 1
                    break

            file_inserts.append((
                scan_id,
                f['path'],
                f['name'],
                f['size'],
                f['category'],
                is_dup,
                1 if f['is_junk'] else 0,
                f['last_modified'],
                f['last_accessed']
            ))

        cursor.executemany("""
            INSERT INTO file_metadata (scan_id, file_path, file_name, file_size, category, is_duplicate, is_junk, last_modified, last_accessed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, file_inserts)

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database logging failed: {e}")
    finally:
        conn.close()

    # Generate Recommendations dynamically
    recommender = RecommendationEngine(target_path)
    recommendations = recommender.generate_recommendations(results)

    return {
        "scan_id": scan_id,
        "summary": {
            "total_files": results['total_files'],
            "total_size": results['total_size'],
            "health_score": results['health_score'],
            "duplicate_count": sum(len(d['files']) - 1 for d in results['duplicates']),
            "junk_count": len(results['junk_files']),
            "large_count": len(results['large_files'])
        },
        "duplicates": results['duplicates'],
        "similar_images": results['similar_images'],
        "junk_files": results['junk_files'],
        "large_files": results['large_files'],
        "empty_folders": results['empty_folders'],
        "category_sizes": results['category_sizes'],
        "category_counts": results['category_counts'],
        "recommendations": recommendations
    }


@app.post("/api/organize")
async def organize_folder(req: OrganizeRequest):
    try:
        organizer = FolderOrganizer(req.path)
        results = organizer.organize()
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/undo-organize")
async def undo_organize(req: UndoOrganizeRequest):
    try:
        results = FolderOrganizer.undo_organization(req.batch_id)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clean-junk")
async def clean_junk(req: ScanRequest):
    """Safely cleans all files marked as junk, moving them to backups for undo support."""
    target_path = req.path
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT file_path, file_size, category 
        FROM file_metadata 
        WHERE is_junk = 1 AND file_path LIKE ?
    """, (f"{target_path}%",))
    
    junk_files = cursor.fetchall()
    if not junk_files:
        conn.close()
        return {"cleaned_count": 0, "space_recovered": 0}

    backup_dir = get_backup_directory()
    cleaned_count = 0
    space_recovered = 0

    # Batch ID for tracking
    cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM cleanup_history")
    batch_id = cursor.fetchone()[0]

    for row in junk_files:
        filepath = Path(row['file_path'])
        if filepath.exists() and filepath.is_file():
            try:
                # Keep a backup copy of the file before removal
                rel_backup_path = backup_dir / f"junk_batch_{batch_id}_{filepath.name}"
                shutil.copy2(str(filepath), str(rel_backup_path))

                # Log clean in database
                cursor.execute("""
                    INSERT INTO cleanup_history (file_path, file_size, category, action_taken, backup_path)
                    VALUES (?, ?, ?, ?, ?)
                """, (str(filepath), row['file_size'], row['category'], f"junk_batch_{batch_id}", str(rel_backup_path)))

                # Delete the original file
                filepath.unlink()
                cleaned_count += 1
                space_recovered += row['file_size']
            except Exception as e:
                print(f"Error safe-cleaning junk file {filepath}: {e}")

    # Log space recovered in scan history
    cursor.execute("""
        INSERT INTO scan_history (target_path, total_files, total_size, space_freed, health_score)
        VALUES (?, 0, 0, ?, 100.0)
    """, (str(target_path), space_recovered))

    conn.commit()
    conn.close()

    return {
        "batch_id": batch_id,
        "cleaned_count": cleaned_count,
        "space_recovered": space_recovered
    }


@app.post("/api/delete-files")
async def delete_files(req: DeleteRequest):
    """Deletes list of targeted files (e.g. duplicates) with backup copy safety."""
    if not req.paths:
        return {"deleted_count": 0, "space_recovered": 0}

    conn = get_db_connection()
    cursor = conn.cursor()
    
    backup_dir = get_backup_directory()
    deleted_count = 0
    space_recovered = 0

    # Batch ID for tracking
    cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM cleanup_history")
    batch_id = cursor.fetchone()[0]

    for p in req.paths:
        filepath = Path(p)
        if filepath.exists() and filepath.is_file():
            try:
                size = filepath.stat().st_size
                ext = filepath.suffix.lower()
                
                # Copy to backup
                rel_backup = backup_dir / f"del_batch_{batch_id}_{filepath.name}"
                shutil.copy2(str(filepath), str(rel_backup))

                # Log delete transaction
                cursor.execute("""
                    INSERT INTO cleanup_history (file_path, file_size, category, action_taken, backup_path)
                    VALUES (?, ?, ?, ?, ?)
                """, (str(filepath), size, ext, f"delete_batch_{batch_id}", str(rel_backup)))

                # Remove original
                filepath.unlink()
                deleted_count += 1
                space_recovered += size
            except Exception as e:
                print(f"Failed to delete/backup file {p}: {e}")

    conn.commit()
    conn.close()

    return {
        "batch_id": batch_id,
        "deleted_count": deleted_count,
        "space_recovered": space_recovered
    }


@app.post("/api/undo-cleanup")
async def undo_cleanup(req: UndoOrganizeRequest):
    """Restores files that were deleted/cleaned in a specific batch."""
    batch_id = req.batch_id
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, file_path, backup_path 
        FROM cleanup_history 
        WHERE action_taken LIKE ? OR action_taken LIKE ?
    """, (f"junk_batch_{batch_id}", f"delete_batch_{batch_id}"))
    
    records = cursor.fetchall()
    restored_files = []
    errors = []

    for record in records:
        rec_id, original_path, backup_path = record
        
        if os.path.exists(backup_path):
            try:
                # Ensure parent dir exists
                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                
                # Copy back
                shutil.copy2(backup_path, original_path)
                restored_files.append(original_path)

                # Remove backup file
                os.remove(backup_path)

                # Remove DB log
                cursor.execute("DELETE FROM cleanup_history WHERE id = ?", (rec_id,))
            except Exception as e:
                errors.append(f"Failed to restore {os.path.basename(original_path)}: {str(e)}")
        else:
            errors.append(f"Backup file not found: {backup_path}")

    conn.commit()
    conn.close()

    return {
        "restored_files": restored_files,
        "errors": errors
    }


@app.post("/api/chat")
async def chat_assistant(req: ChatRequest):
    response = chatbot.process_message(req.message)
    return {"reply": response}


@app.get("/api/dashboard")
async def get_dashboard_data():
    """Compiles global analytics dashboard statistics across historical runs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Total recovered space
        cursor.execute("SELECT SUM(space_freed) FROM scan_history")
        space_recovered = cursor.fetchone()[0] or 0

        # Latest Health Score
        cursor.execute("SELECT health_score FROM scan_history ORDER BY id DESC LIMIT 1")
        latest_score_row = cursor.fetchone()
        latest_score = latest_score_row[0] if latest_score_row else 100.0

        # Duplicate counts registered
        cursor.execute("SELECT COUNT(*), SUM(file_size) FROM file_metadata WHERE is_duplicate = 1")
        dup_row = cursor.fetchone()
        dup_count = dup_row[0] or 0
        dup_size = dup_row[1] or 0

        # Recent cleanup logs
        cursor.execute("""
            SELECT file_path, file_size, category, action_taken, cleaned_at 
            FROM cleanup_history 
            ORDER BY id DESC LIMIT 10
        """)
        cleanups = [dict(row) for row in cursor.fetchall()]

        # Storage composition grouping by category
        cursor.execute("""
            SELECT category, COUNT(*) as count, SUM(file_size) as size 
            FROM file_metadata 
            GROUP BY category
        """)
        composition = [dict(row) for row in cursor.fetchall()]

        # Scan History Log
        cursor.execute("SELECT target_path, total_files, total_size, health_score, scanned_at FROM scan_history ORDER BY id DESC LIMIT 5")
        history = [dict(row) for row in cursor.fetchall()]

        return {
            "space_recovered_bytes": space_recovered,
            "folder_health_score": latest_score,
            "duplicate_count": dup_count,
            "duplicate_size_bytes": dup_size,
            "composition": composition,
            "cleanup_history": cleanups,
            "scan_history": history
        }
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Dashboard query failed: {e}")
    finally:
        conn.close()


@app.get("/api/settings")
def get_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    conn.close()
    return settings


@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for k, v in req.settings.items():
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
    return {"status": "settings updated"}


# Real-time WebSocket Monitoring Broadcasting
async def monitor_broadcast_callback(event_data: dict):
    """Pipes synchronous file system updates from Watchdog to WebSocket."""
    await manager.broadcast(event_data)


@app.websocket("/api/monitor/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Maintain connection alive (heartbeats)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/monitor/start")
async def start_monitoring(req: ScanRequest):
    global active_watcher
    if active_watcher:
        active_watcher.stop()
        active_watcher = None

    try:
        active_watcher = FolderWatcher(req.path, monitor_broadcast_callback)
        active_watcher.start()
        return {"status": "monitoring started", "path": req.path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Watcher startup failed: {str(e)}")


@app.post("/api/monitor/stop")
async def stop_monitoring():
    global active_watcher
    if active_watcher:
        active_watcher.stop()
        active_watcher = None
        return {"status": "monitoring stopped"}
    return {"status": "no active monitoring observer to stop"}

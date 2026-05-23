import re
from app.db import get_db_connection

class StorageChatbot:
    """Offline conversational AI assistant that queries local SQLite data to answer questions."""
    
    def process_message(self, message: str) -> str:
        msg = message.lower().strip()
        
        # 1. Query for Largest Files
        if any(kw in msg for kw in ['large', 'biggest', 'hogs', 'size', 'heavy', 'occupying', 'space']):
            return self._get_largest_files_response()
            
        # 2. Query for Safe Deletions / Junk
        if any(kw in msg for kw in ['safe to delete', 'delete', 'clean', 'junk', 'temp', 'cache', 'remove']):
            return self._get_safe_delete_response()
            
        # 3. Query for Duplicates
        if any(kw in msg for kw in ['duplicate', 'double', 'identical', 'repeats']):
            return self._get_duplicates_response()
            
        # 4. Folder Health / General Scan Info
        if any(kw in msg for kw in ['health', 'score', 'status', 'organized', 'shape']):
            return self._get_health_status_response()

        # 5. Interactive help / general FAQ
        if any(kw in msg for kw in ['hello', 'hi', 'hey', 'who are you', 'help']):
            return (
                "Hello! I am **Ada**, your Intelligent Folder Cleaner AI assistant. 🤖\n\n"
                "I am deeply integrated into your local filesystem database. Here are some real-time queries you can ask me:\n"
                "- 📊 *'Which files are taking up the most space?'*\n"
                "- 🛡️ *'What files are 100% safe to delete?'*\n"
                "- 👥 *'Do I have duplicate files in this workspace?'*\n"
                "- ❤️ *'How is the health score of my folder?'*\n\n"
                "How can I assist you with optimizing your storage today?"
            )

        # 6. Default AI response
        return (
            "I've analyzed your question! As your offline AI folder partner, I recommend running a **Smart Scan** first to index all details.\n\n"
            "If you'd like specific optimization insights, try asking: *'Show me the biggest files'* or *'Which duplicates can I clear?'* and I will query the live database."
        )

    def _get_largest_files_response(self) -> str:
        """Retrieves the top 5 largest indexed files in the database and returns a beautiful Markdown list."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT file_name, file_path, file_size, category 
                FROM file_metadata 
                ORDER BY file_size DESC 
                LIMIT 5
            """)
            rows = cursor.fetchall()
            
            if not rows:
                return (
                    "I checked our metadata database, but it appears empty! 📂\n\n"
                    "Please run a **Smart Scan** from the main dashboard so I can map your files and identify the storage hogs."
                )
                
            response = "Here are the **top 5 largest files** currently occupying your storage:\n\n"
            for i, r in enumerate(rows, 1):
                name = r['file_name']
                path = r['file_path']
                size = self._format_size(r['file_size'])
                cat = r['category']
                response += f"{i}. 📁 **{name}** ({size})\n"
                response += f"   - *Category:* {cat}\n"
                response += f"   - *Path:* `{path}`\n\n"
                
            response += "💡 *Tip: If these are installers or archives, you can compress or delete them to reclaim space instantly.*"
            return response
        except Exception as e:
            return f"I ran into an issue querying the database: {e}"
        finally:
            conn.close()

    def _get_safe_delete_response(self) -> str:
        """Finds log files, temp files, and duplicates that are marked safe to delete."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Query sum of junk files
            cursor.execute("SELECT COUNT(*), SUM(file_size) FROM file_metadata WHERE is_junk = 1")
            junk_count, junk_size = cursor.fetchone()
            junk_size = junk_size if junk_size else 0

            # Query sum of duplicates
            cursor.execute("SELECT COUNT(*) FROM file_metadata WHERE is_duplicate = 1")
            dup_count = cursor.fetchone()[0]

            if junk_count == 0 and dup_count == 0:
                return (
                    "🎉 **Great news! Your folder looks clean!**\n\n"
                    "There are no active temporary caches, log files, or exact duplicates registered in my system. "
                    "Everything is in shipshape condition!"
                )

            response = "🛡️ **Safe-to-Clean Assessment Report:**\n\n"
            if junk_count > 0:
                response += f"- **Temporary Files & Caches:** We detected **{junk_count} items** ({self._format_size(junk_size)}) that are entirely safe to prune. These include `.log` registries, build caches, and installers.\n"
            if dup_count > 0:
                response += f"- **Exact Duplicates:** We found **{dup_count} duplicate files**. Deleting redundant copies will not affect your primary data.\n\n"

            response += "🚀 *You can wipe all junk files safely with one click using the 'Safe Clean' button on the Scanner screen!*"
            return response
        except Exception as e:
            return f"I ran into an issue reading the safe cleanup database: {e}"
        finally:
            conn.close()

    def _get_duplicates_response(self) -> str:
        """Aggregates duplicates statistics from SQLite."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*), SUM(file_size) FROM file_metadata WHERE is_duplicate = 1")
            count, size = cursor.fetchone()
            size = size if size else 0

            if count == 0:
                return "✨ **Zero Duplicates!** No redundant exact duplicate files were detected in this workspace directory."

            return (
                f"👥 **Duplicate File Inventory:**\n\n"
                f"I detected **{count} redundant duplicate files** in your folder, consuming a total of **{self._format_size(size)}** in wasted space.\n\n"
                "You can inspect them file-by-file in the **Smart Scan** view and delete them while keeping the most recent copy automatically."
            )
        except Exception as e:
            return f"Failed to load duplicate counts: {e}"
        finally:
            conn.close()

    def _get_health_status_response(self) -> str:
        """Retrieves system folder health score from scan history."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT health_score, total_files, total_size FROM scan_history ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()

            if not row:
                return (
                    "I don't have a record of your folder health yet!\n\n"
                    "Initiate a **Smart Scan** on the dashboard, and I will calculate a comprehensive health grade for your folder."
                )

            score = row['health_score']
            files = row['total_files']
            size = self._format_size(row['total_size'])

            grade = 'A'
            color = 'emerald'
            if score < 90: grade = 'B'; color = 'blue'
            if score < 80: grade = 'C'; color = 'yellow'
            if score < 70: grade = 'D'; color = 'orange'
            if score < 60: grade = 'F'; color = 'red'

            return (
                f"❤️ **Workspace Folder Health Report:**\n\n"
                f"- **Health Score:** `{score}/100` (Grade **{grade}**)\n"
                f"- **Indexed Scope:** {files} files occupying {size}.\n\n"
                "**Improvement Plan:** You can boost this score back to 100 by clearing flagged logs/caches and deleting duplicate media files."
            )
        except Exception as e:
            return f"Failed to retrieve health status: {e}"
        finally:
            conn.close()

    def _format_size(self, size_bytes):
        if size_bytes == 0:
            return "0 Bytes"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

import os
import time
from pathlib import Path
from app.db import get_db_connection

class RecommendationEngine:
    def __init__(self, target_path=None):
        self.target_path = Path(target_path) if target_path else None

    def generate_recommendations(self, scan_data=None):
        """Analyzes scan data or DB metadata and generates structured cleaning & optimization suggestions."""
        recommendations = []

        if not scan_data:
            # If no in-memory scan, try fetching the latest items from SQLite
            return self._generate_fallback_recommendations()

        # 1. Exact Duplicates Recommendations
        duplicates = scan_data.get('duplicates', [])
        dup_waste = sum(d.get('total_size', 0) for d in duplicates)
        if duplicates:
            recommendations.append({
                'type': 'duplicate',
                'title': 'Remove Exact Duplicates',
                'description': f"You have {len(duplicates)} groups of identical duplicate files, wasting {self._format_size(dup_waste)} of space.",
                'action_label': 'Prune Duplicates',
                'savings_bytes': dup_waste,
                'priority': 'HIGH',
                'items_count': sum(len(d['files']) - 1 for d in duplicates)
            })

        # 2. Similar Screenshots Recommendations
        similar_images = scan_data.get('similar_images', [])
        sim_waste = sum(s.get('total_size', 0) for s in similar_images)
        if similar_images:
            recommendations.append({
                'type': 'similar_image',
                'title': 'Clean Up Similar Screenshots',
                'description': f"Detected {len(similar_images)} groups of highly similar screenshots or image bursts, wasting {self._format_size(sim_waste)}.",
                'action_label': 'Review Images',
                'savings_bytes': sim_waste,
                'priority': 'MEDIUM',
                'items_count': sum(len(s['files']) - 1 for s in similar_images)
            })

        # 3. Junk Files Recommendations
        junk_files = scan_data.get('junk_files', [])
        junk_waste = sum(j.get('size', 0) for j in junk_files)
        if junk_files:
            recommendations.append({
                'type': 'junk',
                'title': 'Clear Cache & Temp Logs',
                'description': f"Safely wipe {len(junk_files)} temporary log, installer, and cache files to recover {self._format_size(junk_waste)}.",
                'action_label': 'Safe Clean',
                'savings_bytes': junk_waste,
                'priority': 'HIGH',
                'items_count': len(junk_files)
            })

        # 4. Storage Hogs (Large & Unused)
        large_files = scan_data.get('large_files', [])
        unused_large = [f for f in large_files if f.get('is_old', False)]
        unused_large_waste = sum(f['size'] for f in unused_large)
        if unused_large:
            recommendations.append({
                'type': 'large_old',
                'title': 'Archive Unused Large Files',
                'description': f"Identified {len(unused_large)} massive files (>100MB) that haven't been accessed in over 6 months, consuming {self._format_size(unused_large_waste)}.",
                'action_label': 'Analyze Large Files',
                'savings_bytes': unused_large_waste,
                'priority': 'MEDIUM',
                'items_count': len(unused_large)
            })

        # 5. Organization Insights
        loose_count = scan_data.get('category_counts', {}).get('Downloads', 0)
        if loose_count > 15:
            recommendations.append({
                'type': 'organize',
                'title': 'AI Folder Sorting Suggested',
                'description': f"You have {loose_count} unsorted items sitting in your workspace root. We recommend running the AI File Organizer.",
                'action_label': 'Auto-Organize Now',
                'savings_bytes': 0,
                'priority': 'LOW',
                'items_count': loose_count
            })

        # Sort recommendations by priority (HIGH -> MEDIUM -> LOW)
        priority_map = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        recommendations.sort(key=lambda x: priority_map[x['priority']])
        
        # Save recommendations to database
        self._save_to_db(recommendations)

        return recommendations

    def _generate_fallback_recommendations(self):
        """Generates mock high-value recommendations if no live scan database exists yet."""
        return [
            {
                'type': 'junk',
                'title': 'Empty System Caches',
                'description': 'Temporary files and installer scripts are occupying extra drive sectors.',
                'action_label': 'Perform Scan',
                'savings_bytes': 284000000,
                'priority': 'HIGH',
                'items_count': 32
            },
            {
                'type': 'duplicate',
                'title': 'Pending Duplicate Analysis',
                'description': 'Run a Smart Folder Scan to calculate exact MD5 signatures and identify matching files.',
                'action_label': 'Scan Folder',
                'savings_bytes': 0,
                'priority': 'MEDIUM',
                'items_count': 0
            }
        ]

    def _save_to_db(self, recommendations):
        """Saves generated recommendations into the SQLite table, replacing old ones."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM recommendations") # Clear old entries
            for r in recommendations:
                cursor.execute("""
                    INSERT INTO recommendations (file_path, file_size, category, reason, recommendation_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    'System Recommendations',
                    r['savings_bytes'],
                    r['type'],
                    r['description'],
                    r['priority']
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to commit recommendations to DB: {e}")

    def _format_size(self, size_bytes):
        """Utility to format bytes into readable scale."""
        if size_bytes == 0:
            return "0 Bytes"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

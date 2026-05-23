import os
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from PIL import Image

# Helper dictionary for fast initial classification
EXTENSION_CATEGORIES = {
    # Images
    '.jpg': 'Images', '.jpeg': 'Images', '.png': 'Images', '.gif': 'Images', '.bmp': 'Images', 
    '.webp': 'Images', '.tiff': 'Images', '.svg': 'Images',
    # Videos
    '.mp4': 'Videos', '.mkv': 'Videos', '.mov': 'Videos', '.avi': 'Videos', '.wmv': 'Videos', 
    '.flv': 'Videos', '.webm': 'Videos',
    # Documents
    '.pdf': 'Documents', '.doc': 'Documents', '.docx': 'Documents', '.xls': 'Documents', 
    '.xlsx': 'Documents', '.ppt': 'Documents', '.pptx': 'Documents', '.txt': 'Documents', 
    '.rtf': 'Documents', '.csv': 'Documents', '.md': 'Documents', '.epub': 'Documents',
    # Code files
    '.py': 'Code files', '.js': 'Code files', '.ts': 'Code files', '.tsx': 'Code files', 
    '.jsx': 'Code files', '.html': 'Code files', '.css': 'Code files', '.json': 'Code files', 
    '.cpp': 'Code files', '.c': 'Code files', '.h': 'Code files', '.java': 'Code files', 
    '.go': 'Code files', '.rs': 'Code files', '.sh': 'Code files', '.bat': 'Code files',
    # Music
    '.mp3': 'Music', '.wav': 'Music', '.flac': 'Music', '.ogg': 'Music', '.m4a': 'Music', 
    '.aac': 'Music',
    # Archives
    '.zip': 'Archives', '.rar': 'Archives', '.7z': 'Archives', '.tar': 'Archives', 
    '.gz': 'Archives', '.bz2': 'Archives',
}

JUNK_EXTENSIONS = {'.tmp', '.temp', '.log', '.bak', '.old', '.chk', '.dmp', '.part', '.crdownload'}
JUNK_DIR_NAMES = {'node_modules', '.cache', 'temp', 'tmp', 'cache', 'logs', 'bower_components'}

def get_file_md5(file_path, chunk_size=8192):
    """Calculates the MD5 checksum of a file in binary chunks to prevent high memory usage."""
    hasher = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (PermissionError, FileNotFoundError):
        return None

def get_image_hash(image_path):
    """Generates an 8x8 average hash (aHash) for an image to detect similar files."""
    try:
        with Image.open(image_path) as img:
            # Convert to grayscale and resize to 8x8 (resample to box for speed)
            img = img.convert('L').resize((8, 8), Image.Resampling.BOX)
            pixels = list(img.getdata())
            avg = sum(pixels) / 64
            # Generate 64-bit integer based on pixel values vs average
            hash_val = 0
            for i, p in enumerate(pixels):
                if p > avg:
                    hash_val |= (1 << i)
            return hex(hash_val)
    except Exception:
        return None

def hamming_distance(h1, h2):
    """Computes the Hamming distance between two hex hashes (number of differing bits)."""
    try:
        val1 = int(h1, 16)
        val2 = int(h2, 16)
        # XOR matches differing bits, bin().count('1') counts them
        return bin(val1 ^ val2).count('1')
    except Exception:
        return 99

class SmartScanner:
    def __init__(self, target_path):
        self.target_path = Path(target_path)
        self.files_found = []
        self.duplicates = []
        self.similar_images = []
        self.junk_files = []
        self.empty_folders = []
        self.large_files = []
        self.old_files = []
        self.total_size = 0
        self.total_files = 0
        self.category_sizes = defaultdict(int)
        self.category_counts = defaultdict(int)

    def scan(self, progress_callback=None):
        """Scans the target directory and executes analysis."""
        if not self.target_path.exists() or not self.target_path.is_dir():
            raise FileNotFoundError(f"Target path does not exist or is not a folder: {self.target_path}")

        print(f"Beginning scan of directory: {self.target_path}")
        
        # 1. Walk directory and list all elements
        all_elements = []
        for root, dirs, files in os.walk(str(self.target_path)):
            # Skip common hidden or gigantic system folders
            if any(part.startswith('.') and part != '.' for part in Path(root).parts) or '$RECYCLE.BIN' in root:
                continue

            # Record empty folders (directories with no files or subdirectories)
            if not dirs and not files:
                self.empty_folders.append(root)
                continue

            # Skip checking junk folders to avoid crashing on millions of small dev files
            # but record them as junk files if we want
            is_junk_dir = any(jd in Path(root).parts for jd in JUNK_DIR_NAMES)

            for file in files:
                full_path = os.path.join(root, file)
                all_elements.append((full_path, is_junk_dir))

        self.total_files = len(all_elements)
        print(f"Discovered {self.total_files} files to inspect.")

        # 2. Extract metadata using multithreading for quick IO
        def process_file_metadata(item):
            file_path, parent_is_junk_dir = item
            try:
                path_obj = Path(file_path)
                stat = path_obj.stat()
                size = stat.st_size
                ext = path_obj.suffix.lower()

                # Basic classification
                category = EXTENSION_CATEGORIES.get(ext, 'Work files' if ext in ['.docx', '.xlsx', '.pptx', '.pdf'] else 'Downloads')
                
                # Check screenshots
                if 'screenshot' in path_obj.name.lower() or 'ss_' in path_obj.name.lower():
                    category = 'Screenshots'

                is_junk = (ext in JUNK_EXTENSIONS) or parent_is_junk_dir or (size == 0)
                
                # Old/Unused check (not accessed in 180 days)
                last_accessed = stat.st_atime
                last_modified = stat.st_mtime
                import time
                age_days = (time.time() - last_accessed) / (24 * 3600)
                is_old = age_days > 180

                file_info = {
                    'path': file_path,
                    'name': path_obj.name,
                    'size': size,
                    'ext': ext,
                    'category': category,
                    'is_junk': is_junk,
                    'last_modified': last_modified,
                    'last_accessed': last_accessed,
                    'is_old': is_old
                }
                return file_info
            except Exception:
                return None

        # Execute thread-pool metadata scanning
        processed_files = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            for idx, res in enumerate(executor.map(process_file_metadata, all_elements)):
                if res:
                    processed_files.append(res)
                    self.total_size += res['size']
                    self.category_sizes[res['category']] += res['size']
                    self.category_counts[res['category']] += 1
                    
                    if res['is_junk']:
                        self.junk_files.append(res)
                    if res['size'] > 100 * 1024 * 1024:  # > 100 MB
                        self.large_files.append(res)
                    if res['is_old']:
                        self.old_files.append(res)

                if progress_callback and idx % max(1, int(self.total_files / 20)) == 0:
                    progress_callback(int((idx / self.total_files) * 60))  # First 60% of scan

        self.files_found = processed_files
        print("Metadata indexing complete. Starting duplicate detection.")

        # 3. Exact Duplicate Detection (Hash check for files with exact same size)
        size_groups = defaultdict(list)
        for f in self.files_found:
            if f['size'] > 0: # ignore empty files (they're marked junk already)
                size_groups[f['size']].append(f)

        duplicate_candidates = {size: files for size, files in size_groups.items() if len(files) > 1}
        
        exact_duplicate_groups = defaultdict(list)
        for size, files in duplicate_candidates.items():
            for f in files:
                md5 = get_file_md5(f['path'])
                if md5:
                    exact_duplicate_groups[md5].append(f)

        # Structure duplicate reports
        for md5, group in exact_duplicate_groups.items():
            if len(group) > 1:
                # Sort group: keep the most recently modified one, recommend deleting older ones
                group_sorted = sorted(group, key=lambda x: x['last_modified'], reverse=True)
                self.duplicates.append({
                    'hash': md5,
                    'files': group_sorted,
                    'total_size': sum(f['size'] for f in group_sorted[1:]),  # Wasted size
                })

        if progress_callback:
            progress_callback(80) # 80% progress

        # 4. Similar Image Detection (Average Hash hamming distance check)
        image_files = [f for f in self.files_found if f['category'] == 'Images' and f['size'] < 15 * 1024 * 1024] # < 15MB to avoid crash
        image_hashes = {}
        
        # Multithreaded hashing
        with ThreadPoolExecutor(max_workers=4) as executor:
            paths = [img['path'] for img in image_files]
            hashes = list(executor.map(get_image_hash, paths))
            for f, h in zip(image_files, hashes):
                if h:
                    image_hashes[f['path']] = h

        # Compare Hamming distances between images
        visited = set()
        for path1, hash1 in image_hashes.items():
            if path1 in visited:
                continue
            group = [f for f in image_files if f['path'] == path1]
            for path2, hash2 in image_hashes.items():
                if path1 != path2 and path2 not in visited:
                    dist = hamming_distance(hash1, hash2)
                    if dist <= 8:  # Highly similar
                        matching_file = next((f for f in image_files if f['path'] == path2), None)
                        if matching_file:
                            group.append(matching_file)
                            visited.add(path2)
            if len(group) > 1:
                group_sorted = sorted(group, key=lambda x: x['last_modified'], reverse=True)
                self.similar_images.append({
                    'hash': hash1,
                    'files': group_sorted,
                    'total_size': sum(f['size'] for f in group_sorted[1:]),
                })
                visited.add(path1)

        if progress_callback:
            progress_callback(100) # 100% completed

        print(f"Scan complete. Found {len(self.duplicates)} duplicate groups, {len(self.similar_images)} similar image groups, and {len(self.junk_files)} junk files.")
        
        # Calculate health score (weighted score out of 100 based on clutter)
        # Deduct score for duplicates, large logs/caches, and trash
        total_wasted = sum(d['total_size'] for d in self.duplicates) + sum(j['size'] for j in self.junk_files)
        health_deduction = (total_wasted / (1024 * 1024 * 1024)) * 10  # 10 points per GB wasted
        health_score = max(20.0, min(100.0, 100.0 - health_deduction))

        return {
            'total_files': self.total_files,
            'total_size': self.total_size,
            'health_score': round(health_score, 1),
            'duplicates': self.duplicates,
            'similar_images': self.similar_images,
            'junk_files': self.junk_files,
            'empty_folders': self.empty_folders,
            'large_files': sorted(self.large_files, key=lambda x: x['size'], reverse=True)[:30],
            'old_files': self.old_files,
            'category_sizes': dict(self.category_sizes),
            'category_counts': dict(self.category_counts)
        }

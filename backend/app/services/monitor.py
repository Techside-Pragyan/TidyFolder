import asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class WebSocketBroadcastHandler(FileSystemEventHandler):
    """Custom FileSystemEventHandler that forwards events to an asynchronous callback function."""
    def __init__(self, callback, loop):
        super().__init__()
        self.callback = callback
        self.loop = loop

    def on_created(self, event):
        if event.is_directory or Path(event.src_path).name.startswith('.'):
            return
        asyncio.run_coroutine_threadsafe(
            self.callback({
                'type': 'CREATED',
                'path': event.src_path,
                'name': Path(event.src_path).name,
                'is_dir': event.is_directory
            }),
            self.loop
        )

    def on_deleted(self, event):
        if event.is_directory or Path(event.src_path).name.startswith('.'):
            return
        asyncio.run_coroutine_threadsafe(
            self.callback({
                'type': 'DELETED',
                'path': event.src_path,
                'name': Path(event.src_path).name,
                'is_dir': event.is_directory
            }),
            self.loop
        )

    def on_modified(self, event):
        # Prevent spamming multiple modified triggers for a single write
        if event.is_directory or Path(event.src_path).name.startswith('.'):
            return
        asyncio.run_coroutine_threadsafe(
            self.callback({
                'type': 'MODIFIED',
                'path': event.src_path,
                'name': Path(event.src_path).name,
                'is_dir': event.is_directory
            }),
            self.loop
        )

    def on_moved(self, event):
        if event.is_directory or Path(event.src_path).name.startswith('.'):
            return
        asyncio.run_coroutine_threadsafe(
            self.callback({
                'type': 'MOVED',
                'src_path': event.src_path,
                'dest_path': event.dest_path,
                'name': Path(event.dest_path).name,
                'is_dir': event.is_directory
            }),
            self.loop
        )

class FolderWatcher:
    """Service to manage a background directory watcher and bridge events to WebSockets."""
    def __init__(self, target_path, broadcast_callback):
        self.target_path = Path(target_path)
        self.broadcast_callback = broadcast_callback
        self.observer = None

    def start(self):
        """Starts monitoring the target directory in a background thread."""
        if not self.target_path.exists() or not self.target_path.is_dir():
            raise FileNotFoundError(f"Cannot monitor non-existent folder: {self.target_path}")

        # Get current running asyncio event loop to bridge thread-safe calls
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        event_handler = WebSocketBroadcastHandler(self.broadcast_callback, loop)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.target_path), recursive=True)
        self.observer.start()
        print(f"Watchdog folder monitor successfully started on: {self.target_path}")

    def stop(self):
        """Stops the active folder monitor."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            print(f"Watchdog folder monitor stopped.")

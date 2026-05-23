import uvicorn
from app.db import init_db

if __name__ == "__main__":
    # Ensure database file and schema exist on startup
    init_db()
    
    # Run the Uvicorn high-performance server
    print("Launching Uvicorn server on 127.0.0.1:8000...")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

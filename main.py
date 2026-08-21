import sys
import os
import uvicorn

# Ensure the backend module is on the python search path
root_dir = os.path.dirname(os.path.abspath(__file__))
matching_dir = os.path.join(root_dir, "mentor_me_capstone", "matching")
if matching_dir not in sys.path:
    sys.path.insert(0, matching_dir)

# Import the FastAPI app instance
try:
    from backend.main import app
except ImportError:
    from mentor_me_capstone.matching.backend.main import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

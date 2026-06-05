"""Entry point for Canary-Agent application.

Supports running both directly and via Docker (Dockerfile uses 'python main.py').
"""
import asyncio
import sys
import os

# Ensure the project root is on path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from app.main import setup
    import uvicorn
    
    app = asyncio.run(setup())
    cfg = app.config
    uvicorn.run(app, host=cfg.host, port=cfg.port, lifespan="on")

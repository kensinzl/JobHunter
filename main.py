import os, sys
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

ROOT = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
from controller.controller import *
from controller.ats_controller import *
from controller.job_controller import *


if __name__ == "__main__":
    # if "--test-scrape" in sys.argv:
    #     prefs = {"keywords": "ai engineer", "location": "Sydney NSW"}
    #     print("Seek:", len(scrape_seek(prefs)), "jobs")
    #     print("LinkedIn:", len(scrape_linkedin(prefs)), "jobs")
    #     sys.exit(0)
    import uvicorn
    uvicorn.run(app, host = "127.0.0.1", port = 8000)

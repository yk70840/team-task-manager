import os
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates

load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
templates = Jinja2Templates(directory="app/templates")


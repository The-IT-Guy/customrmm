from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext

SECRET_KEY = "CHANGE_ME"
ALGORITHM = "HS256"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(p): return pwd.hash(p)
def verify_password(p, h): return pwd.verify(p, h)

def create_access_token(data):
    data["exp"] = datetime.utcnow() + timedelta(hours=8)
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

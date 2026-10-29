"""Create the standard TEST users (weak shared password - never run against production).

    python scripts/seed_test_users.py                    # create missing users, leave existing ones untouched
    python scripts/seed_test_users.py --reset-passwords  # also reset existing users' password/role/status
    python scripts/seed_test_users.py --password Other1! # use a different default password
    python scripts/seed_test_users.py --force            # allow a non-local MongoDB (refused by default)

Uses MONGODB_URI / MONGODB_DB from backend/.env, like the API does.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pymongo  # noqa: E402

    from app.core.config import get_settings  # noqa: E402
    from app.core.security import hash_password  # noqa: E402
except ModuleNotFoundError as e:
    sys.exit(f"Missing Python package '{e.name}'. Run this with the project's virtual environment:\n"
             "  .venv\\Scripts\\python scripts\\seed_test_users.py      (Windows cmd)\n"
             "or install the dependencies first:  pip install -r requirements.txt")

USERS = [
    ("admin@dsr.com", "Admin", "admin"),
    ("manager1@dsr.com", "Manager 1", "uploader"),
    ("manager2@dsr.com", "Manager 2", "uploader"),
    ("user@mail.com", "User", "viewer"),
    ("test@mail.com", "Test User", "viewer"),
]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "mongo"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--password", default="password")
    ap.add_argument("--reset-passwords", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    host = urlparse(s.mongodb_uri).hostname or ""
    if host not in LOCAL_HOSTS and not args.force:
        print(f"Refusing: MongoDB host '{host}' is not local and these accounts use a weak password. Use --force to override.")
        return 1
    if len(args.password) < 8:
        print("Password must be at least 8 characters.")
        return 1

    db = pymongo.MongoClient(s.mongodb_uri, serverSelectionTimeoutMS=3000)[s.mongodb_db]
    try:
        db.command("ping")
    except pymongo.errors.PyMongoError as e:
        print(f"Cannot reach MongoDB at {s.mongodb_uri}: {e}")
        return 1
    db.users.create_index("email", unique=True)

    print(f"Database: {s.mongodb_db}")
    for email, name, role in USERS:
        existing = db.users.find_one({"email": email})
        fields = {"name": name, "role": role, "status": "active", "passwordHash": hash_password(args.password)}
        if not existing:
            db.users.insert_one({"email": email, **fields, "createdAt": datetime.now(timezone.utc), "createdBy": "seed_test_users"})
            print(f"  created  {email:<20} {role}")
        elif args.reset_passwords:
            db.users.update_one({"_id": existing["_id"]}, {"$set": fields})
            print(f"  reset    {email:<20} {role}")
        else:
            print(f"  exists   {email:<20} {existing['role']} (unchanged; use --reset-passwords to reset)")
    print(f"Default password: {args.password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

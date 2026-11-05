import json
import sys
from pathlib import Path

# Add project root to sys.path so backend imports work reliably when executed directly
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas.ldap.directory import (
    LDAPOUCreate,
    LDAPUser,
    LDAPGroupCreate,
)
from services.ldap.ldap import LDAPService

# Current directory where json files live: backend/app/services/ldap/
CURRENT_DIR = Path(__file__).resolve().parent

# Note: Based on your tree, the OU file is named 'os.json' (or 'ous.json' if renamed)
OU_FILE = CURRENT_DIR / "os.json" if (CURRENT_DIR / "os.json").exists() else CURRENT_DIR / "ous.json"
USERS_FILE = CURRENT_DIR / "users.json"
GROUPS_FILE = CURRENT_DIR / "groups.json"


def check_result(operation: str, identifier: str, result: dict) -> None:
    """Print readable status output for each LDAP operation."""
    description = result.get("description", "Unknown")
    code = result.get("result", -1)

    if code == 0:
        print(f"[OK] {operation}: {identifier}")
    elif code == 68:  # LDAP code 68 = entryAlreadyExists
        print(f"[EXISTS] {operation}: {identifier} (Skipping, already present)")
    else:
        print(f"[ERROR {code}] {operation}: {identifier} -> {description}")


def seed_ous(service: LDAPService) -> None:
    print("\n--- Seeding Organizational Units (OUs) ---")
    if not OU_FILE.exists():
        print(f"[WARN] File not found: {OU_FILE}. Skipping OUs.")
        return

    with open(OU_FILE, "r", encoding="utf-8") as f:
        ous = json.load(f)

    for item in ous:
        ou_schema = LDAPOUCreate(**item)
        res = service.create_ou(ou_schema)
        check_result("OU", ou_schema.name, res)


def seed_users(service: LDAPService) -> None:
    print("\n--- Seeding Users ---")
    if not USERS_FILE.exists():
        print(f"[WARN] File not found: {USERS_FILE}. Skipping Users.")
        return

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)

    for item in users:
        user_schema = LDAPUser(**item)
        res = service.create_user(user_schema)
        check_result("User", user_schema.uid, res)


def seed_groups(service: LDAPService) -> None:
    print("\n--- Seeding Groups ---")
    if not GROUPS_FILE.exists():
        print(f"[WARN] File not found: {GROUPS_FILE}. Skipping Groups.")
        return

    with open(GROUPS_FILE, "r", encoding="utf-8") as f:
        groups = json.load(f)

    for item in groups:
        group_schema = LDAPGroupCreate(**item)
        res = service.create_group(group_schema)
        check_result("Group", group_schema.cn, res)


def main():
    print("Connecting to LDAP service...")
    try:
        service = LDAPService()
        print("Connected.")
    except Exception as e:
        print(f"[CRITICAL] Could not connect to LDAP server: {e}")
        sys.exit(1)

    # 1. OUs must be created first (provides tree structure for users & groups)
    seed_ous(service)

    # 2. Users must be created second
    seed_users(service)

    # 3. Groups are created last (since groupOfNames references member user DNs)
    seed_groups(service)

    print("\n[DONE] Directory seeding finished.")


if __name__ == "__main__":
    main()
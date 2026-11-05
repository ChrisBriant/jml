import sys
import json
from pathlib import Path
from ldap3 import SUBTREE

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import schemas
from schemas.ldap.directory import (
    LDAPUser,
    LDAPGroup,
    LDAPOU,
    LDAPTreeOU,
    LDAPDirectorySnapshot,
    LDAPDirectoryTree,
)
from services.ldap.ldap import LDAPService


def fetch_all_ous(service: LDAPService) -> list[LDAPOU]:
    """Retrieve all organizationalUnit entries."""
    service.connection.search(
        search_base=service.base_dn,
        search_filter="(objectClass=organizationalUnit)",
        search_scope=SUBTREE,
        attributes=["ou", "description", "objectClass"]
    )

    ous = []
    for entry in service.connection.entries:
        # Handle cases where 'ou' attribute returns a list or single value
        ou_name = str(entry.ou.values[0] if hasattr(entry.ou, "values") else entry.ou)
        desc = str(entry.description) if entry.description else None
        ous.append(
            LDAPOU(
                dn=entry.entry_dn,
                ou=ou_name,
                description=desc,
                object_classes=list(entry.objectClass)
            )
        )
    return ous


def build_directory_tree(
    base_dn: str,
    ous: list[LDAPOU],
    users: list[LDAPUser],
    groups: list[LDAPGroup],
) -> LDAPDirectoryTree:
    """Build a hierarchical LDAPDirectoryTree from flat object lists."""
    
    # 1. Map each OU DN to a mutable LDAPTreeOU structure
    ou_map: dict[str, LDAPTreeOU] = {
        ou.dn: LDAPTreeOU(
            ou=ou.ou,
            dn=ou.dn,
            description=ou.description,
            users=[],
            groups=[],
            children_ous=[]
        )
        for ou in ous
    }

    # 2. Assign Users to their direct parent OU
    for u in users:
        if u.dn:
            parent_dn = u.dn.split(",", 1)[1]
            if parent_dn in ou_map:
                ou_map[parent_dn].users.append(u)

    # 3. Assign Groups to their direct parent OU
    for g in groups:
        parent_dn = g.dn.split(",", 1)[1]
        if parent_dn in ou_map:
            ou_map[parent_dn].groups.append(g)

    # 4. Assemble parent-child OU relationships
    root_ous: list[LDAPTreeOU] = []
    for dn, tree_ou in ou_map.items():
        parent_dn = dn.split(",", 1)[1]
        if parent_dn.lower() == base_dn.lower():
            root_ous.append(tree_ou)
        elif parent_dn in ou_map:
            ou_map[parent_dn].children_ous.append(tree_ou)

    return LDAPDirectoryTree(base_dn=base_dn, root_ous=root_ous)


def print_ascii_tree(tree_ou: LDAPTreeOU, prefix: str = "") -> None:
    """Print an ASCII visual representation of the OU tree to the terminal."""
    print(f"{prefix}📁 OU: {tree_ou.ou} ({tree_ou.dn})")
    
    child_prefix = prefix + "    "
    for user in tree_ou.users:
        title = f" [{user.title}]" if user.title else ""
        print(f"{child_prefix}👤 {user.cn} ({user.uid}){title}")

    for group in tree_ou.groups:
        print(f"{child_prefix}👥 Group: {group.cn} ({len(group.members)} members)")

    for sub_ou in tree_ou.children_ous:
        print_ascii_tree(sub_ou, child_prefix)


def main():
    print("=" * 60)
    print("  CONNECTING TO LDAP & EXTRACTING DIRECTORY")
    print("=" * 60)

    service = LDAPService()

    # 1. Fetch all items
    ous = fetch_all_ous(service)
    users = service.get_users()
    groups = service.get_groups()

    # 2. Build both schemas
    snapshot = LDAPDirectorySnapshot(
        base_dn=service.base_dn,
        ous=ous,
        users=users,
        groups=groups,
    )
    tree = build_directory_tree(service.base_dn, ous, users, groups)

    # 3. Print to Terminal
    print(f"\n📊 Summary for Base DN: '{service.base_dn}'")
    print(f"  • Total OUs:    {len(ous)}")
    print(f"  • Total Users:  {len(users)}")
    print(f"  • Total Groups: {len(groups)}")

    print("\n🌳 Directory Structure:")
    print(f"[{service.base_dn}]")
    for root_ou in tree.root_ous:
        print_ascii_tree(root_ou, prefix="  ")

    # 4. Save JSON files to current working directory
    snapshot_filename = "directory_snapshot.json"
    tree_filename = "directory_tree.json"

    with open(snapshot_filename, "w", encoding="utf-8") as f:
        f.write(snapshot.model_dump_json(indent=2))

    with open(tree_filename, "w", encoding="utf-8") as f:
        f.write(tree.model_dump_json(indent=2))

    print("\n" + "=" * 60)
    print("  FILES SAVED TO CURRENT WORKING DIRECTORY")
    print("=" * 60)
    print(f"  ✓ {Path(snapshot_filename).resolve()}")
    print(f"  ✓ {Path(tree_filename).resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
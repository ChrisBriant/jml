import requests
from typing import Any, Dict, List, Optional
import asyncio
from services.jml.auth import get_token
import dotenv
import os
import json
from datetime import datetime, timezone
from pydantic import ValidationError
from database.jml.models.iga_user import IGAUser
from database.jml.db import AsyncSession, SessionLocal
from schemas.iga.iga import HREmployeeToIGAUser



dotenv_file = ".env"
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)

HR_ENDPOINT_URL = os.environ.get("HR_ENDPOINT_URL")

async def sync_hr_employees_and_report(
    jml_db: AsyncSession,
    employees_payload: List,
    source_system: str = "HR_SYSTEM",
) -> Dict[str, Any]:
    """
    Sync employees from the depaginated HR API payload into the JML database
    (IGAUser + IGAAudit) without provisioning to LDAP, and return a report
    with statistics and categorised employee lists.
    """
    items = employees_payload

    new_employees: List[Dict[str, Any]] = []
    moved_department_employees: List[Dict[str, Any]] = []
    changed_employees: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    unchanged_count = 0

    for raw_emp in items:
        raw_id = raw_emp.get("employee_id")
        raw_name = f"{raw_emp.get('first_name', '')} {raw_emp.get('last_name', '')}".strip()
        hr_department_name = (raw_emp.get("department") or {}).get("name")

        try:
            mapped = HREmployeeToIGAUser.model_validate(raw_emp)
        except ValidationError as exc:
            errors.append(
                {
                    "source_id": str(raw_id) if raw_id else None,
                    "employee_number": raw_emp.get("employee_number"),
                    "full_name": raw_name or None,
                    "reason": str(exc),
                }
            )
            continue

        iga_user, event_type, changed_fields = await IGAUser.upsert_from_source(
            db=jml_db,
            **mapped.to_upsert_kwargs(source_system=source_system),
        )

        if iga_user is None or event_type == "ERROR":
            errors.append(
                {
                    "source_id": str(mapped.source_id),
                    "employee_number": raw_emp.get("employee_number"),
                    "full_name": f"{mapped.first_name} {mapped.last_name}",
                    "reason": "Database integrity error while upserting IGAUser",
                }
            )
            continue

        if event_type == "UNCHANGED":
            unchanged_count += 1
            continue

        base_entry = {
            "user_id": str(iga_user.user_id),
            "source_id": iga_user.source_id,
            "employee_number": raw_emp.get("employee_number"),
            "username": iga_user.username,
            "full_name": f"{iga_user.first_name} {iga_user.last_name}",
            "email": iga_user.email,
            "job_title": iga_user.job_title,
            "department_id": str(iga_user.department_id) if iga_user.department_id else None,
            "department_name": hr_department_name,
            "employment_status": iga_user.employment_status.value,
        }

        if event_type == "JOINER":
            new_employees.append(
                {
                    **base_entry,
                    "start_date": iga_user.start_date.isoformat(),
                }
            )
        elif "department_id" in changed_fields:
            dept_change = changed_fields["department_id"]
            moved_department_employees.append(
                {
                    **base_entry,
                    "event_type": event_type,
                    "previous_department_id": dept_change["old"],
                    "new_department_id": dept_change["new"],
                    "changed_fields": changed_fields,
                }
            )
        else:
            changed_employees.append(
                {
                    **base_entry,
                    "event_type": event_type,
                    "changed_fields": changed_fields,
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_system": source_system,
        "statistics": {
            "total_processed": len(items),
            "new": len(new_employees),
            "moved_departments": len(moved_department_employees),
            "changed": len(changed_employees),
            "unchanged": unchanged_count,
            "errors": len(errors),
        },
        "employees": {
            "new": new_employees,
            "moved_departments": moved_department_employees,
            "changed": changed_employees,
            "errors": errors,
        },
    }


def print_sync_report(report: Dict[str, Any]) -> None:
    """Print a readable summary of the JML sync statistics and affected employees."""
    stats = report["statistics"]
    groups = report["employees"]

    print("=" * 60)
    print(f"JML HR SYNC REPORT ({report['generated_at']})")
    print("=" * 60)
    print(f"Total processed   : {stats['total_processed']}")
    print(f"New employees     : {stats['new']}")
    print(f"Moved departments : {stats['moved_departments']}")
    print(f"Changed (other)   : {stats['changed']}")
    print(f"Unchanged         : {stats['unchanged']}")
    print(f"Errors            : {stats['errors']}")
    print("-" * 60)

    print("\n[NEW EMPLOYEES]")
    if not groups["new"]:
        print("  None")
    for emp in groups["new"]:
        print(
            f"  - {emp['full_name']} ({emp['username'] or 'no-username'}) | "
            f"{emp['job_title']} | Dept: {emp['department_name'] or emp['department_id']} | "
            f"Status: {emp['employment_status']}"
        )

    print("\n[MOVED DEPARTMENTS]")
    if not groups["moved_departments"]:
        print("  None")
    for emp in groups["moved_departments"]:
        print(
            f"  - {emp['full_name']} ({emp['username'] or 'no-username'}) | "
            f"{emp['previous_department_id']} -> {emp['new_department_id']} "
            f"({emp['department_name'] or 'unknown'}) | "
            f"Fields: {', '.join(emp['changed_fields'].keys())}"
        )

    print("\n[CHANGED EMPLOYEES]")
    if not groups["changed"]:
        print("  None")
    for emp in groups["changed"]:
        changes = ", ".join(
            f"{field}: {vals['old']} -> {vals['new']}"
            for field, vals in emp["changed_fields"].items()
        )
        print(
            f"  - {emp['full_name']} ({emp['username'] or 'no-username'}) "
            f"[{emp['event_type']}] | {changes}"
        )

    if groups["errors"]:
        print("\n[ERRORS]")
        for err in groups["errors"]:
            print(
                f"  - {err['full_name'] or err['source_id']}: {err['reason']}"
            )

    print("=" * 60)


async def fetch_all_hr_employees(
    bearer_token: str,
    base_url: Optional[str] = None,
    page_size: int = 10,
    employment_status: Optional[str] = None,
    employment_type: Optional[str] = None,
    department_id: Optional[str] = None,
    manager_id: Optional[str] = None,
    search: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Fetch and depaginate all employees from GET /hr/employees using requests
    inside an async context via asyncio.to_thread.

    Returns:
        {"total": <int>, "items": [<employee_dict>, ...]}
    """
    resolved_base_url = (
        base_url
        or os.environ.get("HR_ENDPOINT_URL")
        or "http://localhost:8000"
    )
    url = f"{resolved_base_url.rstrip('/')}/hr/employees"

    clean_token = bearer_token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Accept": "application/json",
    }

    resolved_page_size = max(1, min(page_size, 200))

    base_params: Dict[str, Any] = {"page_size": resolved_page_size}
    if employment_status is not None:
        base_params["employment_status"] = employment_status
    if employment_type is not None:
        base_params["employment_type"] = employment_type
    if department_id is not None:
        base_params["department_id"] = department_id
    if manager_id is not None:
        base_params["manager_id"] = manager_id
    if search is not None:
        base_params["search"] = search

    def _fetch_sync() -> Dict[str, Any]:
        all_employees: List[Dict[str, Any]] = []
        page = 1

        with requests.Session() as session:
            session.headers.update(headers)

            while True:
                params = {**base_params, "page": page}
                response = session.get(url, params=params, timeout=timeout)
                response.raise_for_status()

                payload = response.json()
                items = payload.get("items", [])
                total = payload.get("total", 0)

                if not items:
                    break

                all_employees.extend(items)

                if len(all_employees) >= total or len(items) < resolved_page_size:
                    break

                page += 1

        return {
            "total": len(all_employees),
            "items": all_employees,
        }

    return await asyncio.to_thread(_fetch_sync)



async def main():
    #Get the token for sign in
    token = get_token()
    print("ACCESS TOKEN", token)
    all_employees = await fetch_all_hr_employees(token)
    print("EMPLOYEE 1", json.dumps(all_employees["items"][0],indent=4))
    async with SessionLocal() as session:
        jml_cycle_report = await sync_hr_employees_and_report(session,all_employees["items"])
        print("JML CYCLE REPORT", jml_cycle_report)

if __name__ == "__main__":
    asyncio.run(main())

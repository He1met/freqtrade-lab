"""Initialize only the authorized isolated Profile using project schema helpers."""
import json
from pathlib import Path
from lab.database import init_database, get_connection

ROOT = Path(__file__).resolve().parent
database = ROOT / "research.sqlite"
if database.exists():
    raise SystemExit("Existing database preserved; refusing duplicate initialization")
profile = json.loads((ROOT / "profile.json").read_text())
init_database(database)
connection = get_connection(database, must_exist=True)
try:
    columns = list(profile)
    connection.execute(
        "INSERT INTO research_profiles (" + ",".join(columns) + ") VALUES ("
        + ",".join("?" for _ in columns) + ")",
        [profile[column] for column in columns],
    )
    connection.commit()
    print(json.dumps({"database": str(database), "profile_id": profile["id"]}))
finally:
    connection.close()

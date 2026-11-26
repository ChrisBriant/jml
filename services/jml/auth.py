import requests
import dotenv
import os

dotenv_file = ".env"
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)


JML_PASSWORD = os.environ.get("JML_PASSWORD")
HR_ENDPOINT_URL = os.environ.get("HR_ENDPOINT_URL")

def get_token():
    response = requests.post(
        f"{HR_ENDPOINT_URL}/hr/login",
        json={
            "username": "jml",
            "password": JML_PASSWORD,
        },
        timeout=10,
    )

    response.raise_for_status()

    return response.json()["token"]
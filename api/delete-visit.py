"""Vercel serverless function: delete a visit row from coffee_data.csv via GitHub API."""

import base64
import csv
import io
import json
import os
from http.server import BaseHTTPRequestHandler

REPO = "vviggyy/coffeehour"
CSV_PATH = "coffee_data.csv"
BRANCH = "main"


def github_request(path, method="GET", body=None, token=None):
    import urllib.request

    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    if method == "GET":
        url += f"?ref={BRANCH}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "coffeehour-vercel",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        admin_pw = os.environ.get("ADMIN_PASSWORD")
        if not admin_pw:
            self._json(500, {"error": "ADMIN_PASSWORD not configured"})
            return

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            self._json(500, {"error": "GITHUB_TOKEN not configured"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._json(400, {"error": "Invalid JSON"})
            return

        password = payload.get("password", "")
        date = payload.get("date")
        arrival_time = payload.get("arrival_time")
        coffee_time = payload.get("coffee_time")
        people_ahead = payload.get("people_ahead")
        refills = payload.get("refills")

        if not password or password != admin_pw:
            self._json(403, {"error": "Wrong password"})
            return

        if not all([date, arrival_time, coffee_time]) or people_ahead is None or refills is None:
            self._json(400, {"error": "Missing visit fields"})
            return

        people_ahead = str(int(people_ahead))
        refills = str(int(refills))

        try:
            file_info = github_request(CSV_PATH, token=token)
        except Exception as e:
            self._json(500, {"error": f"Failed to fetch CSV: {e}"})
            return

        sha = file_info["sha"]
        csv_content = base64.b64decode(file_info["content"]).decode("utf-8")

        reader = csv.DictReader(io.StringIO(csv_content))
        fieldnames = reader.fieldnames
        kept_rows = []
        deleted = False
        for row in reader:
            if (not deleted
                    and row["date"] == date
                    and row["arrival_time"] == arrival_time
                    and row["coffee_time"] == coffee_time
                    and row["people_ahead"] == people_ahead
                    and row["refills"] == refills):
                deleted = True
                continue
            kept_rows.append(row)

        if not deleted:
            self._json(404, {"error": "No matching visit found"})
            return

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in kept_rows:
            writer.writerow(row)
        updated_csv = buf.getvalue()

        updated_b64 = base64.b64encode(updated_csv.encode("utf-8")).decode("ascii")
        commit_msg = f"Delete visit {date} {arrival_time} ({people_ahead} people)"
        try:
            github_request(
                CSV_PATH,
                method="PUT",
                body={
                    "message": commit_msg,
                    "content": updated_b64,
                    "sha": sha,
                    "branch": BRANCH,
                },
                token=token,
            )
        except Exception as e:
            self._json(500, {"error": f"Failed to commit: {e}"})
            return

        self._json(200, {"ok": True, "date": date, "arrival_time": arrival_time})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

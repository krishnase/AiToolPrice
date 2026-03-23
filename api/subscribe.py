"""
api/subscribe.py — Vercel serverless function
Saves email subscribers to Supabase.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import psycopg2
import re

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors()
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            email = data.get("email", "").strip().lower()

            if not email or not EMAIL_RE.match(email):
                self._json(400, {"error": "Invalid email address."})
                return

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO subscribers (email)
                VALUES (%s)
                ON CONFLICT (email) DO NOTHING
                """,
                (email,),
            )
            inserted = cur.rowcount
            conn.commit()
            conn.close()

            if inserted:
                self._json(200, {"message": "Subscribed! We'll alert you when prices change."})
            else:
                self._json(200, {"message": "You're already subscribed!"})

        except Exception as e:
            self._json(500, {"error": "Something went wrong. Please try again."})

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "https://aitoolprice.com")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress default access logs

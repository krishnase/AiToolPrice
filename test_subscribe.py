"""Quick local test for the subscribe API logic."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import get_connection

def test_subscribe(email):
    import re
    EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

    if not EMAIL_RE.match(email):
        print(f"❌ Invalid email: {email}")
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO subscribers (email) VALUES (%s) ON CONFLICT (email) DO NOTHING",
        (email,),
    )
    inserted = cur.rowcount
    conn.commit()

    if inserted:
        print(f"✅ Subscribed: {email}")
    else:
        print(f"ℹ️  Already subscribed: {email}")

    # Show all subscribers
    cur.execute("SELECT email, subscribed_at FROM subscribers ORDER BY subscribed_at DESC")
    rows = cur.fetchall()
    print(f"\n📋 Total subscribers: {len(rows)}")
    for row in rows:
        print(f"   {row[0]}  —  {row[1].strftime('%Y-%m-%d %H:%M')}")

    conn.close()

if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "test@example.com"
    test_subscribe(email)

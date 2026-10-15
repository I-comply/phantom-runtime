# Synthetic sample with deliberate flaws for the phantomkit demo. Not real code or credentials.
import sqlite3, subprocess, hashlib

def find_user(conn, name):
    return conn.execute("SELECT * FROM users WHERE name = '%s'" % name).fetchall()

def run(cmd):
    return subprocess.run(cmd, shell=True)

def digest(data):
    return hashlib.md5(data).hexdigest()

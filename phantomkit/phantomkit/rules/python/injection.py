import os, subprocess, pickle
from flask import request


def a(x):
    # ruleid: phantom.python.dangerous-eval
    eval(x)
    # ruleid: phantom.python.dangerous-eval
    exec("print(%s)" % x)
    # ok: phantom.python.dangerous-eval
    eval("1 + 1")


def b(cmd):
    # ruleid: phantom.python.subprocess-shell-true
    subprocess.run(cmd, shell=True)
    # ok: phantom.python.subprocess-shell-true
    subprocess.run("ls -l", shell=True)
    # ok: phantom.python.subprocess-shell-true
    subprocess.run(["ls", cmd])
    # ruleid: phantom.python.os-system-nonliteral
    os.system("ping " + cmd)
    # ok: phantom.python.os-system-nonliteral
    os.system("ls")


def c(cur, uid, name):
    # ruleid: phantom.python.sql-string-building
    cur.execute("SELECT * FROM t WHERE id=" + uid)
    # ruleid: phantom.python.sql-string-building
    cur.execute("SELECT * FROM t WHERE n='%s'" % name)
    # ruleid: phantom.python.sql-string-building
    cur.execute(f"SELECT * FROM t WHERE id={uid}")
    # ruleid: phantom.python.sql-string-building
    cur.execute("SELECT {}".format(uid))
    # ok: phantom.python.sql-string-building
    cur.execute("SELECT * FROM t WHERE id=%s", (uid,))


def d(cur):
    uid = request.args.get("id")
    q = "SELECT * FROM t WHERE id=" + uid
    # ruleid: phantom.python.taint-sql-injection
    cur.execute(q)
    n = int(request.args.get("n"))
    # ruleid: phantom.python.sql-string-building
    # ok: phantom.python.taint-sql-injection
    cur.execute("SELECT %s" % n)
    # ok: phantom.python.taint-sql-injection
    cur.execute("SELECT 1")


def e():
    host = request.form["host"]
    # ruleid: phantom.python.taint-command-injection, phantom.python.os-system-nonliteral
    os.system("ping -c1 " + host)
    safe = request.form["h2"]
    # ruleid: phantom.python.os-system-nonliteral
    # ok: phantom.python.taint-command-injection
    os.system("ping -c1 " + shlex.quote(safe))


def f():
    code = request.args.get("c")
    # ruleid: phantom.python.taint-code-injection, phantom.python.dangerous-eval
    eval(code)


def g():
    name = request.args.get("file")
    # ruleid: phantom.python.taint-path-traversal
    with open("/data/" + name) as fh:
        return fh.read()
    # ok: phantom.python.taint-path-traversal
    open(secure_filename(name))


def h():
    url = request.args.get("u")
    # ruleid: phantom.python.taint-ssrf
    requests.get(url)
    # ok: phantom.python.taint-ssrf
    requests.get("https://api.example.com")


def i():
    nm = request.args.get("n")
    # ruleid: phantom.python.taint-xss
    return render_template_string("<h1>" + nm + "</h1>")
    # ok: phantom.python.taint-xss
    return render_template_string("<h1>" + escape(nm) + "</h1>")


def j():
    nxt = request.args.get("next")
    # ruleid: phantom.python.taint-open-redirect
    return redirect(nxt)
    # ok: phantom.python.taint-open-redirect
    return redirect(url_for("home"))

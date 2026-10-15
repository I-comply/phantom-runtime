app = Flask(__name__)
# ruleid: phantom.python.flask-debug-enabled, phantom.python.bind-all-interfaces
app.run(host="0.0.0.0", debug=True)
# ok: phantom.python.flask-debug-enabled
app.run(debug=False)

# ruleid: phantom.python.hardcoded-secret-key
app.config["SECRET_KEY"] = "dev-secret-123"
# ok: phantom.python.hardcoded-secret-key
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]

# ruleid: phantom.python.insecure-cookie
resp.set_cookie("sid", sid, secure=False)
# ok: phantom.python.insecure-cookie
resp.set_cookie("sid", sid, secure=True, httponly=True)

# ruleid: phantom.python.csrf-exempt
@csrf_exempt
def hook(request):
    pass

# ruleid: phantom.python.mark-safe-nonliteral
html = mark_safe(user_html)
# ok: phantom.python.mark-safe-nonliteral
html = mark_safe("<b>x</b>")

# ruleid: phantom.python.requests-no-timeout
requests.get("https://example.com")
# ok: phantom.python.requests-no-timeout
requests.get("https://example.com", timeout=5)

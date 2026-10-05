FROM python:3.11-slim

# Deliberately root: app/core/sandbox.py's subprocess driver drops privilege to
# an unprivileged uid (65534) for each plugin/strategy execution, which needs
# CAP_SETUID — i.e. needs this process to start as root. Do not add a USER
# directive here without also granting that capability some other way, or the
# sandbox will fail closed (see sandbox.py's PermissionError handling) rather
# than silently execute code as the app's own user.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]

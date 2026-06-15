FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py platform_sso.py dashboard.html ./

CMD ["gunicorn", "-b", ":8080", "main:app"]
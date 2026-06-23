FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py definitions_seed.py ./
# Drop root: least privilege. This job seeds client_<c>.seed_* tables, reads/writes the status
# bucket's definitions/*.json, and RUNs the <c>-export + status-export jobs (run.invoker, not actAs).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
CMD ["python", "main.py"]

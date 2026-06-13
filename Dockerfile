FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/ ./packages/
ENV MEKICORE_WORKSPACE=/app/workspace
RUN mkdir -p /app/workspace
EXPOSE 8080
CMD ["python", "packages/mekichat/app.py"]

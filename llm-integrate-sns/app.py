import os
import json
import time
import requests
import boto3
from fastapi import FastAPI, Request

app = FastAPI()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")
LIST_SNS_TOPIC_ARN = json.loads(os.getenv("LIST_SNS_TOPIC_ARN", "{}"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")

logs_client = boto3.client("logs", region_name=AWS_REGION)
sns_client = boto3.client("sns", region_name=AWS_REGION)


def get_recent_error_logs(log_group_name: str) -> str:
    end_time = int(time.time() * 1000)
    start_time = end_time - (3600 * 1000)  # 1 jam terakhir

    try:
        response = logs_client.filter_log_events(
            logGroupName=log_group_name,
            startTime=start_time,
            endTime=end_time,
            filterPattern="ERROR",
        )
        events = response.get("events", [])
        # Ambil 5 log error terbaru
        latest_events = events[-5:] if len(events) > 5 else events
        if not latest_events:
            return "Tidak ditemukan log ERROR spesifik dalam 1 jam terakhir."
        return "\n".join([e["message"] for e in latest_events])
    except Exception as e:
        return f"Gagal mengambil log dari CloudWatch: {str(e)}"


def ask_llm(error_logs: str) -> str:
    prompt = (
        "Sebagai DevOps, berikan 1 ringkasan penyebab error (Summary) "
        "dan 1 rekomendasi (Solusi) dari semua log berikut.\n\n"
        f"{error_logs}"
    )

    if LLM_PROVIDER == "ollama":
        resp = requests.post(
            OLLAMA_ENDPOINT,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "Tidak ada respons dari Ollama.")

    elif LLM_PROVIDER == "groq":
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return "LLM_PROVIDER tidak valid."


@app.post("/webhook")
async def sns_webhook(request: Request):
    raw_body = await request.body()
    payload = json.loads(raw_body.decode("utf-8"))
    msg_type = payload.get("Type")

    # 1. Konfirmasi langganan SNS otomatis
    if msg_type == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL")
        if subscribe_url:
            requests.get(subscribe_url, timeout=15)
        return {"status": "Subscription confirmed"}

    # 2. Proses Notifikasi Alarm CloudWatch
    if msg_type == "Notification":
        message = json.loads(payload.get("Message", "{}"))
        alarm_name = message.get("AlarmName", "UnknownAlarm")

        log_group = LIST_SNS_TOPIC_ARN.get(alarm_name)
        if log_group:
            error_logs = get_recent_error_logs(log_group)
        else:
            error_logs = f"Log group untuk alarm {alarm_name} tidak ditemukan di LIST_SNS_TOPIC_ARN."

        # 3. Analisis dengan LLM
        analysis = ask_llm(error_logs)

        # 4. Publish laporan kembali ke SNS
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Resume Incident Report: {alarm_name}",
            Message=analysis,
        )
        return {"status": "Incident report published", "alarm": alarm_name}

    return {"status": "Ignored"}
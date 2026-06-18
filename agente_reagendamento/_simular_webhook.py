"""Script temporário: processa localmente a resposta '1' do lead teste,
simulando o payload que o Gupshup entregaria ao webhook."""
import time

import main

payload = {
    "app": "Number02",
    "timestamp": int(time.time() * 1000),
    "version": 2,
    "type": "message",
    "payload": {
        "id": "simulado-local-resposta-1",
        "source": "5511989171391",
        "type": "text",
        "payload": {"text": "1"},
        "sender": {"phone": "5511989171391", "name": "Roberto"},
    },
}

main.processar_resposta_webhook(payload)
print("OK — webhook processado")

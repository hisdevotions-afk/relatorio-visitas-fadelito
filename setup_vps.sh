#!/bin/bash
# Setup inicial do servidor VPS para relatorio_visitas + agente_reagendamento.
# Execute uma vez após clonar o repositório:
#   chmod +x setup_vps.sh && ./setup_vps.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="reagendamento"

echo "=== Setup VPS ==="
echo "Diretório: $REPO_DIR"

# Dependências Python
echo "[1/5] Instalando dependências Python..."
pip install -r "$REPO_DIR/requirements.txt"
pip install fastapi uvicorn

# Diretório de logs
echo "[2/5] Criando diretório de logs..."
mkdir -p "$REPO_DIR/agente_reagendamento/logs"

# .env
echo "[3/5] Verificando .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  [ATENÇÃO] Arquivo .env criado. Edite com suas credenciais antes de continuar:"
    echo "    nano $REPO_DIR/.env"
    echo ""
    echo "  Depois rode novamente: ./setup_vps.sh"
    exit 1
fi

# Systemd — servidor de webhook 24/7
echo "[4/5] Configurando serviço systemd ($SERVICE_NAME)..."
CURRENT_USER=$(whoami)
sed "s|/opt/relatorio-visitas|$REPO_DIR|g; s|User=ubuntu|User=$CURRENT_USER|g" \
    "$REPO_DIR/agente_reagendamento/reagendamento.service" \
    > /etc/systemd/system/$SERVICE_NAME.service

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME
echo "  Serviço $SERVICE_NAME iniciado e habilitado no boot."
echo "  Status: $(systemctl is-active $SERVICE_NAME)"

# Cron — envio diário às 10h30 BRT
echo "[5/5] Configurando cron..."
CRON_REL="0 13 * * 1-5 cd $REPO_DIR && python relatorio_visitas.py >> /var/log/relatorio_visitas.log 2>&1"
CRON_AGT="30 13 * * 1-5 cd $REPO_DIR/agente_reagendamento && python main.py --processar >> /var/log/agente_reagendamento.log 2>&1"

( crontab -l 2>/dev/null | grep -v "relatorio_visitas\|agente_reagendamento"
  echo "$CRON_REL"
  echo "$CRON_AGT"
) | crontab -
echo "  Cron configurado."

echo ""
echo "=== Setup concluído ==="
echo ""
echo "Serviço webhook:  systemctl status $SERVICE_NAME"
echo "Logs webhook:     journalctl -u $SERVICE_NAME -f"
echo "Logs relatório:   tail -f /var/log/relatorio_visitas.log"
echo "Logs agente:      tail -f /var/log/agente_reagendamento.log"
echo ""
echo "Configure no Z-API → Webhooks → Ao receber mensagem:"
VPS_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<IP_DO_VPS>")
echo "  http://$VPS_IP:8000/webhook"

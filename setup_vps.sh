#!/bin/bash
# Setup inicial do servidor VPS para relatorio_visitas + agente_reagendamento.
# Execute uma vez após clonar o repositório:
#   chmod +x setup_vps.sh && ./setup_vps.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Setup VPS ==="
echo "Diretório: $REPO_DIR"

# Dependências Python
echo "[1/4] Instalando dependências Python..."
pip install -r "$REPO_DIR/requirements.txt"
pip install fastapi uvicorn  # servidor de webhook

# Diretório de logs
echo "[2/4] Criando diretório de logs..."
mkdir -p "$REPO_DIR/agente_reagendamento/logs"

# .env
echo "[3/4] Verificando .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  [ATENÇÃO] Arquivo .env criado a partir do .env.example."
    echo "  Edite com suas credenciais antes de continuar:"
    echo "    nano $REPO_DIR/.env"
    echo ""
fi

# Cron
echo "[4/4] Sugestão de cron (execute: crontab -e)"
cat <<CRON

# Relatório diário — puxa leads faltados da API Gendo → Google Sheets
# 10h Brasília (UTC-3)
0 13 * * 1-5 cd $REPO_DIR && python relatorio_visitas.py >> /var/log/relatorio_visitas.log 2>&1

# Agente reagendamento — envia mensagens WhatsApp para leads pendentes
# 10h30 Brasília (executa 30 min após o relatório para garantir que a aba existe)
30 13 * * 1-5 cd $REPO_DIR/agente_reagendamento && python main.py --processar >> /var/log/agente_reagendamento.log 2>&1

CRON

echo "=== Para rodar o servidor de webhook (recebe respostas do WhatsApp) ==="
echo "  cd $REPO_DIR/agente_reagendamento"
echo "  uvicorn server:app --host 0.0.0.0 --port 8000"
echo ""
echo "  Configure no Z-API: Webhooks → Ao receber mensagem:"
echo "  http://<IP_DO_VPS>:8000/webhook"
echo ""
echo "=== Setup concluído ==="

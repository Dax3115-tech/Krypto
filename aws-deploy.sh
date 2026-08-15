#!/bin/bash
# AWS EC2 Deployment Script for Algo Trader
# Run this on your EC2 instance

set -e

echo "================================"
echo "Algo Trader - AWS EC2 Setup"
echo "================================"

# Update system
echo "[1/10] Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
echo "[2/10] Installing Docker..."
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

# Install Docker Compose
echo "[3/10] Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add ubuntu user to docker group
echo "[4/10] Configuring Docker permissions..."
sudo usermod -aG docker ubuntu
newgrp docker

# Clone repository
echo "[5/10] Cloning repository..."
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/algo-trader.git
cd algo-trader/algo-trader

# Create .env file
echo "[6/10] Setting up environment variables..."
cat > .env << EOF
ALPACA_API_KEY=YOUR_API_KEY_HERE
ALPACA_SECRET_KEY=YOUR_SECRET_KEY_HERE
ALPACA_BASE_URL=https://paper-api.alpaca.markets
DATABASE_URL=postgresql://postgres:Reena2220@postgres:5432/algotrader
TRADING_SYMBOLS=SPY,QQQ,AAPL
MAX_POSITION_SIZE=0.10
MAX_DAILY_LOSS=0.03
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
MAX_OPEN_POSITIONS=5
FLASK_SECRET_KEY=your-secret-key-here
DASHBOARD_PORT=5000
ENV=paper
LOG_LEVEL=INFO
EOF

echo "⚠️  IMPORTANT: Edit .env with your Alpaca credentials:"
echo "   nano /home/ubuntu/algo-trader/algo-trader/.env"

# Start with Docker Compose
echo "[7/10] Starting Docker containers..."
docker-compose up -d

# Wait for services to start
echo "[8/10] Waiting for services to start..."
sleep 10

# Check status
echo "[9/10] Checking container status..."
docker-compose ps

# Setup monitoring
echo "[10/10] Setting up monitoring..."
sudo apt-get install -y htop

echo ""
echo "================================"
echo "✅ Setup Complete!"
echo "================================"
echo ""
echo "Dashboard: http://YOUR_EC2_IP:5000"
echo ""
echo "Useful commands:"
echo "  docker-compose logs -f              # View logs"
echo "  docker-compose ps                   # Check status"
echo "  docker-compose restart              # Restart services"
echo "  docker-compose down                 # Stop services"
echo ""
echo "Security tips:"
echo "  1. Update .env with your Alpaca credentials"
echo "  2. Configure security group to allow port 5000 only from your IP"
echo "  3. Setup SSH key authentication"
echo "  4. Enable monitoring for AWS costs"
echo ""

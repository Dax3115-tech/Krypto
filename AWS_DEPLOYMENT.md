# AWS EC2 Deployment Guide for Algo Trader

## Prerequisites
- AWS Account (Free tier eligible)
- GitHub account with your repo pushed
- Alpaca API credentials

## Step 1: Create AWS EC2 Instance (Free Tier)

### 1.1 Launch EC2 Instance
1. Go to [AWS Console](https://console.aws.amazon.com)
2. Navigate to **EC2 Dashboard**
3. Click **Launch Instances**
4. Choose **Ubuntu 22.04 LTS** (Free tier eligible)
5. Instance type: **t2.micro** (Free tier)
6. Storage: **30 GB** (Free tier)

### 1.2 Configure Security Group
1. Create new security group or edit
2. **Inbound Rules:**
   - SSH (22): From your IP or 0.0.0.0/0 (less secure)
   - HTTP (80): 0.0.0.0/0
   - HTTPS (443): 0.0.0.0/0
   - Custom TCP (5000): From your IP (Flask Dashboard)
   - Custom TCP (5432): Only from this security group (PostgreSQL)

### 1.3 Key Pair
1. Create new key pair: `algo-trader-key.pem`
2. Download and save securely
3. Set permissions: `chmod 400 algo-trader-key.pem`

## Step 2: Connect to EC2 Instance

```bash
# SSH into your instance
ssh -i algo-trader-key.pem ubuntu@YOUR_EC2_PUBLIC_IP

# Example:
ssh -i algo-trader-key.pem ubuntu@ec2-54-123-456-789.compute-1.amazonaws.com
```

## Step 3: Automated Deployment

```bash
# Download and run deployment script
curl -O https://raw.githubusercontent.com/YOUR_USERNAME/algo-trader/main/algo-trader/aws-deploy.sh
chmod +x aws-deploy.sh
./aws-deploy.sh
```

## Step 4: Manual Setup (If automated fails)

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y docker.io docker-compose git

# Add user to docker group
sudo usermod -aG docker ubuntu
newgrp docker

# Clone repository
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/algo-trader.git
cd algo-trader/algo-trader

# Create .env file
nano .env
# Paste your Alpaca credentials and save (Ctrl+X, Y, Enter)

# Start services
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

## Step 5: Configure Environment

Edit the `.env` file with your Alpaca credentials:

```bash
nano .env
```

Replace:
```
ALPACA_API_KEY=YOUR_API_KEY
ALPACA_SECRET_KEY=YOUR_SECRET_KEY
FLASK_SECRET_KEY=your-random-secret-key
```

Save and restart:
```bash
docker-compose restart algo-trader
```

## Step 6: Access Dashboard

Open in your browser:
```
http://YOUR_EC2_PUBLIC_IP:5000
```

## Monitoring & Logs

```bash
# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f algo-trader
docker-compose logs -f postgres

# Check container status
docker-compose ps

# SSH into container
docker-compose exec algo-trader bash

# Check resource usage
docker stats

# Stop services
docker-compose stop

# Restart services
docker-compose restart

# Remove all containers
docker-compose down -v
```

## Database Backup

```bash
# Backup PostgreSQL database
docker-compose exec postgres pg_dump -U postgres algotrader > backup.sql

# Restore from backup
docker-compose exec -T postgres psql -U postgres algotrader < backup.sql
```

## Troubleshooting

### Container won't start
```bash
docker-compose logs algo-trader
```

### Port already in use
```bash
# Check what's using port 5000
sudo lsof -i :5000

# Kill the process
sudo kill -9 <PID>
```

### Database connection error
```bash
# Verify PostgreSQL is running
docker-compose ps

# Restart database
docker-compose restart postgres
```

### Out of disk space
```bash
# Check disk usage
df -h

# Clean up Docker
docker system prune -a
```

## Cost Optimization (Free Tier)

✅ **Free for 12 months:**
- t2.micro EC2 instance
- 20 GB storage
- RDS free tier (if using instead of Docker)

**Estimated costs after free tier:**
- EC2 t2.micro: ~$9.50/month
- Storage: ~$1/month
- Data transfer: Varies
- **Total: ~$10-15/month**

## Security Best Practices

1. **SSH Key**: Keep `algo-trader-key.pem` secure
2. **Security Groups**: Restrict access to necessary ports
3. **Environment Variables**: Never commit `.env` to git
4. **Updates**: Run `sudo apt-get update && upgrade` regularly
5. **Monitoring**: Enable CloudWatch alerts for unusual activity
6. **Backups**: Backup database regularly

## Auto-Start on Reboot

Create systemd service:

```bash
sudo nano /etc/systemd/system/algo-trader.service
```

Paste:
```ini
[Unit]
Description=Algo Trader Docker Compose
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/algo-trader/algo-trader
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down
Restart=no

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable algo-trader.service
sudo systemctl start algo-trader.service
```

## Production Deployment Checklist

- [ ] EC2 instance launched (t2.micro)
- [ ] Security groups configured
- [ ] SSH key downloaded and secured
- [ ] Repository pushed to GitHub
- [ ] `.env` updated with credentials
- [ ] Docker deployed successfully
- [ ] Dashboard accessible on port 5000
- [ ] Logs showing trading activity
- [ ] Database backing up
- [ ] Auto-restart configured
- [ ] CloudWatch monitoring enabled
- [ ] Cost alerts set up

## Next Steps

1. **Monitor Performance**: Check dashboard and logs daily
2. **Scale Up**: When free tier ends, consider t2.small or t3.micro
3. **Database**: For production, use AWS RDS instead of Docker
4. **Load Balancer**: For high traffic, add Application Load Balancer
5. **CI/CD**: Set up GitHub Actions for auto-deployment

## Support

- AWS Support: https://console.aws.amazon.com/support
- Docker Docs: https://docs.docker.com
- EC2 Documentation: https://docs.aws.amazon.com/ec2/

---

**Last Updated**: 2026-08-14

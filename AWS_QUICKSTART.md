# 🚀 AWS EC2 Quick Start Guide

## ⚡ Fastest Deployment (CloudFormation - 5 minutes)

### 1. Go to AWS CloudFormation Console
```
https://console.aws.amazon.com/cloudformation
```

### 2. Click "Create Stack"
- Upload file: `cloudformation-template.yaml`
- Next

### 3. Fill in Stack Details
- **Stack name**: `algo-trader-stack`
- **Instance Type**: `t2.micro` (Free tier)
- **KeyName**: Select your EC2 key pair
- **GitHubRepository**: `https://github.com/YOUR_USERNAME/algo-trader.git`
- **AlpacaApiKey**: Your Alpaca API key
- **AlpacaSecretKey**: Your Alpaca secret key
- **SSHLocation**: Your IP (e.g., 123.45.67.89/32) or 0.0.0.0/0
- Next → Create Stack

### 4. Wait for Stack Creation
- Status changes to `CREATE_COMPLETE` (5-10 minutes)
- Check **Outputs** tab for:
  - Instance Public IP
  - Dashboard URL
  - SSH Command

### 5. Access Your Dashboard
```
http://YOUR_PUBLIC_IP:5000
```

---

## 📋 Manual Deployment (10 minutes)

### Step 1: Create EC2 Key Pair
```bash
# Download your key pair from AWS Console
# Save as: algo-trader-key.pem
# Set permissions
chmod 400 algo-trader-key.pem
```

### Step 2: Launch EC2 Instance
- **AMI**: Ubuntu 22.04 LTS (free tier)
- **Instance Type**: t2.micro
- **Security Groups**: Allow SSH (22), HTTP (80), HTTPS (443), TCP 5000
- **Storage**: 30 GB (free tier)

### Step 3: Connect to Instance
```bash
ssh -i algo-trader-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

### Step 4: Run Deployment Script
```bash
# On your EC2 instance
curl -O https://raw.githubusercontent.com/YOUR_USERNAME/algo-trader/main/algo-trader/aws-deploy.sh
chmod +x aws-deploy.sh
./aws-deploy.sh
```

### Step 5: Configure Credentials
```bash
cd /home/ubuntu/algo-trader/algo-trader
nano .env
# Edit with your Alpaca credentials and save
docker-compose restart algo-trader
```

---

## 🔍 Useful Commands

```bash
# View logs
docker-compose logs -f

# Check container status
docker-compose ps

# Restart services
docker-compose restart

# SSH into bot
docker-compose exec algo-trader bash

# View database
docker-compose exec postgres psql -U postgres -d algotrader

# Stop everything
docker-compose down

# Clean up
docker system prune -a
```

---

## 📊 Monitoring Dashboard

Access via browser:
```
http://YOUR_EC2_PUBLIC_IP:5000
```

Features:
- Real-time trading signals
- Position management
- P&L tracking
- Risk metrics

---

## 💰 Free Tier Costs (12 months)
✅ **FREE**
- t2.micro EC2 instance (1 year)
- 30 GB storage
- Data transfer (limited)

**After free tier**: ~$10-15/month

---

## 🔐 Security Checklist

- [ ] EC2 key pair downloaded securely
- [ ] Security groups restrict access
- [ ] .env file with credentials
- [ ] SSH key authentication enabled
- [ ] Regular backups scheduled
- [ ] CloudWatch monitoring enabled
- [ ] Cost alerts configured

---

## ⚠️ Important Notes

1. **Never commit .env** to GitHub (it's in .gitignore)
2. **Keep API keys secure** - regenerate if exposed
3. **Paper trading mode** by default (ALPACA_BASE_URL)
4. **Database**: PostgreSQL runs in Docker
5. **Logs**: Check `/home/ubuntu/algo-trader/algo-trader/logs/`

---

## 🐛 Troubleshooting

**Container won't start?**
```bash
docker-compose logs algo-trader
```

**Port 5000 in use?**
```bash
sudo lsof -i :5000
sudo kill -9 <PID>
```

**Database connection error?**
```bash
docker-compose restart postgres
docker-compose logs postgres
```

**Out of disk space?**
```bash
df -h
docker system prune -a
```

---

## 📈 Next Steps

1. ✅ Deploy to AWS EC2
2. ✅ Configure Alpaca credentials
3. ✅ Access dashboard
4. ⏭️ **Monitor trading activity** (logs & dashboard)
5. ⏭️ **Adjust risk parameters** (MAX_DAILY_LOSS, STOP_LOSS_PCT)
6. ⏭️ **Add more strategies** (if needed)
7. ⏭️ **Upgrade to production** (live trading, larger instance)

---

## 📞 Support

- **AWS Docs**: https://docs.aws.amazon.com/ec2/
- **Docker Docs**: https://docs.docker.com/
- **Alpaca Docs**: https://docs.alpaca.markets/
- **This Project**: Check AWS_DEPLOYMENT.md for detailed guide

---

**Last Updated**: 2026-08-14  
**Status**: ✅ Ready for Production

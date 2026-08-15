# 🚀 AWS CloudFormation - Simplified Deployment Guide

## ✨ Key Improvements Over Original Template

✅ **No SSH Key Required** - Use AWS Session Manager instead  
✅ **Fewer Parameters** - Only 5 required fields  
✅ **Automatic Configuration** - Environment variables auto-generated  
✅ **Simplified Security** - Better defaults  
✅ **Browser-Based Terminal** - No downloads needed  

---

## ⚡ Super Quick Start (3 Steps)

### **Step 1: Open CloudFormation Console**
Click here → https://console.aws.amazon.com/cloudformation/

### **Step 2: Create Stack**
- Click **Create stack** → **With new resources (standard)**
- Choose **Upload a template file**
- Upload: `cloudformation-simple.yaml`
- Click **Next**

### **Step 3: Fill Parameters**

| Field | Example | Notes |
|-------|---------|-------|
| **Stack name** | `algo-trader` | Any name you like |
| **InstanceType** | `t2.micro` | Free tier! |
| **GitHubRepository** | `https://github.com/yourname/algo-trader.git` | Your repo URL |
| **AlpacaApiKey** | `PKP...` | From alpaca.markets |
| **AlpacaSecretKey** | `7qf...` | From alpaca.markets |
| **TradingSymbols** | `SPY,QQQ,AAPL` | Your symbols |
| **MaxDailyLoss** | `0.03` | 3% = 0.03 |

Click **Next** → **Next** → **Create stack**

---

## 📊 Status & Access

### **Wait for Deployment** (3-5 minutes)
- Stack status should show: `CREATE_IN_PROGRESS`
- Then: `CREATE_COMPLETE` ✅

### **Access Your Dashboard**
1. Click on the stack name
2. Go to **Outputs** tab
3. Click **DashboardURL** link
4. 🎉 Dashboard opens!

---

## 💻 Connect to Your Server (No SSH Key!)

### **Option 1: AWS Session Manager (Easiest)**
1. Click **Outputs** tab
2. Click **SSMSessionURL** link
3. Browser terminal opens automatically ✅

### **Option 2: AWS Console**
1. Go to [EC2 Dashboard](https://console.aws.amazon.com/ec2/)
2. Find your instance
3. Select it
4. Click **Connect** → **Session Manager**
5. Click **Connect**

### **Useful Commands**
```bash
# View logs
docker-compose logs -f

# Check status
docker-compose ps

# View app logs only
docker-compose logs -f algo-trader

# Restart app
docker-compose restart algo-trader

# SSH from terminal
ssh -i your-key.pem ubuntu@YOUR_IP  # (if you have SSH key)
```

---

## 🔍 Troubleshooting

### **Deployment Stuck?**
Check CloudFormation Events:
1. Click stack name
2. Click **Events** tab
3. Look for red errors

### **Dashboard Not Loading?**
```bash
# Check if containers are running
docker-compose ps

# View error logs
docker-compose logs algo-trader

# Restart everything
docker-compose restart
```

### **Wrong GitHub URL?**
```bash
# Inside Session Manager:
cd /home/ubuntu/algo-trader/algo-trader
git remote -v  # Check URL

# If wrong, delete and re-clone:
cd /home/ubuntu
rm -rf algo-trader
git clone https://github.com/YOUR_USERNAME/algo-trader.git algo-trader
cd algo-trader/algo-trader
docker-compose up -d
```

---

## 💰 Costs

**First 12 months (Free Tier):**
- ✅ t2.micro EC2: FREE
- ✅ 30 GB storage: FREE  
- ✅ Data transfer: FREE (limited)
- ✅ **Total: $0**

**After free tier:**
- t2.micro: ~$9.50/month
- Storage: ~$1/month
- Total: ~$10-15/month

---

## 🛑 Stop or Delete

### **Keep Instance but Stop (saves money)**
```bash
# Via AWS Console:
1. EC2 Dashboard → Instances
2. Select instance
3. Instance State → Stop
4. Cost: $0 when stopped
```

### **Delete Everything (free up resources)**
```bash
# Via CloudFormation Console:
1. Select your stack
2. Click Delete
3. Confirm
4. Everything removed
```

---

## ✅ Deployment Checklist

- [ ] AWS Account created
- [ ] CloudFormation template uploaded
- [ ] Parameters filled in
- [ ] Stack creation started
- [ ] Wait for `CREATE_COMPLETE` status
- [ ] Open DashboardURL from Outputs
- [ ] Dashboard loads ✅
- [ ] Testing trading signals

---

## 📞 Need Help?

**Common Issues:**
- ❌ "Parameter validation failed" → Ensure all fields are filled
- ❌ "Repository not found" → Check GitHub URL is correct
- ❌ "Dashboard not loading" → Give it 2-3 min, check Session Manager logs

**AWS Resources:**
- CloudFormation Docs: https://docs.aws.amazon.com/cloudformation/
- EC2 Docs: https://docs.aws.amazon.com/ec2/
- Session Manager: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html

---

## 🎯 What Happens After Deployment?

1. ✅ Instance launched (t2.micro)
2. ✅ Docker installed
3. ✅ Repository cloned
4. ✅ Environment variables configured
5. ✅ Docker containers started
6. ✅ PostgreSQL running
7. ✅ Flask dashboard accessible
8. ✅ Trading bot monitoring markets

Everything runs 24/7 in the cloud! 🚀

---

## 🔐 Security Notes

- Environment variables auto-generated (`FLASK_SECRET_KEY`)
- API keys stored securely in `.env` (not in code)
- Session Manager uses IAM authentication (no SSH keys)
- Database password configured
- Network isolated in custom VPC

---

**You're all set! Deploy now →** https://console.aws.amazon.com/cloudformation/

Good luck! 🎉

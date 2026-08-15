# 🔍 How to Check Your AWS Deployment

## 1️⃣ Check CloudFormation Stack Status

### **In AWS Console:**
1. Go to: https://console.aws.amazon.com/cloudformation/
2. Find your stack: `algo-trader`
3. Look at **Status** column:
   - ✅ `CREATE_COMPLETE` = Success!
   - ⏳ `CREATE_IN_PROGRESS` = Still deploying (wait 3-5 min)
   - ❌ `ROLLBACK_COMPLETE` = Error occurred

### **If Status is ROLLBACK_COMPLETE:**
1. Click on stack
2. Go to **Events** tab
3. Look for red errors at top
4. Fix the issue and redeploy

---

## 2️⃣ Check Instance Status

### **In EC2 Dashboard:**
1. Go to: https://console.aws.amazon.com/ec2/
2. Click **Instances**
3. Find your instance
4. Look at **Instance State**:
   - ✅ `running` = Good!
   - ⏳ `pending` = Still starting
   - ❌ `stopped` = Instance off

### **Check Instance Details:**
- Click instance name
- Verify:
  - Public IPv4 address (for dashboard URL)
  - Security groups (should allow port 5000)
  - VPC/Subnet (should be your custom VPC)

---

## 3️⃣ Check Dashboard Access

### **Method 1: Use CloudFormation Outputs**
1. Go to CloudFormation console
2. Click your stack name
3. Go to **Outputs** tab
4. Copy **DashboardURL** value
5. Paste in browser: `http://YOUR_IP:5000`

### **Expected Result:**
- Flask dashboard loads ✅
- Shows trading interface
- Real-time data

### **If Dashboard Doesn't Load:**
```bash
# Check if port 5000 is open
# Security Group should allow inbound on 5000

# Inside Session Manager:
curl http://localhost:5000
# Should return HTML (not "connection refused")
```

---

## 4️⃣ Check Containers Status

### **Connect via Session Manager:**
1. Go to EC2 console
2. Select your instance
3. Click **Connect** → **Session Manager** → **Connect**

### **Check Containers:**
```bash
# List all containers
docker-compose ps

# Expected output:
# NAME                COMMAND              STATUS
# postgres            "docker-entrypoint"  Up 2 minutes
# algo-trader         "python main.py"     Up 2 minutes

# ✅ Both should show "Up"
```

### **If Containers Show "Exit":**
```bash
# View error logs
docker-compose logs

# Restart containers
docker-compose restart

# Check specific service
docker-compose logs algo-trader
```

---

## 5️⃣ Check Application Logs

### **View Live Logs:**
```bash
cd /home/ubuntu/algo-trader/algo-trader

# Real-time logs
docker-compose logs -f

# Just trading bot logs
docker-compose logs -f algo-trader

# Just database logs
docker-compose logs -f postgres

# Exit with Ctrl+C
```

### **Expected Log Output:**
```
2026-08-15 10:30:45 | INFO | Market opened
2026-08-15 10:30:50 | INFO | SPY price: $450.25
2026-08-15 10:31:00 | INFO | Signal generated: MOMENTUM_UP
2026-08-15 10:31:05 | INFO | Order placed: BUY 10 shares SPY
```

### **Check for Errors:**
Look for:
- ❌ `ERROR: ` lines
- ❌ `Connection refused`
- ❌ `API key invalid`
- ❌ `Database error`

---

## 6️⃣ Check Environment Variables

### **Verify Configuration Loaded:**
```bash
# Check .env file exists
ls -la .env

# View env variables (safe - no secrets shown)
docker-compose exec algo-trader env | grep -E "TRADING|FLASK|ENV"

# Expected output shows:
# TRADING_SYMBOLS=SPY,QQQ,AAPL
# FLASK_SECRET_KEY=(random)
# ENV=paper
```

---

## 7️⃣ Check Database Connection

### **Test Database:**
```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U postgres -d algotrader

# Inside psql (you'll see: algotrader=# prompt):
SELECT version();
\dt  # List tables
\q  # Exit

# Expected: Tables for trades, signals, positions
```

### **If Connection Fails:**
```bash
# Restart database
docker-compose restart postgres

# Check database logs
docker-compose logs postgres
```

---

## 8️⃣ Check Network Connectivity

### **Verify Instance Can Access Internet:**
```bash
# Test external API access
curl -I https://api.alpaca.markets

# Should return HTTP status (not timeout)
```

### **Verify Port 5000 is Open:**
```bash
# Check from inside container
docker-compose exec algo-trader curl localhost:5000

# Should return HTML (not "Connection refused")
```

---

## 9️⃣ Check CloudWatch Logs

### **In AWS Console:**
1. Go to: https://console.aws.amazon.com/logs/
2. Look for log group: `/algo-trader/deployment`
3. Click to expand
4. View setup script output

### **Check Setup Status:**
```
[1/8] Updating system packages... ✅
[2/8] Installing Docker... ✅
[3/8] Installing Docker Compose... ✅
[4/8] Configuring Docker permissions... ✅
[5/8] Cloning repository... ✅
[6/8] Setting up environment variables... ✅
[7/8] Starting Docker containers... ✅
[8/8] Waiting for services to start... ✅
```

---

## 🔟 Quick Validation Checklist

Run this sequence to verify everything:

```bash
# 1. Check containers running
docker-compose ps

# 2. Check logs for errors
docker-compose logs | grep -i error

# 3. Test database
docker-compose exec -T postgres psql -U postgres -d algotrader -c "SELECT COUNT(*) FROM information_schema.tables;"

# 4. Test API connection
docker-compose exec algo-trader curl -I https://api.alpaca.markets

# 5. Test dashboard
docker-compose exec algo-trader curl -I localhost:5000

# 6. Check environment
docker-compose exec algo-trader env | grep ALPACA_API_KEY | wc -c
# Should be > 10 (has value, not empty)
```

---

## 📊 Health Check Summary

| Check | Command | Expected |
|-------|---------|----------|
| **CloudFormation Status** | AWS Console | `CREATE_COMPLETE` |
| **Instance State** | EC2 Console | `running` |
| **Containers** | `docker-compose ps` | All `Up` |
| **Dashboard** | Browser: port 5000 | Loads page |
| **Logs** | `docker-compose logs` | No `ERROR` lines |
| **Database** | `psql ...` | Connects |
| **API Access** | `curl alpaca` | HTTP response |
| **Env Vars** | `env \| grep` | Has values |

---

## 🆘 Troubleshooting by Status

### **✅ Everything Shows "SUCCESS"**
- Dashboard is live ✅
- Bot is monitoring markets ✅
- Check `/trading` page for signals

### **⏳ Containers Still Starting**
```bash
# Wait 2-3 more minutes
# Check progress
watch -n 5 'docker-compose ps'  # Updates every 5 sec
```

### **❌ Containers Show "Exit"**
```bash
# View exit error
docker-compose logs algo-trader | tail -50

# Common issues:
# - API keys invalid
# - Database not ready
# - Port already in use

# Fix and restart
docker-compose restart
```

### **❌ Dashboard Not Loading**
```bash
# Check if port is listening
sudo lsof -i :5000

# If nothing: container crashed
docker-compose logs algo-trader

# If "LISTEN": check URL is correct
# http://PUBLIC_IP:5000
```

---

## 📞 Getting Help

**Copy & send me:**
1. Output of: `docker-compose ps`
2. Output of: `docker-compose logs algo-trader` (last 20 lines)
3. The error message from CloudFormation Events tab

---

## ✅ You're Fully Deployed When

- ✅ CloudFormation status: `CREATE_COMPLETE`
- ✅ All containers show: `Up`
- ✅ Dashboard loads in browser
- ✅ Logs show: `Trading active`
- ✅ No `ERROR` lines in logs

---

**All set? Your bot is running 24/7 in the cloud!** 🚀

import telebot
from telebot import types
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import threading
import json
import os

# Bot configuration
BOT_TOKEN = '8213168243:AAHO7NWNF6qqm6rjBYX5zjXyRW9qkPe4JpU'
bot = telebot.TeleBot(BOT_TOKEN)

# Payment configuration
PAYMENT_NUMBER = "09012345678"  # Replace with your payment number
PAYMENT_NAME = "Prince AB"  # Replace with your name

# Subscription plans
PLANS = {
    'free': {
        'name': 'Free Trial',
        'price': 0,
        'daily_limit': 3,
        'weekly_limit': 9,
        'duration_days': 7,
        'description': '3 signals/day, 9 signals/week for 7 days'
    },
    'weekly': {
        'name': 'Weekly Plan',
        'price': 3000,
        'daily_limit': 7,
        'weekly_limit': 35,
        'duration_days': 7,
        'description': '7 signals/day, 35 signals/week'
    },
    'monthly': {
        'name': 'Monthly Plan',
        'price': 10000,
        'daily_limit': 15,
        'weekly_limit': 75,
        'duration_days': 30,
        'description': '15 signals/day, 75 signals/week'
    }
}

# Optimized pair selection
MAJOR_PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD']
VOLATILE_PAIRS = ['GBPJPY', 'EURJPY', 'ONTUSDT', 'BTCUSD']
ALL_PAIRS = MAJOR_PAIRS + VOLATILE_PAIRS

# Trading configuration
RISK_REWARD_RATIO = 2.5
ATR_MULTIPLIER_SL = 2.0
ATR_MULTIPLIER_TP = 5.0

# Timeframes
TIMEFRAMES = {
    '5m': '5min',
    '15m': '15min',
    '30m': '30min',
    '1h': '1h',
    '4h': '4h',
    '1d': '1day'
}
DEFAULT_TIMEFRAME = '1h'

# User database file
USER_DB_FILE = 'users_db.json'

class UserManager:
    """Manage user subscriptions and usage limits"""
    
    def __init__(self):
        self.users = self.load_users()
    
    def load_users(self):
        """Load users from file"""
        if os.path.exists(USER_DB_FILE):
            try:
                with open(USER_DB_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_users(self):
        """Save users to file"""
        with open(USER_DB_FILE, 'w') as f:
            json.dump(self.users, f, indent=2)
    
    def get_user(self, user_id):
        """Get user data"""
        user_id = str(user_id)
        if user_id not in self.users:
            # New user - create with no plan
            self.users[user_id] = {
                'plan': None,
                'plan_started': None,
                'plan_expires': None,
                'daily_usage': 0,
                'weekly_usage': 0,
                'last_reset_day': None,
                'last_reset_week': None,
                'has_used_free_trial': False,
                'payment_pending': False
            }
            self.save_users()
        return self.users[user_id]
    
    def activate_plan(self, user_id, plan_type):
        """Activate a subscription plan"""
        user_id = str(user_id)
        user = self.get_user(user_id)
        
        now = datetime.now()
        plan = PLANS[plan_type]
        
        user['plan'] = plan_type
        user['plan_started'] = now.isoformat()
        user['plan_expires'] = (now + timedelta(days=plan['duration_days'])).isoformat()
        user['daily_usage'] = 0
        user['weekly_usage'] = 0
        user['last_reset_day'] = now.date().isoformat()
        user['last_reset_week'] = now.date().isoformat()
        user['payment_pending'] = False
        
        if plan_type == 'free':
            user['has_used_free_trial'] = True
        
        self.save_users()
        return True
    
    def check_and_reset_limits(self, user_id):
        """Check if limits need to be reset"""
        user = self.get_user(user_id)
        now = datetime.now().date()
        
        # Reset daily limit
        if user['last_reset_day'] != now.isoformat():
            user['daily_usage'] = 0
            user['last_reset_day'] = now.isoformat()
        
        # Reset weekly limit (every Monday)
        last_reset = datetime.fromisoformat(user['last_reset_week']).date() if user['last_reset_week'] else now
        if now.weekday() == 0 and (now - last_reset).days >= 7:
            user['weekly_usage'] = 0
            user['last_reset_week'] = now.isoformat()
        
        self.save_users()
    
    def can_generate_signal(self, user_id):
        """Check if user can generate a signal"""
        user = self.get_user(user_id)
        
        # Check if user has active plan
        if not user['plan']:
            return False, "❌ No active plan. Use /subscribe to get started!"
        
        # Check if plan expired
        if datetime.now() > datetime.fromisoformat(user['plan_expires']):
            user['plan'] = None
            self.save_users()
            return False, "⏰ Your plan has expired. Use /subscribe to renew!"
        
        # Reset limits if needed
        self.check_and_reset_limits(user_id)
        
        # Check limits
        plan = PLANS[user['plan']]
        
        if user['daily_usage'] >= plan['daily_limit']:
            return False, f"📊 Daily limit reached ({plan['daily_limit']} signals). Try again tomorrow!"
        
        if user['weekly_usage'] >= plan['weekly_limit']:
            return False, f"📊 Weekly limit reached ({plan['weekly_limit']} signals). Resets on Monday!"
        
        return True, "OK"
    
    def increment_usage(self, user_id):
        """Increment usage counters"""
        user = self.get_user(user_id)
        user['daily_usage'] += 1
        user['weekly_usage'] += 1
        self.save_users()
    
    def get_usage_stats(self, user_id):
        """Get user usage statistics"""
        user = self.get_user(user_id)
        
        if not user['plan']:
            return None
        
        plan = PLANS[user['plan']]
        expires = datetime.fromisoformat(user['plan_expires'])
        days_left = (expires - datetime.now()).days
        
        return {
            'plan_name': plan['name'],
            'daily_used': user['daily_usage'],
            'daily_limit': plan['daily_limit'],
            'weekly_used': user['weekly_usage'],
            'weekly_limit': plan['weekly_limit'],
            'days_left': days_left,
            'expires': expires.strftime('%Y-%m-%d %H:%M')
        }

# Initialize managers
user_manager = UserManager()

class ForexAnalyzer:
    """Enhanced analyzer with trend filtering"""
    
    def __init__(self):
        self.twelve_api_key = '935b760b081245d28b791fbcbaf81732'
        self.alpha_api_key = 'JYXBWYP1S4MSY5NQ'
    
    def get_price_data(self, pair, interval='1h', periods=200):
        """Fetch historical price data from Twelve Data API"""
        try:
            formatted_pair = f"{pair[:3]}/{pair[3:]}"
            url = f"https://api.twelvedata.com/time_series"
            params = {
                'symbol': formatted_pair,
                'interval': interval,
                'outputsize': periods,
                'apikey': self.twelve_api_key,
                'format': 'JSON'
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if 'values' not in data:
                return self.get_price_data_alpha(pair, interval, periods)
            
            df = pd.DataFrame(data['values'])
            df['timestamp'] = pd.to_datetime(df['datetime'])
            df['open'] = pd.to_numeric(df['open'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['close'] = pd.to_numeric(df['close'])
            df['volume'] = pd.to_numeric(df.get('volume', 0))
            
            df = df.sort_values('timestamp').reset_index(drop=True)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            return df
            
        except Exception as e:
            print(f"Error fetching data: {e}")
            return None
    
    def get_price_data_alpha(self, pair, interval='60min', periods=200):
        """Fallback data source"""
        try:
            url = f"https://www.alphavantage.co/query"
            params = {
                'function': 'FX_INTRADAY',
                'from_symbol': pair[:3],
                'to_symbol': pair[3:],
                'interval': interval,
                'apikey': self.alpha_api_key,
                'outputsize': 'full',
                'datatype': 'json'
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            time_series_key = f'Time Series FX ({interval})'
            if time_series_key not in data:
                return None
            
            time_series = data[time_series_key]
            records = []
            
            for timestamp, values in list(time_series.items())[:periods]:
                records.append({
                    'timestamp': pd.to_datetime(timestamp),
                    'open': float(values['1. open']),
                    'high': float(values['2. high']),
                    'low': float(values['3. low']),
                    'close': float(values['4. close']),
                    'volume': 0
                })
            
            df = pd.DataFrame(records)
            df = df.sort_values('timestamp').reset_index(drop=True)
            return df
            
        except Exception as e:
            print(f"Error with fallback: {e}")
            return None
    
    def calculate_indicators(self, df):
        """Calculate technical indicators"""
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        # ADX
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr = df['atr'] * 14
        plus_di = 100 * (plus_dm.rolling(14).mean() / tr)
        minus_di = 100 * (minus_dm.rolling(14).mean() / tr)
        
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        df['adx'] = dx.rolling(14).mean()
        
        return df
    
    def generate_signal(self, pair, timeframe='1h', strict_mode=True):
        """Generate trading signal"""
        df = self.get_price_data(pair, interval=timeframe, periods=200)
        
        if df is None or len(df) < 200:
            return None
            
        df = self.calculate_indicators(df)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = latest['close']
        atr = latest['atr']
        
        if strict_mode and latest['adx'] < 25:
            return None
        
        bullish_score = 0
        bearish_score = 0
        
        # Trend analysis
        if latest['ema_9'] > latest['ema_20'] > latest['ema_50'] > latest['ema_200']:
            bullish_score += 4
        elif latest['ema_9'] < latest['ema_20'] < latest['ema_50'] < latest['ema_200']:
            bearish_score += 4
        elif latest['ema_20'] > latest['ema_50']:
            bullish_score += 2
        elif latest['ema_20'] < latest['ema_50']:
            bearish_score += 2
        
        # Moving average cross
        if latest['ema_9'] > latest['ema_20'] and prev['ema_9'] <= prev['ema_20']:
            bullish_score += 3
        elif latest['ema_9'] < latest['ema_20'] and prev['ema_9'] >= prev['ema_20']:
            bearish_score += 3
        
        # RSI confirmation
        if 40 < latest['rsi'] < 60 and latest['rsi'] > prev['rsi']:
            bullish_score += 2
        elif 40 < latest['rsi'] < 60 and latest['rsi'] < prev['rsi']:
            bearish_score += 2
        
        # Price position
        if current_price > latest['ema_50']:
            bullish_score += 1
        elif current_price < latest['ema_50']:
            bearish_score += 1
        
        # ADX bonus
        if latest['adx'] > 30:
            if bullish_score > bearish_score:
                bullish_score += 2
            elif bearish_score > bullish_score:
                bearish_score += 2
        
        signal = None
        confidence = 0
        min_score = 6 if strict_mode else 4
        
        if bullish_score >= min_score and bullish_score > (bearish_score + 2):
            signal = 'BUY'
            confidence = min(95, 55 + (bullish_score * 5))
            entry = current_price
            stop_loss = entry - (atr * ATR_MULTIPLIER_SL)
            take_profit = entry + (atr * ATR_MULTIPLIER_TP)
            
            tp_levels = [
                entry + (atr * ATR_MULTIPLIER_TP * 0.5),
                entry + (atr * ATR_MULTIPLIER_TP * 0.8),
                entry + (atr * ATR_MULTIPLIER_TP)
            ]
                
        elif bearish_score >= min_score and bearish_score > (bullish_score + 2):
            signal = 'SELL'
            confidence = min(95, 55 + (bearish_score * 5))
            entry = current_price
            stop_loss = entry + (atr * ATR_MULTIPLIER_SL)
            take_profit = entry - (atr * ATR_MULTIPLIER_TP)
            
            tp_levels = [
                entry - (atr * ATR_MULTIPLIER_TP * 0.5),
                entry - (atr * ATR_MULTIPLIER_TP * 0.8),
                entry - (atr * ATR_MULTIPLIER_TP)
            ]
        
        if signal:
            return {
                'pair': pair,
                'signal': signal,
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'tp_levels': [round(tp, 5) for tp in tp_levels],
                'confidence': round(confidence, 1),
                'rsi': round(latest['rsi'], 2),
                'adx': round(latest['adx'], 2),
                'timeframe': timeframe,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
            }
        
        return None

# Initialize analyzer
analyzer = ForexAnalyzer()

@bot.message_handler(commands=['start'])
def start_command(message):
    user = user_manager.get_user(message.from_user.id)
    
    welcome_text = f"""
🤖 *Welcome to Premium Forex Signal Bot*

👋 Hello {message.from_user.first_name}!

📊 *Your Status:*
"""
    
    if user['plan']:
        stats = user_manager.get_usage_stats(message.from_user.id)
        welcome_text += f"""✅ Plan: {stats['plan_name']}
📈 Today: {stats['daily_used']}/{stats['daily_limit']} signals
📅 This Week: {stats['weekly_used']}/{stats['weekly_limit']} signals
⏰ Expires: {stats['expires']} ({stats['days_left']} days left)
"""
    else:
        welcome_text += "❌ No active plan\n"
    
    welcome_text += """
🎯 *Available Commands:*
/subscribe - View subscription plans
/status - Check your plan and usage
/signals [timeframe] - Generate signals
/analyze [PAIR] [timeframe] - Analyze specific pair
/pairs - View available pairs
/help - Show help

💡 *Quick Start:*
1️⃣ Choose a plan: /subscribe
2️⃣ Get signals: /signals
3️⃣ Manage risk: Use proper position sizing

⚠️ *Risk Warning:* Trading involves risk. Only trade with money you can afford to lose.
"""
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['subscribe'])
def subscribe_command(message):
    user = user_manager.get_user(message.from_user.id)
    
    subscribe_text = """
💎 *SUBSCRIPTION PLANS*

"""
    
    # Free trial info
    if not user['has_used_free_trial']:
        subscribe_text += """
🎁 *FREE TRIAL* (7 Days)
✅ 3 signals per day
✅ 9 signals per week
✅ Access to all pairs
💰 Price: FREE (One-time only)

"""
    else:
        subscribe_text += "✓ You've already used your free trial\n\n"
    
    subscribe_text += """
📅 *WEEKLY PLAN*
✅ 7 signals per day
✅ 35 signals per week
✅ Access to all pairs
✅ Priority support
💰 Price: ₦3,000 / week

🌟 *MONTHLY PLAN* (Best Value!)
✅ 15 signals per day
✅ 75 signals per week
✅ Access to all pairs
✅ Priority support
✅ Market analysis tips
💰 Price: ₦10,000 / month

📱 *How to Subscribe:*
"""
    
    if not user['has_used_free_trial']:
        subscribe_text += "1️⃣ Free Trial: Click button below\n"
    
    subscribe_text += f"""2️⃣ Paid Plans: Send payment to {PAYMENT_NUMBER} ({PAYMENT_NAME})
3️⃣ Send screenshot of payment proof
4️⃣ Get instant activation

💡 Choose your plan below:
"""
    
    # Create inline keyboard
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if not user['has_used_free_trial']:
        markup.add(types.InlineKeyboardButton("🎁 Start Free Trial", callback_data="plan_free"))
    
    markup.add(
        types.InlineKeyboardButton("📅 Weekly Plan - ₦3,000", callback_data="plan_weekly"),
        types.InlineKeyboardButton("🌟 Monthly Plan - ₦10,000", callback_data="plan_monthly")
    )
    
    bot.send_message(message.chat.id, subscribe_text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
def handle_plan_selection(call):
    plan_type = call.data.split('_')[1]
    user_id = call.from_user.id
    user = user_manager.get_user(user_id)
    
    if plan_type == 'free':
        if user['has_used_free_trial']:
            bot.answer_callback_query(call.id, "❌ You've already used your free trial!")
            return
        
        # Activate free trial immediately
        user_manager.activate_plan(user_id, 'free')
        
        bot.answer_callback_query(call.id, "✅ Free trial activated!")
        bot.send_message(call.message.chat.id,
            "🎉 *Free Trial Activated!*\n\n"
            "✅ You now have 7 days of free access\n"
            "📊 Limits: 3 signals/day, 9 signals/week\n\n"
            "Use /signals to start generating signals!\n\n"
            "💡 Upgrade anytime with /subscribe",
            parse_mode='Markdown')
    
    else:
        plan = PLANS[plan_type]
        
        payment_text = f"""
💳 *PAYMENT INSTRUCTIONS*

Plan: {plan['name']}
Price: ₦{plan['price']:,}

📱 *Send payment to:*
Number: {PAYMENT_NUMBER}
Name: {PAYMENT_NAME}

📸 *After payment:*
1️⃣ Take screenshot of payment confirmation
2️⃣ Send the screenshot to this chat
3️⃣ Include transaction reference (if any)

⚡ Activation is usually instant after verification!

❓ Need help? Contact support.
"""
        
        user['payment_pending'] = True
        user['pending_plan'] = plan_type
        user_manager.save_users()
        
        bot.send_message(call.message.chat.id, payment_text, parse_mode='Markdown')
        bot.answer_callback_query(call.id, f"Please send ₦{plan['price']:,} to {PAYMENT_NUMBER}")

@bot.message_handler(content_types=['photo'])
def handle_payment_proof(message):
    """Handle payment proof screenshots"""
    user = user_manager.get_user(message.from_user.id)
    
    if not user.get('payment_pending'):
        return
    
    # In production, you'd verify the payment here
    # For now, we'll notify admin and provide instructions
    
    bot.reply_to(message,
        "📸 *Payment proof received!*\n\n"
        "⏳ Your payment is being verified...\n"
        "✅ You'll be notified once activated (usually within 5 minutes)\n\n"
        "💡 Keep this chat open for updates.",
        parse_mode='Markdown')
    
    # Forward to admin (replace with your admin user ID)
    admin_id = message.from_user.id  # Replace with actual admin ID
    try:
        bot.send_photo(admin_id, message.photo[-1].file_id,
            caption=f"💳 Payment proof from @{message.from_user.username or message.from_user.first_name}\n"
                    f"User ID: {message.from_user.id}\n"
                    f"Plan: {user.get('pending_plan', 'Unknown')}\n\n"
                    f"To activate: /activate {message.from_user.id} {user.get('pending_plan', 'weekly')}")
    except:
        pass

@bot.message_handler(commands=['activate'])
def activate_user(message):
    """Admin command to activate user subscription"""
    # Simple admin check - replace with your actual admin ID
    if message.from_user.id != message.from_user.id:  # Replace first ID with admin ID
        return
    
    try:
        parts = message.text.split()
        target_user_id = int(parts[1])
        plan_type = parts[2]
        
        if plan_type not in PLANS:
            bot.reply_to(message, "❌ Invalid plan type")
            return
        
        user_manager.activate_plan(target_user_id, plan_type)
        
        plan = PLANS[plan_type]
        bot.send_message(target_user_id,
            f"🎉 *Subscription Activated!*\n\n"
            f"✅ Plan: {plan['name']}\n"
            f"⏰ Duration: {plan['duration_days']} days\n"
            f"📊 Daily limit: {plan['daily_limit']} signals\n"
            f"📅 Weekly limit: {plan['weekly_limit']} signals\n\n"
            f"Use /signals to start trading!\n"
            f"Check /status anytime to see your usage.",
            parse_mode='Markdown')
        
        bot.reply_to(message, f"✅ Activated {plan['name']} for user {target_user_id}")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}\n\nUsage: /activate USER_ID PLAN_TYPE")

@bot.message_handler(commands=['status'])
def status_command(message):
    stats = user_manager.get_usage_stats(message.from_user.id)
    
    if not stats:
        bot.reply_to(message,
            "❌ *No Active Plan*\n\n"
            "Use /subscribe to get started!",
            parse_mode='Markdown')
        return
    
    # Calculate percentage used
    daily_percent = (stats['daily_used'] / stats['daily_limit']) * 100
    weekly_percent = (stats['weekly_used'] / stats['weekly_limit']) * 100
    
    # Create progress bars
    daily_bar = '█' * int(daily_percent / 10) + '░' * (10 - int(daily_percent / 10))
    weekly_bar = '█' * int(weekly_percent / 10) + '░' * (10 - int(weekly_percent / 10))
    
    status_text = f"""
📊 *YOUR SUBSCRIPTION STATUS*

💎 *Plan:* {stats['plan_name']}
⏰ *Expires:* {stats['expires']}
⏳ *Days Left:* {stats['days_left']} days

📈 *Daily Usage:*
{daily_bar} {stats['daily_used']}/{stats['daily_limit']} ({daily_percent:.0f}%)

📅 *Weekly Usage:*
{weekly_bar} {stats['weekly_used']}/{stats['weekly_limit']} ({weekly_percent:.0f}%)

💡 *Tips:*
• Daily limit resets at midnight UTC
• Weekly limit resets every Monday
• Use /signals to generate new signals
• Upgrade with /subscribe for more signals
"""
    
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(commands=['signals'])
def signals_command(message):
    user_id = message.from_user.id
    
    # Check if user can generate signal
    can_generate, msg = user_manager.can_generate_signal(user_id)
    
    if not can_generate:
        bot.reply_to(message, msg)
        return
    
    parts = message.text.split()
    timeframe = '1h' if len(parts) == 1 else parts[1] if parts[1] in TIMEFRAMES else '1h'
    
    bot.reply_to(message, f"🔍 Scanning for {timeframe} signals...\n\n⏳ Please wait...")
    
    signals_found = []
    for pair in ALL_PAIRS:
        signal = analyzer.generate_signal(pair, timeframe, strict_mode=True)
        if signal and signal['confidence'] >= 70:
            signals_found.append(signal)
        time.sleep(0.5)
    
    if signals_found:
        # Increment usage for each signal
        for _ in signals_found:
            user_manager.increment_usage(user_id)
        
        signals_found.sort(key=lambda x: x['confidence'], reverse=True)
        for signal in signals_found[:3]:  # Max 3 signals at once
            send_signal(message.chat.id, signal)
    else:
        bot.send_message(message.chat.id,
            f"📊 No high-quality signals on {timeframe} right now.\n\n"
            "💡 Try:\n"
            "• Different timeframe: /signals 4h\n"
            "• Specific pair: /analyze EURUSD\n"
            "• Check back in 1-2 hours")

@bot.message_handler(commands=['analyze'])
def analyze_command(message):
    user_id = message.from_user.id
    
    # Check if user can generate signal
    can_generate, msg = user_manager.can_generate_signal(user_id)
    
    if not can_generate:
        bot.reply_to(message, msg)
        return
    
    try:
        parts = message.text.split()
        pair = parts[1].upper()
        timeframe = '1h' if len(parts) < 3 else parts[2] if parts[2] in TIMEFRAMES else '1h'
        
        if pair not in ALL_PAIRS:
            bot.reply_to(message, f"❌ Invalid pair. Use /pairs to see available pairs")
            return
        
        bot.reply_to(message, f"🔍 Analyzing {pair} on {timeframe}...")
        signal = analyzer.generate_signal(pair, timeframe, strict_mode=False)
        
        if signal:
            user_manager.increment_usage(user_id)
            send_signal(message.chat.id, signal)
        else:
            bot.send_message(message.chat.id,
                f"📊 No clear setup for {pair} on {timeframe}.\n\n"
                "Try a different timeframe or pair.")
    except IndexError:
        bot.reply_to(message, "❌ Usage: /analyze EURUSD 1h")

@bot.message_handler(commands=['pairs'])
def pairs_command(message):
    pairs_text = """
📊 *AVAILABLE PAIRS:*

🥇 *Major Pairs (Recommended):*
• EURUSD - Most liquid
• GBPUSD - Good volatility
• USDJPY - Strong trends
• XAUUSD - Gold

🥈 *Volatile Pairs:*
• GBPJPY - High volatility
• EURJPY - Good for trends
• BTCUSD - Crypto
• ONTUSDT - Crypto

⏰ *Timeframes:*
• 1h - Recommended
• 4h - Swing trading
• 15m - Scalping
• 1d - Long-term
"""
    bot.reply_to(message, pairs_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
🤖 *HELP & COMMANDS*

📊 *Signal Commands:*
/signals [timeframe] - Get trading signals
/analyze PAIR [timeframe] - Analyze specific pair
/pairs - View available pairs

💎 *Account Commands:*
/subscribe - View and choose plans
/status - Check usage and limits
/start - Main menu

💡 *Examples:*
• /signals 1h
• /analyze EURUSD
• /analyze XAUUSD 4h

⚠️ *Important:*
• Signals count toward your daily/weekly limit
• Limits reset daily (00:00 UTC) and weekly (Monday)
• Always use proper risk management

💬 Need help? Contact support.
"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

def send_signal(chat_id, signal):
    """Send formatted trading signal (WITHOUT strategy details)"""
    if 'XAU' in signal['pair']:
        sl_pips = abs(signal['entry'] - signal['stop_loss']) * 10
        tp_pips = abs(signal['entry'] - signal['take_profit']) * 10
    elif 'JPY' in signal['pair']:
        sl_pips = abs(signal['entry'] - signal['stop_loss']) * 100
        tp_pips = abs(signal['entry'] - signal['take_profit']) * 100
    else:
        sl_pips = abs(signal['entry'] - signal['stop_loss']) * 10000
        tp_pips = abs(signal['entry'] - signal['take_profit']) * 10000
    
    rr_ratio = tp_pips / sl_pips if sl_pips > 0 else 0
    
    emoji = "🟢" if signal['signal'] == 'BUY' else "🔴"
    
    # Quality badge based on confidence
    if signal['confidence'] >= 85:
        quality = "💎 PREMIUM"
    elif signal['confidence'] >= 75:
        quality = "⭐ HIGH"
    else:
        quality = "✅ GOOD"
    
    signal_text = f"""
{emoji} *{signal['signal']} SIGNAL* {quality}

📌 *Pair:* {signal['pair']}
⏰ *Timeframe:* {signal['timeframe']}
📊 *Confidence:* {signal['confidence']}%

🎯 *TRADING LEVELS:*

📍 *Entry:* {signal['entry']}
🛑 *Stop Loss:* {signal['stop_loss']} ({sl_pips:.1f} pips)

💰 *Take Profit Levels:*
   TP1 (50%): {signal['tp_levels'][0]} 
   TP2 (30%): {signal['tp_levels'][1]} 
   TP3 (20%): {signal['tp_levels'][2]} 

⚖️ *Risk/Reward:* 1:{rr_ratio:.2f}
⏰ *Time:* {signal['timestamp']}

💡 *TRADE MANAGEMENT:*
1️⃣ Enter at {signal['entry']}
2️⃣ Set SL at {signal['stop_loss']}
3️⃣ Take 50% profit at TP1
4️⃣ Move SL to breakeven
5️⃣ Let remaining run to TP2/TP3

⚠️ *Risk Warning:*
Risk only 1-2% of your account per trade. This is not financial advice. Trade at your own risk.
"""
    
    bot.send_message(chat_id, signal_text, parse_mode='Markdown')

if __name__ == '__main__':
    print("🤖 Premium Forex Signal Bot is running...")
    print("✨ Features: Subscription system, Usage limits, Payment integration")
    bot.infinity_polling()


KONKURSBOT - RENDER DEPLOYMENT

GitHub repository must contain this exact structure:
  bot.py
  antimulti.py
  requirements.txt
  render.yaml
  webapp/index.html

Render Web Service:
  Build Command: pip install -r requirements.txt
  Start Command: python bot.py
  Health Check Path: /

Environment variables:
  BOT_TOKEN = Telegram bot token from BotFather
  ADMIN_ID = your numeric Telegram user ID
  WEBAPP_URL = https://YOUR-SERVICE-NAME.onrender.com
  DB_PATH = /var/data/bot.db

Important:
- WEBAPP_URL must be the final HTTPS URL of this Render service.
- The persistent disk mount is /var/data. Do not use the free plan if you need
  the bot to remain online continuously and preserve SQLite data.
- After deployment, test / in a browser, then open the Mini App from Telegram,
  verify /verify, and test creating/joining a contest.
- Do not commit BOT_TOKEN to GitHub.

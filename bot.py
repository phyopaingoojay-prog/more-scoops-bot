import os
import datetime
import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import ApplicationBuilder
from openai import OpenAI

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8822304975:AAE_Cd3KPbIlEhFU1R5UwsOeQO3P7AzKHFk")
SPREADSHEET_NAME = "More Scoops (Accounting)"
WORKSHEET_NAME = "Bot"

# Initialize Groq Client using OpenAI compatibility
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY", "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"),
    base_url="https://api.groq.com/openai/v1"
)

# Initialize Google Sheets Connection using your service account JSON file
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gc = gspread.authorize(creds)
sheet = gc.open(SPREADSHEET_NAME).worksheet(WORKSHEET_NAME)

ACCOUNTING_PROMPT = """You are my personal accounting assistant for my ice cream business.

When I write a short transaction, reply ONLY with a clean markdown table showing ALL affected elements (double-entry style).

Format exactly like this:

| Date       | Description                        | Amount   | Element    | Category                  |
|------------|------------------------------------|----------|------------|---------------------------|
| 15-10-2026 | Deposit for Yangon Carnival        | 200000   | Asset      | Prepaid Expenses          |
| 15-10-2026 | Deposit for Yangon Carnival        | -200000  | Asset      | Cash / Bank               |

Rules:
- Always show every affected Element (usually 2 rows).
- Use positive amount for increase and negative amount for decrease.
- If no date is given, use today's date in DD-MM-YYYY format.
- You MUST only use categories from the list below. Never invent new categories.
- Choose the most suitable Category from the list.
- Keep Description clear.
- Do not explain anything. Only reply with the table.

Allowed Categories:
Asset: Cash / Bank, Inventory - Ingredients, Inventory - Cones & Packaging, Inventory - Toppings, Equipment, Furniture & Fixtures, Prepaid Expenses, Accounts Receivable
Liability: Accounts Payable, Loans Payable, Sales Tax Payable, Credit Card Payable, Accrued Expenses
Equity: Owner's Capital, Owner's Drawings, Retained Earnings
Revenue: Ice Cream Sales, Toppings & Extras Sales, Beverage Sales, Catering / Events, Delivery Fees, Merchandise Sales
Expense: Cost of Goods Sold (COGS), Rent, Utilities, Salaries & Wages, Marketing & Advertising, Packaging Supplies, Cleaning & Hygiene, Maintenance & Repairs, Insurance, Transportation / Delivery, Bank Charges, Professional Fees, Depreciation
"""

app = Flask(__name__)
telegram_app = None

def parse_markdown_table(markdown_text):
    rows = []
    lines = markdown_text.strip().split('\n')
    for line in lines:
        if '|' in line and '---' not in line and 'Date' not in line:
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if len(cols) >= 5:
                rows.append(cols[:5])
    return rows

@app.route("/", methods=["GET"])
def health_check():
    return "Bot is running on Cloud Run!", 200

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    """Endpoint that Telegram calls when a new message arrives."""
    json_data = request.get_json(force=True)
    update = Update.de_json(json_data, telegram_app.bot)
    
    if update and update.message and update.message.text:
        user_text = update.message.text
        message_id = str(update.message.message_id)
        timestamp = datetime.datetime.now().isoformat()
        
        try:
            # 1. Ask Groq to process transaction
            response = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": ACCOUNTING_PROMPT},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.1
            )
            
            reply_text = response.choices[0].message.content
            parsed_rows = parse_markdown_table(reply_text)
            
            if not parsed_rows:
                # Use asyncio to run the async Telegram message reply inside Flask
                asyncio.run_coroutine_threadsafe(
                    update.message.reply_text("❌ Could not parse accounting table from Groq's response."),
                    telegram_app.loop
                )
                return jsonify({"status": "error", "message": "parsing failed"})

            # 2. Append each double-entry row into Google Sheet
            for row in parsed_rows:
                date, description, amount, element, category = row
                sheet.append_row([
                    timestamp,
                    date,
                    description,
                    amount,
                    element,
                    category,
                    user_text,
                    message_id,
                    "Success"
                ])
                
            # 3. Confirm back to Telegram
            asyncio.run_coroutine_threadsafe(
                update.message.reply_text(f"✅ Successfully recorded via Groq to Bot sheet:\n\n{reply_text}"),
                telegram_app.loop
            )
            
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                update.message.reply_text(f"❌ Error processing transaction: {str(e)}"),
                telegram_app.loop
            )
            
    return jsonify({"status": "ok"})

async def setup_telegram():
    global telegram_app
    telegram_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    await telegram_app.initialize()

if __name__ == "__main__":
    # Initialize the Telegram bot application instance cleanly
    asyncio.run(setup_telegram())

    # Start the Flask web server on port 8080 for Cloud Run
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
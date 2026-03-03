import os
import requests
import sys

def send_telegram_message(bot_token, chat_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("Telegram message sent successfully!")
    else:
        print(f"Failed to send message: {response.text}")

if __name__ == "__main__":
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.")
        sys.exit(1)
        
    from esalen_scraper import get_all_availability
    
    print("Scraping live availability from Retreat Guru...")
    availability_data = get_all_availability()
    
    message = "*Esalen Volunteer Live Availability Summary*\n\n"
    
    for i, (dept, data) in enumerate(availability_data.items(), 1):
        message += f"**{i}. {dept}**\n"
        if "error" in data:
            message += f"- Error checking data: {data['error']}\n"
        else:
            window = data.get("window", "Unknown period")
            available_dates = data.get("available_dates", [])
            
            if available_dates:
                dates_str = ", ".join(available_dates)
                message += f"- **{window}**: Available! ({dates_str}). [Book Here]({data['url']})\n"
            else:
                message += f"- **{window}**: No availability. [Check Here]({data['url']})\n"
        message += "\n"

    send_telegram_message(bot_token, chat_id, message)

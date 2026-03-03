import json
import logging
import datetime
import os
import requests
from typing import Dict, List
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

URLS = {
    "Kitchen": "https://esalen.secure.retreat.guru/program/esalen-volunteer-day-pass-kitchen/?form=1&lang=en",
    "Cabins": "https://esalen.secure.retreat.guru/program/esalen-volunteer-day-pass-cabins/?form=1&lang=en",
    "Farm & Garden": "https://esalen.secure.retreat.guru/program/esalen-volunteer-day-pass-farm-garden/?form=1&lang=en"
}

def send_telegram_message(bot_token: str, chat_id: str, message: str):
    """Sends a Telegram notification."""
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not found. Skipping notification.")
        return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram notification sent successfully.")
        else:
            logger.error(f"Failed to send Telegram: {response.text}")
    except Exception as e:
        logger.error(f"Error sending Telegram: {e}")

def extract_availability(url: str, playwright) -> Dict:
    """Scrapes the Esalen volunteer booking page for open shifts."""
    try:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        logger.info(f"Navigating to {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)

        # Wait for the specific dates to load or show error if 403
        if "403 Forbidden" in page.content():
            logger.error("403 Forbidden - Scraping blocked")
            return {"error": "Blocked by Cloudflare/Anti-Bot"}

        # Wait for either the booking window text or the cards to appear
        try:
            page.wait_for_selector("text=Stay dates must be between", timeout=10000)
        except Exception as e:
            logger.warning("Could not find booking window text - continuing anyway")

        # Let's try to extract the dates bounds first
        date_window = "Unknown"
        window_elem = page.query_selector("text=Stay dates must be between")
        if window_elem:
            date_window_text = window_elem.inner_text().strip()
            # Extract something like 'March 2, 2026 and March 15, 2026'
            if "between " in date_window_text:
                date_window = date_window_text.split("between ")[1].strip()

        logger.info(f"Booking Window: {date_window}")

        # The dates are actually structured inside cards like:
        # div.col-sm-4.ticket-box > div.panel
        # Inside the panel there's the string 'SOLD OUT' or a 'Select' button
        # But wait, looking at the previous manual check, the calendar is what we want
        # Let's see if we can just scrape the selectable dates from the datepicker.
        
        # We need to click the "Arrival" date field to open the calendar
        try:
            arrival_input = page.query_selector('input[name="arrival_date"]')
            if arrival_input:
                arrival_input.click()
                page.wait_for_timeout(1000) # Give calendar time to render
                
                # Check for active (selectable) cells vs disabled cells
                # Usually datpicker cells have class 'active' or don't have 'disabled'
                selectable_days = page.query_selector_all('td.day:not(.disabled)')
                
                available_dates = []
                for day in selectable_days:
                    available_dates.append(day.inner_text().strip())
                
                logger.info(f"Found {len(available_dates)} selectable days in current month view.")
                
                if available_dates:
                     # If we found available dates from the calendar, that's great
                     # But we also need to know what month it is. The calendar header usually has it.
                     month_header = page.query_selector('th.datepicker-switch')
                     month_year = month_header.inner_text().strip() if month_header else "Current Month"
                     
                     browser.close()
                     return {
                         "status": "Available",
                         "window": date_window,
                         "available_dates": [f"{month_year} {d}" for d in available_dates]
                     }
        except Exception as e:
            logger.error(f"Failed parsing calendar: {e}")

        browser.close()
        
        # If we couldn't find any selectable days, just report no availability
        return {
            "status": "No availability",
            "window": date_window,
            "available_dates": []
        }

    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")
        return {"error": str(e)}

def get_all_availability() -> Dict[str, Dict]:
    results = {}
    with sync_playwright() as p:
        for dept, url in URLS.items():
            logger.info(f"Checking {dept}...")
            results[dept] = extract_availability(url, p)
            results[dept]["url"] = url
    return results

if __name__ == "__main__":
    results = get_all_availability()
    
    # Set timestamp to PST (UTC-8)
    pst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-8)))
    results["last_updated"] = pst_now.strftime("%Y-%m-%d %H:%M:%S") + " PST"
    
    # Save to data.json for the static website
    with open("data.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Check for availability and notify via Telegram
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    any_available = False
    message = "*Esalen Volunteer Availability Alert*\n\n"
    
    for dept, info in results.items():
        if dept == "last_updated": continue
        if info.get("status") == "Available":
            any_available = True
            dates_str = ", ".join(info.get("available_dates", []))
            message += f"✅ *{dept}*: Available! ({dates_str})\n[Book Here]({info['url']})\n\n"
    
    if any_available:
        send_telegram_message(bot_token, chat_id, message)
    
    print(f"Scrape completed at {results['last_updated']}. Data saved to data.json.")
    if any_available:
        print("Availability found and Telegram notification triggered.")

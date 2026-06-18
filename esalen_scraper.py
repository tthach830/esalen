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

        # We need to click the "Arrival" date field to open the calendar
        try:
            date_header = page.query_selector('h2.rs-heading-dates')
            if date_header:
                date_header.click(force=True)
                page.wait_for_timeout(500)
                
            arrival_input = page.query_selector('input[name="start_date"]') or page.query_selector('#rs-stay-start')
            available_dates = []
            if arrival_input:
                page.evaluate('document.querySelector("label[for=\'rs-stay-start\']").click()')
                page.wait_for_timeout(1000) # Give calendar time to render
                
                months_checked = 0
                max_months = 3
                while months_checked < max_months:
                    months_checked += 1
                    
                    month_text = page.evaluate('''() => {
                        const sel = document.querySelector("select.ui-datepicker-month");
                        if (sel) return sel.options[sel.selectedIndex].text;
                        const span = document.querySelector(".ui-datepicker-month");
                        if (span) return span.textContent.trim();
                        return "";
                    }''')
                    year_text = page.evaluate('''() => {
                        const sel = document.querySelector("select.ui-datepicker-year");
                        if (sel) return sel.options[sel.selectedIndex].text;
                        const span = document.querySelector(".ui-datepicker-year");
                        if (span) return span.textContent.trim();
                        return "";
                    }''')
                    
                    if not month_text or not year_text:
                        month_header = page.query_selector('.ui-datepicker-title')
                        month_year = month_header.inner_text().strip() if month_header else "Current Month"
                        month_year = ' '.join(month_year.split())
                    else:
                        month_year = f"{month_text} {year_text}"
                    
                    selectable_nodes = page.query_selector_all('table.ui-datepicker-calendar a.ui-state-default')
                    month_avail_dates = []
                    for node in selectable_nodes:
                        month_avail_dates.append(node.inner_text().strip())
                    
                    logger.info(f"Found {len(month_avail_dates)} selectable days in month {month_year}.")
                    
                    for d in month_avail_dates:
                        try:
                            parsed_date = None
                            for fmt in ("%b %Y %d", "%B %Y %d"):
                                try:
                                    parsed_date = datetime.datetime.strptime(f"{month_year} {d}", fmt)
                                    break
                                except ValueError:
                                    continue
                            
                            if parsed_date:
                                day_name = parsed_date.strftime("%a")
                                available_dates.append(f"{day_name}, {parsed_date.strftime('%B %d, %Y')}")
                            else:
                                available_dates.append(f"{month_year} {d}")
                        except Exception as e:
                            available_dates.append(f"{month_year} {d}")
                    
                    next_button = page.query_selector('.ui-datepicker-next:not(.ui-state-disabled)')
                    if next_button:
                        logger.info("Navigating to next month calendar view...")
                        next_button.click()
                        page.wait_for_timeout(1000)
                    else:
                        break
        except Exception as e:
            logger.error(f"Failed parsing calendar: {e}")

        browser.close()
        
        if available_dates:
            return {
                "status": "Available",
                "window": date_window,
                "available_dates": available_dates
            }
            
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
    
    # Set timestamp to PST/PDT automatically
    # Using the timezone setting for America/Los_Angeles if available, or fallback
    import zoneinfo
    try:
        pst_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        pst_now = datetime.datetime.now(pst_tz)
    except Exception:
        # Fallback to simple -8 offset if tzdata is missing
        pst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-8)))
        
    results["last_updated"] = pst_now.strftime("%Y-%m-%d %I:%M:%S %p") + " PST"
    
    # Save to data.json for the static website
    with open("data.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Check for availability and notify via Telegram
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not found. Notifications will fail silently if availability is found.")
        print("WARNING: Telegram credentials not found. Skipping notification.")
    
    any_available = False
    message = "*Esalen Volunteer Availability Alert*\n\n"
    
    for dept, info in results.items():
        if dept == "last_updated": continue
        if info.get("status") == "Available":
            any_available = True
            dates_str = ", ".join(info.get("available_dates", []))
            message += f"✅ *{dept}*: Available! ({dates_str})\n[Book Here]({info['url']})\n\n"
    
    if any_available:
        try:
            from send_telegram import send_telegram_message
            send_telegram_message(bot_token, chat_id, message)
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
    
    print(f"Scrape completed at {results['last_updated']}. Data saved to data.json.")
    if any_available:
        print("Availability found and Telegram notification triggered.")

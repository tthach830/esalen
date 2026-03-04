import sys
from playwright.sync_api import sync_playwright

url = "https://esalen.secure.retreat.guru/program/esalen-volunteer-day-pass-kitchen/?form=1&lang=en"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url)
    
    page.wait_for_selector('input[name="start_date"], #rs-stay-start', state='attached', timeout=10000)
    print("Page loaded.")
    
    arrival_input = page.query_selector('input[name="start_date"]') or page.query_selector('#rs-stay-start')
    if arrival_input:
        print("Opening calendar...")
        
        # Expand the date accordion if needed
        date_header = page.query_selector('h2.rs-heading-dates')
        if date_header:
            date_header.click(force=True)
            page.wait_for_timeout(500)
            
        # Click the calendar label
        page.evaluate('document.querySelector("label[for=\'rs-stay-start\']").click()')
        page.wait_for_timeout(1000)
        
        # Dump the calendar HTML
        calendar_div = page.query_selector('.ui-datepicker') or page.query_selector('#ui-datepicker-div')
        if calendar_div:
            print("--- CALENDAR HTML ---")
            print(calendar_div.inner_html())
            print("---------------------")
        else:
            print("Could not find calendar div. HTML dump:")
            print(page.content())
            
    browser.close()

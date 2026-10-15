"""
Schnell Energy Technologies - Gateway KPI Mail Dashboard Dispatcher
This script sends the generated executive mail dashboard (mail_dashboard.html) via SMTP.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime
from dotenv import load_dotenv

# Load sensitive environment variables from .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Email Configuration Defaults (loaded securely from .env)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # App password or SMTP password
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USERNAME)
RECIPIENTS = os.getenv("RECIPIENTS", "").split(",")

HTML_FILE_PATH = os.path.join(os.path.dirname(__file__), "mail_dashboard.html")

def send_kpi_mail(dry_run=True, custom_recipients=None):
    if not os.path.exists(HTML_FILE_PATH):
        print(f"Error: {HTML_FILE_PATH} not found. Please run generate_email_html.py first.")
        return False

    with open(HTML_FILE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()

    to_list = custom_recipients or [r.strip() for r in RECIPIENTS if r.strip()]
    subject = f"Schnell IoT Gateway KPI & Fault Analytics Report - {datetime.now().strftime('%d-%b-%Y')}"

    # Build MIME message with inline CID image support for Gmail & Outlook
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(to_list)

    msg_alt = MIMEMultipart("alternative")
    msg.attach(msg_alt)

    # Attach Plain text fallback and HTML body
    msg_alt.attach(MIMEText("Please view this email in an HTML-compatible email client.", "plain"))
    msg_alt.attach(MIMEText(html_content, "html", "utf-8"))

    # Attach schnell_logo.png as inline CID image
    logo_path = os.path.join(os.path.dirname(__file__), "schnell_logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f_img:
            img_part = MIMEImage(f_img.read())
            img_part.add_header("Content-ID", "<schnell_logo>")
            img_part.add_header("Content-Disposition", "inline", filename="schnell_logo.png")
            msg.attach(img_part)

    username = SMTP_USERNAME.strip()
    password = SMTP_PASSWORD.replace(" ", "").strip()

    if dry_run or not password or not username:
        print("=== DRY RUN MODE (No email sent) ===")
        print(f"Subject : {subject}")
        print(f"From    : {SENDER_EMAIL}")
        print(f"To      : {', '.join(to_list)}")
        print(f"HTML Size: {len(html_content):,} bytes")
        if not username:
            print("Warning: SMTP_USERNAME is empty. Check your .env file.")
        if not password:
            print("Warning: SMTP_PASSWORD is empty. Check your .env file.")
        return True

    # Try connecting (with auto-fallback between 587 STARTTLS and 465 SSL)
    success = False
    ports_to_try = [SMTP_PORT, 465] if SMTP_PORT != 465 else [465, 587]

    for port in ports_to_try:
        try:
            print(f"Connecting to SMTP server {SMTP_SERVER}:{port}...")
            if port == 465:
                server = smtplib.SMTP_SSL(SMTP_SERVER, port, timeout=20)
            else:
                server = smtplib.SMTP(SMTP_SERVER, port, timeout=20)
                server.ehlo()
                server.starttls()
                server.ehlo()

            server.login(username, password)
            server.sendmail(SENDER_EMAIL, to_list, msg.as_string())
            server.quit()
            print(f"Successfully sent KPI Mail Dashboard to: {', '.join(to_list)}")
            success = True
            break
        except Exception as e:
            print(f"Attempt on port {port} failed: {e}")

    if not success:
        print("Failed to dispatch email after trying available ports.")
        return False
    return True


if __name__ == "__main__":
    import sys
    is_live = "--send" in sys.argv
    send_kpi_mail(dry_run=not is_live)

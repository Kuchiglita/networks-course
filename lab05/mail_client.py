import smtplib
import argparse
from email.mime.multipart import  MIMEMultipart
from email.mime.text import MIMEText

def send_email():

    parser = argparse.ArgumentParser()
    parser.add_argument("recipient", help="recipient email address")
    parser.add_argument("--sender", required=True, help="sender email address")
    parser.add_argument("--username", required=True, help="auth username")
    parser.add_argument("--password", required=True, help="auth password")
    parser.add_argument("--format", choices=("txt", "html"), default="txt", help="message format")

    parser.add_argument("--subject", required=True, help="email subject")
    parser.add_argument("--body", help="email body")
    args = parser.parse_args()

    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587

    message = MIMEMultipart()
    message["From"] = args.sender
    message["To"] = args.recipient
    message["Subject"] = args.subject
    subtype = "html" if args.format == "html" else "plain"
    message.attach(MIMEText(args.body, subtype, "utf-8"))

    # Attempting to declare a secure connection
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(args.username, args.password)
            server.sendmail(args.sender, [args.recipient], message.as_string())
            print(f"Email sent from {args.sender}, to {args.recipient}"
                  f"By mail.spbu.ru")
    except Exception as e:
        print(f"Error while sending message: {e}")

if __name__ == "__main__":
    send_email()


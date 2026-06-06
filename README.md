# HopeBridge Flask Website

A complete cancer-patient donation website built with Python, Flask, HTML, CSS, JavaScript, and Bootstrap.

## Pages And Features

- Home page
- Campaign listing
- Campaign details
- Campaign creation
- Donation checkout and receipt
- Email registration and login
- Forgot password and reset password
- Google/Facebook bonding fallback
- Profile and settings pages
- User dashboard with database totals

## Run The Project

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Open this URL in your browser:

```text
http://127.0.0.1:5000
```

## Deploy On Render

Use these settings:

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

Required Render environment variables:

```text
DATABASE_URL=your Render internal PostgreSQL URL
SECRET_KEY=your long private secret
```

Optional for real Google/Facebook OAuth:

```text
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
FACEBOOK_CLIENT_ID=...
FACEBOOK_CLIENT_SECRET=...
```

Until real provider credentials are added, the Google/Facebook pages use a testing fallback that bonds one verified email to one account.

## Payment Setup Notes

Replace the sample crypto addresses in `app.py` inside `CRYPTO_ADDRESS_BOOK` with your real BTC, ETH, USDC, and USDT addresses. The app rotates between the three addresses listed for each asset/network.

Bank transfer currently uses a sample account in `BANK_ACCOUNT`. Gift cards currently support Amazon, Apple, and Steam.

## Run Tests

```bash
python3 -m unittest discover -s tests -v
```

## Project Structure

```text
app.py
requirements.txt
build_static.py
netlify.toml
tests/
templates/
static/
```

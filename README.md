# HopeBridge Flask Website

A complete cancer-patient donation website built with Python, Flask, HTML, CSS, JavaScript, and Bootstrap.

## Pages

- Home page
- Campaign listing
- Campaign details and donation form
- Login page
- Registration page
- User dashboard

## Run The Project

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Open this URL in your browser:

```text
http://127.0.0.1:5000
```

## Deploy Static Version To Netlify

Netlify does not run a normal Flask server. To deploy this project on Netlify, build the static version first:

```bash
python3 build_static.py
```

Then upload the generated `netlify-site` folder to Netlify.

## Project Structure

```text
app.py
requirements.txt
build_static.py
netlify.toml
templates/
static/
```

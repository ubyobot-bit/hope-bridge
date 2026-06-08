from app import app, db, ensure_schema, seed_campaigns, seed_site_content


with app.app_context():
    db.drop_all()
    ensure_schema()
    seed_campaigns()
    seed_site_content()
    print("HopeBridge database reset complete. You can register fresh accounts now.")

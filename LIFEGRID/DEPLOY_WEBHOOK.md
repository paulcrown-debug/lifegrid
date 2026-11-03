# LifeGrid 24/7 Webhook Receiver Deployment Guide

Streamlit Community Cloud is designed for interactive data applications and will automatically sleep when no users are active, which can cause external webhooks from Flutterwave or payment providers to miss delivery.

The standalone `LIFEGRID/webhook_service.py` solves this by providing a lightweight 24/7 HTTP server that receives webhook events, verifies signatures, and updates your Turso database in real-time.

---

## Deploy to Render (Recommended Free Tier)

1. Sign up at [render.com](https://render.com) (free).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository: `paulcrown-debug/lifegrid`.
4. Configure the service:
   - **Name:** `lifegrid-webhook`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r LIFEGRID/requirements.txt`
   - **Start Command:** `python LIFEGRID/webhook_service.py`
5. In **Environment Variables**, add the 4 secrets:
   - `TURSO_DATABASE_URL`: Your Turso libSQL database URL (e.g., `libsql://lifegrid-....turso.io`)
   - `TURSO_AUTH_TOKEN`: Your Turso authorization token
   - `FLW_SECRET_KEY`: Your Flutterwave Secret Key (`FLWSECK_TEST-...` or live `FLWSECK-...`)
   - `FLW_WEBHOOK_SECRET_HASH`: Your custom webhook secret hash
6. Click **Deploy Web Service**.

Once deployed, your webhook URL will be:
`https://<your-service-name>.onrender.com/flw-webhook`

---

## Configure in Flutterwave Dashboard

1. Log in to your Flutterwave Dashboard.
2. Go to **Settings** -> **Webhooks**.
3. In the **URL** field, paste:
   `https://<your-service-name>.onrender.com/flw-webhook`
4. In the **Secret Hash** field, enter the exact value you set in `FLW_WEBHOOK_SECRET_HASH`.
5. Save settings. Flutterwave will now deliver payment and payout status webhooks 24/7!

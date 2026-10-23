"""
LifeGrid - Page 19: Creator Feed & Post Tipping Integration
Allows fans to browse creator updates, audio/video clips, and tip directly
via gifts or custom cash amounts, with celebratory animations, instant wallet
earnings updates, and audit ledger persistence.
"""

import os
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import streamlit as st

# =========================================================
# STREAMLIT CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="LifeGrid - Feed & Post Tipping",
    page_icon="🎁",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# FAIL-SAFE PAGE NAVIGATION
# =========================================================
def safe_switch_page(candidates, fallback_label):
    """Resilient page switcher that dynamically detects page filenames and catches StreamlitPageNotFoundError."""
    if not hasattr(st, "switch_page"):
        st.info(f"Please open {fallback_label} from the sidebar menu.")
        return
    pages_dir = "pages"
    existing_files = []
    if os.path.exists(pages_dir):
        try:
            existing_files = [f for f in os.listdir(pages_dir) if f.endswith(".py")]
        except Exception:
            existing_files = []

    # 1. Exact candidates
    for cand in candidates:
        rel_path = f"pages/{cand}" if not cand.startswith("pages/") else cand
        fname = os.path.basename(rel_path)
        if os.path.exists(rel_path) or fname in existing_files:
            try:
                st.switch_page(rel_path)
                return
            except Exception:
                pass

    # 2. Keyword fuzzy match
    for cand in candidates:
        cand_clean = os.path.basename(cand).replace(".py", "").lower()
        keywords = [k for k in cand_clean.split() if len(k) > 3 and not k.isdigit() and k != "-"]
        for f in existing_files:
            f_lower = f.lower()
            if any(kw in f_lower for kw in keywords):
                try:
                    st.switch_page(f"pages/{f}")
                    return
                except Exception:
                    pass

    st.info(f"💡 Please open **{fallback_label}** directly from the sidebar navigation.")


# =========================================================
# DATABASE CONNECTION & SCHEMA ENSURANCE
# =========================================================
def get_db_connection():
    try:
        from database import get_connection
        return get_connection()
    except Exception:
        return sqlite3.connect("lifegrid.db", check_same_thread=False)


def ensure_feed_and_tipping_schemas(connection):
    cursor = connection.cursor()

    # Creator profiles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_profiles (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            creator_status TEXT DEFAULT 'active',
            total_earnings REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'NGN'
        )
    """)

    # Creator earnings ledger
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            fan_name TEXT NOT NULL,
            gift_name TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'NGN',
            created_at TEXT NOT NULL
        )
    """)

    # Posts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            creator_name TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            post_type TEXT NOT NULL DEFAULT 'text',
            media_url TEXT DEFAULT '',
            currency TEXT NOT NULL DEFAULT 'NGN',
            total_tips REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        )
    """)

    # Post tips activity table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            fan_name TEXT NOT NULL,
            gift_title TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'NGN',
            cheer_message TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    connection.commit()


# =========================================================
# SEED DEFAULT POSTS IF EMPTY
# =========================================================
def seed_sample_posts(connection):
    cursor = connection.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM creator_posts").fetchone()[0]
    if count == 0:
        sample_posts = [
            (
                1,
                "Chidinma V.",
                "🎧 Behind The Scenes: New Afrobeats Studio Session!",
                "Just finished recording track 4 with the brass section in Lagos. Thank you to everyone sending love and gifts—dropping the snippet next week!",
                "audio",
                "https://example.com/audio/sample_snippet.mp3",
                "NGN",
                15000.0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
            (
                2,
                "Tunde Tech",
                "🚀 How we scaled our Web3 Micro-payments to 10k TPS",
                "Writing a complete guide on how distributed ledgers handle real-time fan tipping with low fees. If this post helped you, consider fueling my midnight coffee!",
                "text",
                "",
                "USD",
                45.0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
            (
                1,
                "Chidinma V.",
                "🎨 Exclusive Album Artwork Concept Reveal",
                "Here is draft concept A for the upcoming summer EP. Would love your feedback in the comments!",
                "image",
                "",
                "NGN",
                8500.0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
        ]
        cursor.executemany("""
            INSERT INTO creator_posts (creator_id, creator_name, title, content, post_type, media_url, currency, total_tips, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, sample_posts)
        connection.commit()


# =========================================================
# APPLICATION INIT & USER CONTEXT
# =========================================================
db = get_db_connection()
ensure_feed_and_tipping_schemas(db)
seed_sample_posts(db)

user_id = st.session_state.get("user_id", 1)
username = st.session_state.get("username", "lukwun")
fan_display_name = st.session_state.get("display_name", "Lukwun Paul")

# Header & Shortcuts
st.title("🌟 Creator Feed & Live Tipping")
st.caption("Development prototype for creator posts and tipping. Tips are simulated and must not be treated as settled payments.")
st.warning("🧪 Development mode only: this page records simulated tips directly to the local database. Do not expose it to users or credit real creator balances until tips are backed by verified payment callbacks and authenticated fan/creator access.")

top1, top2, top3, top4 = st.columns([2, 1, 1, 1])
with top1:
    st.write(f"Browsing as: **@{username}** ({fan_display_name})")
with top2:
    if st.button("🏦 Receiving Accounts", use_container_width=True):
        safe_switch_page([
            "pages/13 - Creator Receiving Account.py",
            "pages/Creator Receiving Account.py",
            "pages/15 - Creator Receiving Account.py"
        ], "Receiving Accounts")
with top3:
    if st.button("📊 Creator Analytics", use_container_width=True):
        safe_switch_page([
            "pages/18 - Creator Analytics & Ledger Dashboard.py",
            "pages/18 - Creator Analytics.py"
        ], "Creator Analytics")
with top4:
    if st.button("💸 Withdraw Funds", type="primary", use_container_width=True):
        safe_switch_page([
            "pages/14 - Creator Withdrawal.py",
            "pages/Creator Withdrawal.py"
        ], "Withdraw Funds")

st.divider()

# =========================================================
# MAIN VIEW: TABS (Feed vs Create Post)
# =========================================================
tab_feed, tab_create, tab_my_tips = st.tabs(["📰 Creator Feed & Tipping", "✍️ Publish Creator Post", "📜 My Tip History"])

# Predefined gift catalog
GIFT_TIERS = [
    {"name": "☕ Hot Coffee", "amount_ngn": 500.0, "amount_usd": 1.0, "icon": "☕"},
    {"name": "🍕 Pizza Slice", "amount_ngn": 2500.0, "amount_usd": 5.0, "icon": "🍕"},
    {"name": "💎 Star Badge", "amount_ngn": 10000.0, "amount_usd": 20.0, "icon": "💎"},
    {"name": "🚀 Super Rocket", "amount_ngn": 50000.0, "amount_usd": 100.0, "icon": "🚀"},
]

# ---------------------------------------------------------
# TAB 1: FEED & TIPPING
# ---------------------------------------------------------
with tab_feed:
    posts = db.execute("""
        SELECT id, creator_id, creator_name, title, content, post_type, media_url, currency, total_tips, created_at
        FROM creator_posts ORDER BY id DESC
    """).fetchall()

    if not posts:
        st.info("No posts published yet. Be the first to share an update!")
    else:
        for post in posts:
            p_id, p_creator_id, p_creator_name, p_title, p_content, p_type, p_media, p_curr, p_tips, p_created = post

            with st.container():
                st.markdown(f"### {p_title}")
                meta_col1, meta_col2, meta_col3 = st.columns([2, 1, 1])
                with meta_col1:
                    st.caption(f"👤 Creator: **{p_creator_name}** | 📅 {p_created}")
                with meta_col2:
                    st.caption(f"🎁 Total Tips: **{p_curr} {p_tips:,.2f}**")
                with meta_col3:
                    st.caption(f"🏷️ Type: **{p_type.capitalize()}**")

                st.write(p_content)

                # Show tip button and expander
                tip_box_key = f"tip_expander_{p_id}"
                with st.expander(f"✨ Send Tip / Gift to {p_creator_name}"):
                    c1, c2 = st.columns([1, 1])
                    with c1:
                        gift_choice = st.selectbox(
                            "Choose a Gift Tier:",
                            options=[g["name"] for g in GIFT_TIERS] + ["Custom Cash Amount"],
                            key=f"gift_sel_{p_id}"
                        )
                        tip_currency = st.selectbox(
                            "Currency:",
                            ["NGN", "USD", "EUR", "GBP", "KES"],
                            key=f"curr_sel_{p_id}"
                        )

                    with c2:
                        if gift_choice == "Custom Cash Amount":
                            tip_amount = st.number_input(
                                f"Enter Amount ({tip_currency}):",
                                min_value=1.0,
                                value=1000.0 if tip_currency == "NGN" else 5.0,
                                step=100.0 if tip_currency == "NGN" else 1.0,
                                key=f"custom_amt_{p_id}"
                            )
                        else:
                            matched_tier = next(g for g in GIFT_TIERS if g["name"] == gift_choice)
                            tip_amount = matched_tier["amount_ngn"] if tip_currency == "NGN" else matched_tier["amount_usd"]
                            st.write(f"Gift Value: **{tip_currency} {tip_amount:,.2f}**")

                        cheer_msg = st.text_input(
                            "Cheering Note / Fan Message (optional):",
                            value="Keep creating amazing content! ❤️",
                            key=f"cheer_{p_id}"
                        )

                    # Tip execution button
                    if st.button(f"🚀 Send {gift_choice} ({tip_currency} {tip_amount:,.2f})", key=f"btn_send_{p_id}", type="primary"):
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        # 1. Record tip in post_tips
                        db.execute("""
                            INSERT INTO post_tips (post_id, creator_id, fan_name, gift_title, amount, currency, cheer_message, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (p_id, p_creator_id, fan_display_name, gift_choice, float(tip_amount), tip_currency, cheer_msg, now_str))

                        # 2. Update post total tips
                        db.execute("""
                            UPDATE creator_posts SET total_tips = total_tips + ? WHERE id = ?
                        """, (float(tip_amount), p_id))

                        # 3. Insert into creator_earnings ledger
                        db.execute("""
                            INSERT INTO creator_earnings (creator_id, fan_name, gift_name, amount, currency, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (p_creator_id, fan_display_name, f"Tip: {gift_choice}", float(tip_amount), tip_currency, now_str))

                        # 4. Update creator_profiles total_earnings
                        db.execute("""
                            INSERT INTO creator_profiles (user_id, display_name, creator_status, total_earnings, currency)
                            VALUES (?, ?, 'active', ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET total_earnings = total_earnings + ?
                        """, (p_creator_id, p_creator_name, float(tip_amount), tip_currency, float(tip_amount)))

                        db.commit()

                        # Celebration & Feedback
                        st.balloons()
                        st.success(f"🧪 Simulated tip recorded for **{p_creator_name}**: {tip_currency} {tip_amount:,.2f}. No payment was charged or verified.")
                        st.rerun()

                # Recent supporters on this post
                recent_tips = db.execute("""
                    SELECT fan_name, gift_title, amount, currency, cheer_message, created_at
                    FROM post_tips WHERE post_id = ? ORDER BY id DESC LIMIT 3
                """, (p_id,)).fetchall()

                if recent_tips:
                    st.markdown("💬 **Recent Supporters on this post:**")
                    for r_fan, r_gift, r_amt, r_curr, r_msg, r_time in recent_tips:
                        st.caption(f"• **{r_fan}** sent **{r_gift}** ({r_curr} {r_amt:,.2f}) — *\"{r_msg}\"* ({r_time})")

                st.markdown("---")

# ---------------------------------------------------------
# TAB 2: PUBLISH NEW POST
# ---------------------------------------------------------
with tab_create:
    st.subheader("📢 Share a New Update With Your Fans")
    st.info("Prototype only: post ownership and user permissions are not enforced in this standalone page.")
    with st.form("new_post_form", clear_on_submit=True):
        c_title = st.text_input("Post Headline / Title:", placeholder="e.g. Dropping the acoustic version tomorrow!")
        c_content = st.text_area("Body Content / Update:", placeholder="Write your thoughts, studio notes, or update...")
        col_type, col_curr = st.columns([1, 1])
        with col_type:
            c_type = st.selectbox("Format Type:", ["Text Update", "Audio Clip", "Video Snippet", "Artwork / Photo"])
        with col_curr:
            c_curr = st.selectbox("Preferred Currency for Tips:", ["NGN", "USD", "EUR", "GBP"])

        submit_post = st.form_submit_button("🚀 Publish Post to Feed", type="primary")

        if submit_post:
            if not c_title.strip() or not c_content.strip():
                st.error("Please provide both a headline and content for your post.")
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.execute("""
                    INSERT INTO creator_posts (creator_id, creator_name, title, content, post_type, media_url, currency, total_tips, created_at)
                    VALUES (?, ?, ?, ?, ?, '', ?, 0.0, ?)
                """, (user_id, fan_display_name, c_title.strip(), c_content.strip(), c_type.lower().split()[0], c_curr, now_str))
                db.commit()
                st.success("🎉 Post published successfully to the creator feed!")
                st.rerun()

# ---------------------------------------------------------
# TAB 3: MY TIP HISTORY
# ---------------------------------------------------------
with tab_my_tips:
    st.subheader("📜 Tips & Gifts Sent by You")
    user_tips = db.execute("""
        SELECT pt.created_at, cp.title, cp.creator_name, pt.gift_title, pt.amount, pt.currency, pt.cheer_message
        FROM post_tips pt
        JOIN creator_posts cp ON pt.post_id = cp.id
        WHERE pt.fan_name = ?
        ORDER BY pt.id DESC
    """, (fan_display_name,)).fetchall()

    if not user_tips:
        st.info("You haven't sent any tips yet. Find a post on the feed to support a creator!")
    else:
        st.write(f"Total gifts sent: **{len(user_tips)}**")
        for t_time, t_post_title, t_creator, t_gift, t_amt, t_curr, t_msg in user_tips:
            with st.container():
                cols = st.columns([2, 2, 1, 1])
                cols[0].write(f"Post: **{t_post_title}**")
                cols[1].write(f"Creator: **{t_creator}**")
                cols[2].write(f"Gift: **{t_gift}** ({t_curr} {t_amt:,.2f})")
                cols[3].caption(t_time)
                if t_msg:
                    st.caption(f"Cheer: *\"{t_msg}\"*")
                st.divider()

db.close()
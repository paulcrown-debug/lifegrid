"""
LifeGrid - Goals Page
Set personal, educational, business, and financial growth goals.
Track progress, celebrate completions, set optional funding targets,
and seamlessly connect goals with LifeGrid Help and community support.
"""

import sqlite3
import streamlit as st
from datetime import date, datetime

from database import get_connection

st.set_page_config(
    page_title="Goals | LifeGrid",
    page_icon="🎯",
    layout="wide",
)

# ============================================================
# LOGIN CHECK
# ============================================================
if "user" not in st.session_state or not st.session_state.user:
    st.warning("Please log in to access your goals.")
    if st.button("Go to Login"):
        st.switch_page("app.py")
    st.stop()

user = st.session_state.user
user_id = int(user["id"])
user_currency = user.get("currency") or "USD"

# ============================================================
# DATABASE SETUP & MIGRATION
# ============================================================
def ensure_goals_table():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT DEFAULT 'Personal',
            target_date DATE,
            target_amount REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'USD',
            progress INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Check for category and target_amount columns in existing databases
    cursor.execute("PRAGMA table_info(goals)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    additions = {
        "category": "TEXT DEFAULT 'Personal'",
        "target_amount": "REAL DEFAULT 0.0",
        "currency": "TEXT DEFAULT 'USD'",
    }
    for col, defn in additions.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE goals ADD COLUMN {col} {defn}")

    conn.commit()
    conn.close()

ensure_goals_table()

# ============================================================
# PAGE HEADER & SUMMARY METRICS
# ============================================================
st.title("🎯 My Goals & Growth Milestones")
st.write("Set meaningful personal, career, and financial goals, track your progress, and unlock community support.")

conn = get_connection()
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM goals WHERE user_id = ? AND status = 'Active'", (user_id,))
active_goals = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM goals WHERE user_id = ? AND status = 'Completed'", (user_id,))
completed_goals = cursor.fetchone()[0]

cursor.execute("SELECT SUM(target_amount) FROM goals WHERE user_id = ? AND status = 'Active'", (user_id,))
target_funding_sum = cursor.fetchone()[0] or 0.0

conn.close()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("📌 Active Goals", active_goals)
with col2:
    st.metric("🏆 Completed Goals", completed_goals)
with col3:
    st.metric("🎯 Total Active Milestones", f"{active_goals + completed_goals} Total")

st.divider()

# ============================================================
# CREATE A NEW GOAL
# ============================================================
st.subheader("➕ Create a New Goal")

categories = [
    "Career & Professional",
    "Education & Learning",
    "Business & Entrepreneurship",
    "Technology & Coding",
    "Personal Growth",
    "Health & Fitness",
    "Financial & Savings",
    "Community & Impact"
]

with st.form("create_goal_form"):
    form_col1, form_col2 = st.columns(2)

    with form_col1:
        goal_title = st.text_input("Goal Title", placeholder="Example: Complete my Cloud Engineering certification")
        goal_category = st.selectbox("Category", categories)
        goal_date = st.date_input("Target Date", value=date.today(), min_value=date.today())

    with form_col2:
        goal_target_amount = st.number_input(
            f"Optional Financial Target / Budget ({user_currency})",
            min_value=0.0,
            value=0.0,
            step=10.0,
            format="%.2f",
            help="Set a budget or target amount if this goal requires financial support, course fees, or equipment."
        )
        goal_description = st.text_area("Description & Action Plan", placeholder="What will achieving this goal look like? What milestones are needed?")

    create_goal = st.form_submit_button("🎯 Create Goal", type="primary", use_container_width=True)

if create_goal:
    if not goal_title.strip():
        st.error("Please enter a goal title.")
    else:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO goals (user_id, title, description, category, target_date, target_amount, currency, progress, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'Active')
        """, (
            user_id,
            goal_title.strip(),
            goal_description.strip(),
            goal_category,
            goal_date.isoformat(),
            float(goal_target_amount),
            user_currency,
        ))

        conn.commit()
        conn.close()

        st.success(f"🎉 Goal '{goal_title.strip()}' created successfully!")
        st.rerun()

st.divider()

# ============================================================
# ACTIVE GOALS
# ============================================================
st.subheader("📌 Active Goals")

conn = get_connection()
cursor = conn.cursor()

cursor.execute("""
    SELECT id, title, description, category, target_date, target_amount, currency, progress, status
    FROM goals
    WHERE user_id = ? AND status = 'Active'
    ORDER BY target_date ASC
""", (user_id,))
active_records = cursor.fetchall()
conn.close()

if not active_records:
    st.info("You don't have any active goals yet. Create your first goal above to start tracking your growth!")
else:
    for goal in active_records:
        gid, title, desc, cat, t_date, t_amt, curr, progress, status = goal

        with st.container(border=True):
            header_col, cat_col = st.columns([3, 1])
            with header_col:
                st.markdown(f"### 🎯 {title}")
            with cat_col:
                st.markdown(f"🏷️ **{cat or 'Personal'}**")

            if desc:
                st.write(desc)

            info_col1, info_col2 = st.columns(2)
            with info_col1:
                st.caption(f"📅 **Target Date:** {t_date}")
            with info_col2:
                if t_amt and float(t_amt) > 0:
                    st.caption(f"💰 **Budget / Target:** {curr or 'USD'} {float(t_amt):,.2f}")

            st.progress(progress / 100, text=f"Progress: {progress}%")

            new_progress = st.slider(
                "Update Progress",
                min_value=0,
                max_value=100,
                value=progress,
                key=f"progress_slider_{gid}"
            )

            btn_col1, btn_col2, btn_col3 = st.columns(3)

            with btn_col1:
                if st.button("💾 Save Progress", key=f"save_btn_{gid}", use_container_width=True):
                    new_status = "Completed" if new_progress == 100 else "Active"
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE goals
                        SET progress = ?, status = ?
                        WHERE id = ? AND user_id = ?
                    """, (new_progress, new_status, gid, user_id))
                    conn.commit()
                    conn.close()
                    st.success("Progress saved!")
                    st.rerun()

            with btn_col2:
                if st.button("🏆 Mark Completed", key=f"complete_btn_{gid}", use_container_width=True, type="primary"):
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE goals
                        SET progress = 100, status = 'Completed'
                        WHERE id = ? AND user_id = ?
                    """, (gid, user_id))
                    conn.commit()
                    conn.close()
                    st.balloons()
                    st.success(f"Congratulations! You completed '{title}'! 🎉")
                    st.rerun()

            with btn_col3:
                # Direct shortcut to request help for this goal
                if st.button("🤝 Request Help for Goal", key=f"help_btn_{gid}", use_container_width=True):
                    st.session_state["prefill_help_title"] = f"Help with goal: {title}"
                    st.session_state["prefill_help_category"] = cat if cat in ["Business", "Education", "Technology"] else "General"
                    st.info("Tip: Open the **Help** page to publish a community help request for this goal!")

st.divider()

# ============================================================
# COMPLETED GOALS
# ============================================================
st.subheader("🏆 Completed Goals & Achievements")

conn = get_connection()
cursor = conn.cursor()

cursor.execute("""
    SELECT title, description, category, target_date, created_at, target_amount, currency
    FROM goals
    WHERE user_id = ? AND status = 'Completed'
    ORDER BY id DESC
""", (user_id,))
completed_records = cursor.fetchall()
conn.close()

if not completed_records:
    st.info("Your completed achievements will be proudly showcased here once you finish your active goals.")
else:
    for c_goal in completed_records:
        c_title, c_desc, c_cat, c_date, c_created, c_amt, c_curr = c_goal
        with st.container(border=True):
            st.markdown(f"### ✅ {c_title}")
            st.caption(f"🏷️ Category: {c_cat or 'Personal'} • Target Date: {c_date}")
            if c_desc:
                st.write(c_desc)
            if c_amt and float(c_amt) > 0:
                st.caption(f"Budget Achieved: {c_curr or 'USD'} {float(c_amt):,.2f}")
            st.success("Status: Achieved 🎉")

st.markdown("---")
st.caption("LifeGrid Goals • Set Intentions • Take Action • Celebrate Growth")
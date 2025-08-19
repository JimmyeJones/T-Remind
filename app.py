import streamlit as st
import sqlite3
import hashlib
import secrets
from datetime import datetime
import pandas as pd
from streamlit_cookies_manager import EncryptedCookieManager

# -----------------------------
# Database setup
# -----------------------------
DB_FILE = "remind.db"

def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Teachers
    c.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT
    )""")

    # Classes
    c.execute("""
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        teacher_id INTEGER,
        access_code TEXT UNIQUE,
        FOREIGN KEY (teacher_id) REFERENCES teachers(id)
    )""")

    # Students
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        class_id INTEGER,
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )""")

    # Assignments
    c.execute("""
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        title TEXT,
        description TEXT,
        due_date TEXT,
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )""")

    conn.commit()
    conn.close()

init_db()

# -----------------------------
# Helpers
# -----------------------------
def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def generate_code():
    return secrets.token_hex(3)  # 6-char code

def fetchall_df(query, params=()):
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def execute(query, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id

# -----------------------------
# Cookie Manager
# -----------------------------
cookies = EncryptedCookieManager(
    prefix="remind_", password="supersecretpassword"
)
if not cookies.ready():
    st.stop()

def set_student_cookie(student_id:int, class_id:int, name:str):
    cookies["role"] = "student"
    cookies["student_id"] = str(student_id)
    cookies["class_id"] = str(class_id)
    cookies["student_name"] = name
    cookies.set("login_ts", datetime.utcnow().isoformat(), expires_days=365)
    cookies.save()

def set_teacher_cookie(teacher_id:int, username:str):
    cookies["role"] = "teacher"
    cookies["teacher_id"] = str(teacher_id)
    cookies["teacher_username"] = username
    cookies.set("login_ts", datetime.utcnow().isoformat(), expires_days=365)
    cookies.save()

def logout():
    for k in list(cookies.keys()):
        del cookies[k]
    cookies.save()
    st.success("You have been logged out.")
    st.rerun()

# -----------------------------
# Student View
# -----------------------------
def student_join_view():
    st.header("Join a Class")
    name = st.text_input("Your Name")
    code = st.text_input("Class Access Code")
    if st.button("Join"):
        if not name or not code:
            st.error("Please enter both fields.")
            return

        cl = fetchall_df("SELECT * FROM classes WHERE access_code=?", (code,))
        if cl.empty:
            st.error("Invalid class code.")
            return

        class_id = int(cl.iloc[0]["id"])
        strow = fetchall_df("SELECT id FROM students WHERE name=? AND class_id=?", (name, class_id))
        if strow.empty:
            student_id = execute("INSERT INTO students (name,class_id) VALUES (?,?)", (name, class_id))
        else:
            student_id = int(strow.iloc[0]["id"])

        set_student_cookie(student_id, class_id, name)
        st.success(f"Welcome to **{cl.iloc[0]['name']}**! You’re now signed in.")
        st.toast("Login saved. You’ll stay signed in on this device.")
        st.rerun()

def student_dashboard():
    student_name = cookies.get("student_name")
    class_id = int(cookies.get("class_id", "0"))
    cl = fetchall_df("SELECT * FROM classes WHERE id=?", (class_id,))
    if cl.empty:
        st.error("Class not found.")
        return
    st.header(f"Class: {cl.iloc[0]['name']}")
    st.subheader(f"Student: {student_name}")

    df = fetchall_df("SELECT * FROM assignments WHERE class_id=? ORDER BY due_date", (class_id,))
    if df.empty:
        st.info("No assignments yet.")
    else:
        st.dataframe(df[["title", "description", "due_date"]])

# -----------------------------
# Teacher View
# -----------------------------
def teacher_register():
    st.subheader("Register Teacher Account")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Register"):
        try:
            execute("INSERT INTO teachers (username,password_hash) VALUES (?,?)",
                    (u, hash_pw(p)))
            st.success("Teacher registered.")
        except Exception as e:
            st.error(f"Error: {e}")

def teacher_login():
    st.subheader("Teacher Login")
    u = st.text_input("Username", key="login_user")
    p = st.text_input("Password", type="password", key="login_pw")
    if st.button("Login"):
        row = fetchall_df("SELECT * FROM teachers WHERE username=? AND password_hash=?",
                          (u, hash_pw(p)))
        if row.empty:
            st.error("Invalid credentials")
        else:
            teacher_id = int(row.iloc[0]["id"])
            set_teacher_cookie(teacher_id, u)
            st.rerun()

def teacher_dashboard():
    teacher_id = int(cookies.get("teacher_id", "0"))
    st.header(f"Teacher Dashboard - {cookies.get('teacher_username')}")

    # Create new class
    st.subheader("Create Class")
    cname = st.text_input("Class Name")
    if st.button("Create Class"):
        code = generate_code()
        execute("INSERT INTO classes (name, teacher_id, access_code) VALUES (?,?,?)",
                (cname, teacher_id, code))
        st.success(f"Class created with code: {code}")
        st.rerun()

    # List classes
    st.subheader("Your Classes")
    dfc = fetchall_df("SELECT * FROM classes WHERE teacher_id=?", (teacher_id,))
    if dfc.empty:
        st.info("No classes yet.")
    else:
        for _, row in dfc.iterrows():
            st.markdown(f"### {row['name']} (Code: `{row['access_code']}`)")
            cid = int(row["id"])

            # Students
            studs = fetchall_df("SELECT * FROM students WHERE class_id=?", (cid,))
            st.write("Students:", ", ".join(studs["name"].tolist()) or "None")

            # Assignments
            assigns = fetchall_df("SELECT * FROM assignments WHERE class_id=? ORDER BY due_date", (cid,))
            if not assigns.empty:
                st.dataframe(assigns[["title", "description", "due_date"]])
            else:
                st.info("No assignments yet.")

            # Add assignment
            with st.expander(f"Add assignment to {row['name']}"):
                t = st.text_input(f"Title for {cid}")
                d = st.text_area(f"Description for {cid}")
                due = st.date_input(f"Due date for {cid}")
                if st.button(f"Add Assignment {cid}"):
                    execute("INSERT INTO assignments (class_id,title,description,due_date) VALUES (?,?,?,?)",
                            (cid, t, d, due.isoformat()))
                    st.success("Assignment added.")
                    st.rerun()

# -----------------------------
# Mobile Instructions
# -----------------------------
def mobile_install_tip():
    st.markdown("""
    ---
    ### 📱 Add to Home Screen (iOS/Android)
    - **iOS (Safari):** Tap *Share* → *Add to Home Screen*
    - **Android (Chrome):** Tap ⋮ → *Add to Home Screen*
    This makes the app feel like a native app!
    """)

# -----------------------------
# Main App
# -----------------------------
def main():
    st.title("📘 T-Remind: Homework & Assignments")

    if st.button("Logout"):
        logout()

    role = cookies.get("role", None)

    if not role:
        st.sidebar.title("Choose role")
        role = st.sidebar.radio("Login as", ["Student", "Teacher"])
        if role == "Student":
            student_join_view()
            mobile_install_tip()
        elif role == "Teacher":
            mode = st.sidebar.radio("Mode", ["Login", "Register"])
            if mode == "Login":
                teacher_login()
            else:
                teacher_register()
    else:
        if role == "Student":
            student_dashboard()
            mobile_install_tip()
        elif role == "Teacher":
            teacher_dashboard()

if __name__ == "__main__":
    main()
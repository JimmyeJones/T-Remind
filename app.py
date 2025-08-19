import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import hashlib
from streamlit_cookies_manager import EncryptedCookieManager

# ------------------ COOKIE MANAGER ------------------
cookies = EncryptedCookieManager(
    prefix="hwapp_",  # cookie prefix
    password="super-secret-cookie-key",  # change in production
)

if not cookies.ready():
    st.stop()

# ------------------ DATABASE INIT ------------------
def init_db():
    conn = sqlite3.connect("hw.db")
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        teacher_id INTEGER,
        code TEXT UNIQUE
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        class_id INTEGER
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        due_date TEXT,
        class_id INTEGER
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        assignment_id INTEGER,
        submitted INTEGER DEFAULT 0
    )""")

    conn.commit()
    conn.close()

init_db()

# ------------------ HELPERS ------------------
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def fetchall_df(query, params=()):
    conn = sqlite3.connect("hw.db")
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

# ------------------ COOKIE HELPERS ------------------
def set_student_cookie(student_id:int, class_id:int, name:str):
    cookies["role"] = "student"
    cookies["student_id"] = str(student_id)
    cookies["class_id"] = str(class_id)
    cookies["student_name"] = name
    cookies["login_ts"] = datetime.utcnow().isoformat()
    cookies.save()

def set_teacher_cookie(teacher_id:int, username:str):
    cookies["role"] = "teacher"
    cookies["teacher_id"] = str(teacher_id)
    cookies["teacher_username"] = username
    cookies["login_ts"] = datetime.utcnow().isoformat()
    cookies.save()

def clear_cookies():
    cookies["role"] = ""
    cookies["teacher_id"] = ""
    cookies["student_id"] = ""
    cookies["class_id"] = ""
    cookies["teacher_username"] = ""
    cookies["student_name"] = ""
    cookies["login_ts"] = ""
    cookies.save()
    st.rerun()

# ------------------ STUDENT VIEWS ------------------
def student_join_view():
    st.header("Join a Class")
    name = st.text_input("Your Name")
    code = st.text_input("Class Code")
    if st.button("Join Class"):
        if not name or not code:
            st.error("Name and Class Code required.")
            return
        cl = fetchall_df("SELECT * FROM classes WHERE code=?", (code,))
        if cl.empty:
            st.error("Class not found.")
            return
        class_id = int(cl.iloc[0]["id"])
        conn = sqlite3.connect("hw.db")
        cur = conn.cursor()
        cur.execute("SELECT id FROM students WHERE name=? AND class_id=?", (name, class_id))
        row = cur.fetchone()
        if row:
            student_id = row[0]
        else:
            cur.execute("INSERT INTO students (name, class_id) VALUES (?,?)", (name, class_id))
            conn.commit()
            student_id = cur.lastrowid
        conn.close()
        set_student_cookie(student_id, class_id, name)
        st.success(f"Welcome to **{cl.iloc[0]['name']}**!")
        st.toast("Login saved. You’ll stay signed in on this device.")
        st.rerun()

def student_dashboard():
    student_name = cookies.get("student_name")
    class_id = cookies.get("class_id")
    if not student_name or not class_id:
        st.error("Invalid session, please rejoin.")
        clear_cookies()
        return
    st.header(f"📚 Student Dashboard - {student_name}")

    assignments = fetchall_df("SELECT * FROM assignments WHERE class_id=?", (class_id,))
    if assignments.empty:
        st.info("No assignments yet.")
    else:
        for _, row in assignments.iterrows():
            st.subheader(row["title"])
            st.write(row["description"])
            st.write(f"Due: {row['due_date']}")
            sid = cookies.get("student_id")
            subs = fetchall_df(
                "SELECT * FROM submissions WHERE student_id=? AND assignment_id=?",
                (sid, row["id"]),
            )
            submitted = (not subs.empty) and (subs.iloc[0]["submitted"] == 1)
            if submitted:
                st.success("Submitted ✅")
            else:
                if st.button(f"Mark as Submitted: {row['id']}", key=f"submit{row['id']}"):
                    conn = sqlite3.connect("hw.db")
                    cur = conn.cursor()
                    if subs.empty:
                        cur.execute(
                            "INSERT INTO submissions (student_id, assignment_id, submitted) VALUES (?,?,1)",
                            (sid, row["id"]),
                        )
                    else:
                        cur.execute(
                            "UPDATE submissions SET submitted=1 WHERE id=?",
                            (subs.iloc[0]["id"],),
                        )
                    conn.commit()
                    conn.close()
                    st.rerun()

# ------------------ TEACHER VIEWS ------------------
def teacher_register():
    st.header("Teacher Signup/Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Signup/Login"):
        if not username or not password:
            st.error("Enter both username and password")
            return
        conn = sqlite3.connect("hw.db")
        cur = conn.cursor()
        cur.execute("SELECT * FROM teachers WHERE username=?", (username,))
        row = cur.fetchone()
        h = hash_pw(password)
        if row:
            if row[2] != h:
                st.error("Invalid password")
                conn.close()
                return
            else:
                teacher_id = row[0]
        else:
            cur.execute("INSERT INTO teachers (username, password_hash) VALUES (?,?)", (username, h))
            conn.commit()
            teacher_id = cur.lastrowid
        conn.close()
        set_teacher_cookie(teacher_id, username)
        st.success("Logged in!")
        st.rerun()

def teacher_dashboard():
    st.header("👩‍🏫 Teacher Dashboard")
    tid = cookies.get("teacher_id")
    username = cookies.get("teacher_username")
    if not tid:
        st.error("Invalid session.")
        clear_cookies()
        return
    st.write(f"Welcome, **{username}**")

    st.subheader("Your Classes")
    df = fetchall_df("SELECT * FROM classes WHERE teacher_id=?", (tid,))
    if df.empty:
        st.info("No classes yet.")
    else:
        st.table(df[["id", "name", "code"]])

    cname = st.text_input("New Class Name")
    ccode = st.text_input("New Class Code (give to students)")
    if st.button("Create Class"):
        if cname and ccode:
            conn = sqlite3.connect("hw.db")
            cur = conn.cursor()
            cur.execute("INSERT INTO classes (name, teacher_id, code) VALUES (?,?,?)", (cname, tid, ccode))
            conn.commit()
            conn.close()
            st.success("Class created")
            st.rerun()
        else:
            st.error("Fill both fields")

    st.subheader("Assignments")
    class_options = fetchall_df("SELECT * FROM classes WHERE teacher_id=?", (tid,))
    if not class_options.empty:
        class_choice = st.selectbox("Select Class", class_options["name"])
        class_id = int(class_options[class_options["name"] == class_choice]["id"].iloc[0])
        title = st.text_input("Assignment Title")
        desc = st.text_area("Description")
        due = st.date_input("Due Date")
        if st.button("Add Assignment"):
            conn = sqlite3.connect("hw.db")
            cur = conn.cursor()
            cur.execute("INSERT INTO assignments (title, description, due_date, class_id) VALUES (?,?,?,?)",
                        (title, desc, str(due), class_id))
            conn.commit()
            conn.close()
            st.success("Assignment added")
            st.rerun()
        st.write("Assignments in this class:")
        st.table(fetchall_df("SELECT * FROM assignments WHERE class_id=?", (class_id,)))

# ------------------ ADMIN VIEW ------------------
def admin_view():
    st.header("Admin Panel")
    pw = st.text_input("Admin Password", type="password")
    if pw != "adminpass":  # change in production
        st.error("Invalid admin password")
        return
    st.success("Welcome, Admin")
    tab = st.radio("Select Table", ["teachers", "classes", "students", "assignments", "submissions"])
    df = fetchall_df(f"SELECT * FROM {tab}")
    st.dataframe(df)

# ------------------ MOBILE INSTALL TIP ------------------
def mobile_install_tip():
    with st.expander("📱 How to install this app on your phone"):
        st.markdown("""
**On iOS (Safari):**
1. Tap the **Share** button.
2. Scroll down and tap **Add to Home Screen**.
3. Done! Now you can open it like an app.

**On Android (Chrome):**
1. Tap the **3-dot menu** in the top right.
2. Tap **Add to Home screen**.
3. Done! Now it behaves like an app.
        """)

# ------------------ MAIN ------------------
def main():
    st.title("Homework Tracker")

    if cookies.get("role") == "student":
        student_dashboard()
        mobile_install_tip()
        if st.button("Logout"):
            clear_cookies()
    elif cookies.get("role") == "teacher":
        teacher_dashboard()
        mobile_install_tip()
        if st.button("Logout"):
            clear_cookies()
    else:
        role = st.radio("I am a...", ["Student", "Teacher", "Admin"])
        if role == "Student":
            student_join_view()
            mobile_install_tip()
        elif role == "Teacher":
            teacher_register()
            mobile_install_tip()
        elif role == "Admin":
            admin_view()

if __name__ == "__main__":
    main()
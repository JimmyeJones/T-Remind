import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
from datetime import datetime
from streamlit_cookies_manager import EncryptedCookieManager

# ------------------ COOKIE MANAGER ------------------
cookies = EncryptedCookieManager(
    prefix="hwapp_", password="a_very_strong_secret_password"
)
if not cookies.ready():
    st.stop()

# ------------------ DATABASE SETUP ------------------
def init_db():
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            access_code TEXT UNIQUE,
            teacher_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            class_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            due_date TEXT,
            class_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            assignment_id INTEGER,
            submitted INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect("data.db")

init_db()

# ------------------ AUTH HELPERS ------------------
def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def check_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode(), hashed)

# ------------------ COOKIE HELPERS ------------------
def set_student_cookie(student_id:int, class_id:int, name:str):
    cookies["role"] = "student"
    cookies["student_id"] = str(student_id)
    cookies["class_id"] = str(class_id)
    cookies["student_name"] = name
    cookies["login_ts"] = datetime.utcnow().isoformat()
    cookies.save()
    st.rerun()

def set_teacher_cookie(teacher_id:int, username:str):
    cookies["role"] = "teacher"
    cookies["teacher_id"] = str(teacher_id)
    cookies["teacher_username"] = username
    cookies["login_ts"] = datetime.utcnow().isoformat()
    cookies.save()
    st.rerun()

def clear_cookies():
    cookies.clear()
    cookies.save()
    st.rerun()

# ------------------ STUDENT VIEWS ------------------
def student_join_view():
    st.header("Join a Class")
    name = st.text_input("Your Name")
    code = st.text_input("Class Access Code")
    if st.button("Join"):
        if not name or not code:
            st.error("Enter both name and class code.")
            return
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM classes WHERE access_code=?", (code,))
        cl = c.fetchone()
        if not cl:
            st.error("Invalid class code.")
            conn.close()
            return
        class_id = cl[0]
        # see if student already exists
        c.execute("SELECT id FROM students WHERE name=? AND class_id=?", (name, class_id))
        strow = c.fetchone()
        if strow:
            student_id = strow[0]
        else:
            c.execute("INSERT INTO students (name, class_id) VALUES (?,?)", (name, class_id))
            conn.commit()
            student_id = c.lastrowid
        conn.close()
        set_student_cookie(student_id, class_id, name)
        st.success(f"Welcome to class! You’re now signed in as {name}")

def student_dashboard():
    student_name = cookies.get("student_name")
    class_id = int(cookies.get("class_id"))
    student_id = int(cookies.get("student_id"))
    st.header(f"Student Dashboard - {student_name}")

    conn = get_conn()
    assignments = pd.read_sql_query(
        "SELECT * FROM assignments WHERE class_id=? ORDER BY due_date",
        conn, params=(class_id,)
    )
    submissions = pd.read_sql_query(
        "SELECT * FROM submissions WHERE student_id=?",
        conn, params=(student_id,)
    )
    conn.close()

    if assignments.empty:
        st.info("No assignments yet.")
        return

    for _, row in assignments.iterrows():
        st.subheader(row["title"])
        st.write(row["description"])
        st.write(f"Due: {row['due_date']}")
        done = submissions[(submissions["assignment_id"] == row["id"]) & (submissions["submitted"] == 1)]
        if not done.empty:
            st.success("Submitted ✅")
        else:
            if st.button(f"Mark as submitted - {row['id']}", key=f"sub{row['id']}"):
                conn = get_conn()
                c = conn.cursor()
                c.execute("INSERT INTO submissions (student_id, assignment_id, submitted) VALUES (?,?,1)",
                          (student_id, row["id"]))
                conn.commit()
                conn.close()
                st.success("Marked as submitted.")
                st.rerun()

# ------------------ TEACHER VIEWS ------------------
def teacher_register():
    st.subheader("Teacher Registration")
    username = st.text_input("Choose a username")
    pw = st.text_input("Choose a password", type="password")
    if st.button("Register"):
        conn = get_conn()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO teachers (username,password_hash) VALUES (?,?)",
                      (username, hash_password(pw)))
            conn.commit()
            st.success("Teacher registered! Please log in.")
        except sqlite3.IntegrityError:
            st.error("Username already exists.")
        conn.close()

def teacher_login():
    st.subheader("Teacher Login")
    username = st.text_input("Username")
    pw = st.text_input("Password", type="password")
    if st.button("Login"):
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id,password_hash FROM teachers WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if row and check_password(pw, row[1]):
            set_teacher_cookie(row[0], username)
        else:
            st.error("Invalid credentials.")

def teacher_dashboard():
    teacher_username = cookies.get("teacher_username")
    teacher_id = int(cookies.get("teacher_id"))
    st.header(f"Teacher Dashboard - {teacher_username}")

    st.subheader("Your Classes")
    conn = get_conn()
    classes = pd.read_sql_query("SELECT * FROM classes WHERE teacher_id=?", conn, params=(teacher_id,))
    conn.close()
    st.table(classes[["id","name","access_code"]])

    st.subheader("Create New Class")
    cname = st.text_input("Class name")
    ccode = st.text_input("Class access code")
    if st.button("Create class"):
        conn = get_conn()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO classes (name,access_code,teacher_id) VALUES (?,?,?)",
                      (cname, ccode, teacher_id))
            conn.commit()
            st.success("Class created!")
            st.rerun()
        except sqlite3.IntegrityError:
            st.error("Access code already in use.")
        conn.close()

    st.subheader("Create Assignment")
    class_choice = st.selectbox("Select class", classes["id"] if not classes.empty else [])
    title = st.text_input("Assignment title")
    desc = st.text_area("Assignment description")
    due = st.date_input("Due date")
    if st.button("Create assignment"):
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO assignments (title,description,due_date,class_id) VALUES (?,?,?,?)",
                  (title, desc, due.isoformat(), class_choice))
        conn.commit()
        conn.close()
        st.success("Assignment created!")
        st.rerun()

# ------------------ ADMIN VIEW ------------------
def admin_view():
    st.title("Admin Control Panel")
    st.warning("Be careful. These edits apply globally.")
    conn = get_conn()
    tables = ["teachers","classes","students","assignments","submissions"]
    for t in tables:
        st.subheader(t)
        df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
        st.dataframe(df)
    conn.close()

# ------------------ MOBILE INSTRUCTIONS ------------------
def mobile_install_tip():
    st.markdown("""
    ---
    ### 📱 Add to Home Screen (iOS & Android)
    - **iOS (Safari):** Tap Share → *Add to Home Screen*  
    - **Android (Chrome):** Tap ⋮ menu → *Add to Home Screen*  
    This makes the app behave like a standalone app.
    ---
    """)

# ------------------ MAIN ------------------
def main():
    st.title("📘 Homework Tracker")

    if st.sidebar.button("Logout"):
        clear_cookies()

    role = cookies.get("role")

    if not role:
        st.sidebar.title("Login / Register")
        choice = st.sidebar.radio("Choose:", ["Student Join", "Teacher Login", "Teacher Register", "Admin"])
        if choice == "Student Join":
            student_join_view()
            mobile_install_tip()
        elif choice == "Teacher Login":
            teacher_login()
            mobile_install_tip()
        elif choice == "Teacher Register":
            teacher_register()
            mobile_install_tip()
        elif choice == "Admin":
            pw = st.text_input("Enter admin password", type="password")
            if pw == "admin123":  # Change in production!
                admin_view()
            elif pw:
                st.error("Invalid admin password.")
            else:
                st.info("Enter the admin password to proceed.")
    else:
        if role == "Student":
            student_dashboard()
            mobile_install_tip()
        elif role == "Teacher":
            teacher_dashboard()
            mobile_install_tip()

if __name__ == "__main__":
    main()
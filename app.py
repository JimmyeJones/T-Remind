# app.py
import streamlit as st
import sqlite3
import bcrypt
import base64
import secrets
import string
import pandas as pd
from datetime import datetime, date
from typing import Optional, Tuple, List
from streamlit_cookies_manager import EncryptedCookieManager

# -----------------------------
# App Config
# -----------------------------
st.set_page_config(page_title="Classwork Tracker", page_icon="📝", layout="wide")

# -----------------------------
# Cookies (persisted login)
# -----------------------------
cookies = EncryptedCookieManager(
    prefix="hwtracker_",
    password=st.secrets.get("cookie_secret", None)  # set in secrets.toml
)
if not cookies.ready():
    st.stop()

# -----------------------------
# DB Helpers (SQLite)
# -----------------------------
@st.cache_resource(show_spinner=False)
def get_conn():
    return sqlite3.connect("school.db", check_same_thread=False)

def run(query: str, params: tuple = ()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    return cur

def fetchall_df(query: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    return df

def init_db():
    run("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    run("""
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        access_code TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
    )""")
    run("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        class_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, class_id),
        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
    )""")
    run("""
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        due_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
    )""")
    run("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        completed_at TEXT,
        UNIQUE(assignment_id, student_id),
        FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )""")
    run("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        class_id INTEGER NOT NULL,
        email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, class_id),
        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
    )""")

init_db()

# -----------------------------
# Utilities
# -----------------------------
def b64(s: bytes) -> str:
    return base64.b64encode(s).decode("utf-8")

def b64decode_str(s: str) -> bytes:
    return base64.b64decode(s.encode("utf-8"))

def hash_password(pw: str) -> str:
    return b64(bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()))

def check_password(pw: str, stored_hash_b64: str) -> bool:
    return bcrypt.checkpw(pw.encode("utf-8"), b64decode_str(stored_hash_b64))

def code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def require_admin(pass_input: str) -> bool:
    expected = st.secrets.get("admin_password", "")
    return bool(expected) and pass_input == expected

def user_banner():
    st.markdown(
        """
        <style>
        .tip {background:#f6f9fe;border:1px solid #dbe7ff;padding:0.75rem 1rem;border-radius:8px}
        </style>
        """,
        unsafe_allow_html=True
    )

# -----------------------------
# Session helpers (IDs from cookies)
# -----------------------------
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

def sign_out():
    for k in list(cookies.keys()):
        cookies.pop(k, None)
    cookies.save()
    st.rerun()
    
import smtplib
from email.mime.text import MIMEText

def send_email(to_email: str, subject: str, body: str):
    sender = st.secrets["gmail"]["email"]
    password = st.secrets["gmail"]["app_password"]  # use App Password

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, [to_email], msg.as_string())
    except Exception as e:
        st.error(f"Error sending email: {e}")
# -----------------------------
# STUDENT Views
# -----------------------------
def student_join_view():
    st.subheader("Join a Class")
    with st.form("student_join_form"):
        student_name = st.text_input("Your name*", placeholder="e.g., Alex Johnson")
        access_code = st.text_input("Class access code*", placeholder="e.g., 3H8KQZ").upper().strip()
        submitted = st.form_submit_button("Join")
    if submitted:
        if not student_name or not access_code:
            st.error("Please provide your name and a class access code.")
            return
        cl = fetchall_df("SELECT id, name FROM classes WHERE access_code = ?", (access_code,))
        if cl.empty:
            st.error("Couldn't find a class with that code.")
            return
        class_id = int(cl.iloc[0]["id"])
        try:
            run("INSERT INTO students (name, class_id) VALUES (?,?)", (student_name, class_id))
        except sqlite3.IntegrityError:
            pass
        strow = fetchall_df("SELECT id FROM students WHERE name=? AND class_id=?", (student_name, class_id))
        student_id = int(strow.iloc[0]["id"])
        set_student_cookie(student_id, class_id, student_name)
        st.success(f"Welcome to **{cl.iloc[0]['name']}**! You’re now signed in.")
        st.toast("Login saved. You’ll stay signed in on this device.")

def student_home():
    student_id = int(cookies.get("student_id", "0"))
    class_id = int(cookies.get("class_id", "0"))
    name = cookies.get("student_name", "Student")

    header_cols = st.columns([1, 1, 1, 1])
    header_cols[0].markdown(f"### 👋 Hi, **{name}**")
    if header_cols[3].button("Sign out"):
        sign_out()

    cl = fetchall_df("SELECT name FROM classes WHERE id=?", (class_id,))
    if cl.empty:
        st.warning("Your class no longer exists. Please join again.")
        return
    st.caption(f"Class: {cl.iloc[0]['name']}")

    asg = fetchall_df("""
        SELECT a.id, a.title, a.description, a.due_date,
               COALESCE(s.status, 'pending') AS status,
               s.completed_at
        FROM assignments a
        LEFT JOIN submissions s ON a.id = s.assignment_id AND s.student_id = ?
        WHERE a.class_id = ?
        ORDER BY COALESCE(a.due_date, '9999-12-31') ASC, a.id DESC
    """, (student_id, class_id))

    left, right = st.columns([2, 1])
    with left:
        st.subheader("Your Assignments")
        if asg.empty:
            st.info("No assignments yet. Check back later!")
        else:
            for _, row in asg.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['title']}**")
                    if row["description"]:
                        st.write(row["description"])
                    due = row["due_date"]
                    if due:
                        due_dt = date.fromisoformat(due)
                        badge = "✅" if row["status"] == "done" else "⏳"
                        st.caption(f"{badge} Due: {due_dt.strftime('%b %d, %Y')}")
                    cols = st.columns([1, 1, 3])
                    if row["status"] != "done":
                        if cols[0].button("Mark done", key=f"mkdone_{row['id']}"):
                            try:
                                run("INSERT INTO submissions (assignment_id, student_id, status, completed_at) VALUES (?,?,?,?)",
                                    (int(row["id"]), student_id, "done", datetime.utcnow().isoformat()))
                            except sqlite3.IntegrityError:
                                run("UPDATE submissions SET status='done', completed_at=? WHERE assignment_id=? AND student_id=?",
                                    (datetime.utcnow().isoformat(), int(row["id"]), student_id))
                            st.rerun()
                    else:
                        cols[0].write("✅ Done")
                        if cols[1].button("Undo", key=f"undo_{row['id']}"):
                            run("UPDATE submissions SET status='pending', completed_at=NULL WHERE assignment_id=? AND student_id=?",
                                (int(row["id"]), student_id))
                            st.rerun()

    with right:
        st.subheader("Profile")
        with st.form("student_profile"):
            new_name = st.text_input("Display name", value=name)
            email = fetchall_df("SELECT email FROM students WHERE id=?", (student_id,))
            cur_email = email.iloc[0]["email"] if not email.empty else ""
            new_email = st.text_input("Email (optional, for notifications)", value=cur_email)

            if st.form_submit_button("Update profile"):
                run("UPDATE students SET name=?, email=? WHERE id=?", (new_name, new_email, student_id))
                cookies["student_name"] = new_name
                cookies.save()
                st.success("Profile updated!")
# -----------------------------
# -----------------------------
# TEACHER Views
# -----------------------------
def teacher_signup():
    st.subheader("Teacher Sign Up")
    with st.form("signup_form"):
        username = st.text_input("Choose username*")
        password = st.text_input("Choose password*", type="password")
        submitted = st.form_submit_button("Sign Up")
    if submitted:
        if not username or not password:
            st.error("Please enter username and password")
            return
        try:
            run("INSERT INTO teachers (username, password_hash) VALUES (?,?)",
                (username, hash_password(password)))
            st.success("Account created. Please log in.")
        except sqlite3.IntegrityError:
            st.error("That username is already taken.")

def teacher_login():
    st.subheader("Teacher Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
    if submitted:
        row = fetchall_df("SELECT id, password_hash FROM teachers WHERE username=?", (username,))
        if row.empty or not check_password(password, row.iloc[0]["password_hash"]):
            st.error("Invalid credentials")
        else:
            set_teacher_cookie(int(row.iloc[0]["id"]), username)
            st.rerun()

def teacher_dashboard():
    tid = int(cookies.get("teacher_id", "0"))
    uname = cookies.get("teacher_username", "Teacher")

    header_cols = st.columns([1, 2, 1])
    header_cols[0].markdown(f"### 👋 Hi, **{uname}**")
    if header_cols[2].button("Sign out"):
        sign_out()

    tabs = st.tabs(["📚 Classes", "📝 Assignments", "👥 Students"])
    with tabs[0]:
        teacher_classes_tab(tid)
    with tabs[1]:
        teacher_assignments_tab(tid)
    with tabs[2]:
        teacher_students_tab(tid)

def teacher_classes_tab(teacher_id:int):
    st.subheader("Your Classes")
    cl = fetchall_df("SELECT id, name, access_code FROM classes WHERE teacher_id=?", (teacher_id,))
    if cl.empty:
        st.info("You have no classes yet. Create one below.")
    else:
        for _, row in cl.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['name']}** — Code: `{row['access_code']}`")
                if st.button("Delete", key=f"del_class_{row['id']}"):
                    run("DELETE FROM classes WHERE id=?", (int(row['id']),))
                    st.rerun()

    with st.form("new_class"):
        newname = st.text_input("Class name")
        if st.form_submit_button("Create Class"):
            if not newname.strip():
                st.error("Enter a name")
            else:
                acc = code()
                run("INSERT INTO classes (teacher_id, name, access_code) VALUES (?,?,?)",
                    (teacher_id, newname.strip(), acc))
                st.success(f"Created class {newname} with code {acc}")
                st.rerun()

def teacher_assignments_tab(teacher_id:int):
    cl = fetchall_df("SELECT id, name FROM classes WHERE teacher_id=?", (teacher_id,))
    if cl.empty:
        st.info("No classes yet")
        return
    class_opts = dict(zip(cl["name"], cl["id"]))
    cname = st.selectbox("Choose class", list(class_opts.keys()))
    class_id = class_opts[cname]

    asg = fetchall_df("SELECT * FROM assignments WHERE class_id=? ORDER BY id DESC", (class_id,))
    st.subheader("Assignments")
    if asg.empty:
        st.write("None yet")
    else:
        for _, row in asg.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['title']}** (Due {row['due_date'] or 'N/A'})")
                if row["description"]:
                    st.caption(row["description"])
                if st.button("Delete", key=f"del_asg_{row['id']}"):
                    run("DELETE FROM assignments WHERE id=?", (int(row['id']),))
                    st.rerun()

    st.subheader("Create new assignment")
    with st.form("new_asg"):
        t = st.text_input("Title*")
        d = st.text_area("Description")
        due = st.date_input("Due date", value=None)
        notify = st.checkbox("Notify students via email")

        if st.form_submit_button("Create"):
            if not t.strip():
                st.error("Enter a title")
            else:
                due_str = due.isoformat() if due else None
                run("INSERT INTO assignments (class_id, title, description, due_date) VALUES (?,?,?,?)",
                (class_id, t, d, due_str))

                if notify:
                    students = fetchall_df("SELECT name, email FROM students WHERE class_id=? AND email IS NOT NULL", (class_id,))
                    for _, s in students.iterrows():
                    body = f"Hi {s['name']},\n\nA new assignment has been posted:\n\nTitle: {t}\nDescription: {d}\nDue: {due_str or 'N/A'}\n\nPlease log in to view more details."
                    send_email(s["email"], f"New Assignment: {t}", body)

                st.success("Assignment added")
                st.rerun()

def teacher_students_tab(teacher_id:int):
    cl = fetchall_df("SELECT id, name FROM classes WHERE teacher_id=?", (teacher_id,))
    if cl.empty:
        st.info("No classes yet")
        return
    class_opts = dict(zip(cl["name"], cl["id"]))
    cname = st.selectbox("Choose class", list(class_opts.keys()), key="stud_sel")
    class_id = class_opts[cname]

    st.subheader("Students")
    studs = fetchall_df("SELECT id, name, created_at FROM students WHERE class_id=?", (class_id,))
    if studs.empty:
        st.write("No students yet")
    else:
        for _, row in studs.iterrows():
            with st.container(border=True):
                st.write(f"{row['name']} (joined {row['created_at'][:10]})")
                if st.button("Remove", key=f"rem_stud_{row['id']}"):
                    run("DELETE FROM students WHERE id=?", (int(row['id']),))
                    st.rerun()

# -----------------------------
# ADMIN Views
# -----------------------------
def admin_panel():
    st.subheader("Admin Panel")
    tabs = st.tabs(["Teachers", "Classes", "Students", "Assignments", "Submissions"])

    with tabs[0]:
        df = fetchall_df("SELECT id, username, created_at FROM teachers")
        st.dataframe(df)
        if not df.empty:
            id_to_del = st.selectbox("Delete teacher id", df["id"])
            if st.button("Delete teacher"):
                run("DELETE FROM teachers WHERE id=?", (int(id_to_del),))
                st.rerun()

    with tabs[1]:
        df = fetchall_df("SELECT id, name, access_code, teacher_id FROM classes")
        st.dataframe(df)
        if not df.empty:
            id_to_del = st.selectbox("Delete class id", df["id"])
            if st.button("Delete class"):
                run("DELETE FROM classes WHERE id=?", (int(id_to_del),))
                st.rerun()

    with tabs[2]:
        df = fetchall_df("SELECT id, name, class_id FROM students")
        st.dataframe(df)
        if not df.empty:
            id_to_del = st.selectbox("Delete student id", df["id"])
            if st.button("Delete student"):
                run("DELETE FROM students WHERE id=?", (int(id_to_del),))
                st.rerun()

    with tabs[3]:
        df = fetchall_df("SELECT id, title, class_id, due_date FROM assignments")
        st.dataframe(df)
        if not df.empty:
            id_to_del = st.selectbox("Delete assignment id", df["id"])
            if st.button("Delete assignment"):
                run("DELETE FROM assignments WHERE id=?", (int(id_to_del),))
                st.rerun()

    with tabs[4]:
        df = fetchall_df("SELECT id, assignment_id, student_id, status, completed_at FROM submissions")
        st.dataframe(df)
        if not df.empty:
            id_to_del = st.selectbox("Delete submission id", df["id"])
            if st.button("Delete submission"):
                run("DELETE FROM submissions WHERE id=?", (int(id_to_del),))
                st.rerun()
# -----------------------------
# Mobile install tips
# -----------------------------
def mobile_install_tip():
    with st.expander("📲 Add this app to your phone’s Home Screen"):
        st.markdown("""
        **iOS (Safari):** Open the site → tap **Share** → **Add to Home Screen** → **Add**.  
        **Android (Chrome):** Open the site → tap **⋮** → **Add to Home screen** → **Add**.
        """)

# -----------------------------
# Main Router
# -----------------------------
def main():
    user_banner()
    st.title("📝 Classwork & Homework Tracker")
    role = st.sidebar.radio("Use as", ["Student", "Teacher", "Admin"])
    cookie_role = cookies.get("role")
    if cookie_role == "student" and role == "Student":
        student_home()
        mobile_install_tip()
        return
    if cookie_role == "teacher" and role == "Teacher":
        teacher_dashboard()
        mobile_install_tip()
        return
    if role == "Student":
        student_join_view()
        mobile_install_tip()
    elif role == "Teacher":
        auth_tab = st.tabs(["Login", "Sign Up"])
        with auth_tab[0]:
            teacher_login()
        with auth_tab[1]:
            teacher_signup()
        mobile_install_tip()
    else:
        pw = st.text_input("Admin password", type="password")
        if require_admin(pw):
            admin_panel()
            mobile_install_tip()
        else:
            if pw:
                st.error("Invalid admin password.")
            st.info("Enter the admin password to proceed.")

main()
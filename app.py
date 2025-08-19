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
    # On Streamlit Cloud this file lives alongside the app.
    # It persists across sessions but may reset on redeploy; use Admin → Export for backups.
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
        due_date TEXT, -- ISO date
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
    )""")
    run("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending', -- pending|done
        completed_at TEXT,
        UNIQUE(assignment_id, student_id),
        FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
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
    cookies.set("login_ts", datetime.utcnow().isoformat(), expires_days=365)
    cookies.save()

def set_teacher_cookie(teacher_id:int, username:str):
    cookies["role"] = "teacher"
    cookies["teacher_id"] = str(teacher_id)
    cookies["teacher_username"] = username
    cookies.set("login_ts", datetime.utcnow().isoformat(), expires_days=365)
    cookies.save()

def sign_out():
    for k in list(cookies.keys()):
        cookies.pop(k, None)
    cookies.save()
    st.rerun()

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
        # Create or fetch student
        try:
            run("INSERT INTO students (name, class_id) VALUES (?,?)", (student_name, class_id))
        except sqlite3.IntegrityError:
            pass  # student already exists in that class
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

    # Class info
    cl = fetchall_df("SELECT name FROM classes WHERE id=?", (class_id,))
    if cl.empty:
        st.warning("Your class no longer exists. Please join again.")
        return
    st.caption(f"Class: {cl.iloc[0]['name']}")

    # Assignments
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
            if st.form_submit_button("Update name"):
                run("UPDATE students SET name=? WHERE id=?", (new_name, student_id))
                cookies["student_name"] = new_name
                cookies.save()
                st.success("Updated!")

# -----------------------------
# TEACHER Views
# -----------------------------
def teacher_signup():
    st.subheader("Create a Teacher Account")
    with st.form("signup"):
        username = st.text_input("Username *").strip()
        pw = st.text_input("Password *", type="password")
        pw2 = st.text_input("Confirm password *", type="password")
        created = st.form_submit_button("Create account")
    if created:
        if not username or not pw or pw != pw2:
            st.error("Please fill all fields and make sure passwords match.")
            return
        pw_hash = hash_password(pw)
        try:
            run("INSERT INTO teachers (username, password_hash) VALUES (?,?)", (username, pw_hash))
        except sqlite3.IntegrityError:
            st.error("That username is taken.")
            return
        t = fetchall_df("SELECT id FROM teachers WHERE username=?", (username,))
        set_teacher_cookie(int(t.iloc[0]["id"]), username)
        st.success("Account created and you’re logged in!")

def teacher_login():
    st.subheader("Teacher Login")
    with st.form("login"):
        username = st.text_input("Username *").strip()
        pw = st.text_input("Password *", type="password")
        ok = st.form_submit_button("Sign in")
    if ok:
        row = fetchall_df("SELECT id, password_hash FROM teachers WHERE username=?", (username,))
        if row.empty or not check_password(pw, row.iloc[0]["password_hash"]):
            st.error("Invalid username or password.")
            return
        set_teacher_cookie(int(row.iloc[0]["id"]), username)
        st.success("Welcome back!")

def teacher_dashboard():
    teacher_id = int(cookies.get("teacher_id", "0"))
    username = cookies.get("teacher_username", "Teacher")
    top = st.columns([1, 1, 1, 1])
    top[0].markdown(f"### 👋 Hello, **{username}**")
    if top[3].button("Sign out"):
        sign_out()

    st.subheader("Your Classes")

    # Create class
    with st.form("create_class", clear_on_submit=True):
        cname = st.text_input("New class name *", placeholder="e.g., Algebra 1 - Period 3")
        create = st.form_submit_button("Create class")
    if create:
        acode = code(6)
        run("INSERT INTO classes (teacher_id, name, access_code) VALUES (?,?,?)",
            (teacher_id, cname, acode))
        st.success(f"Class **{cname}** created. Access code: **{acode}**")

    classes = fetchall_df("SELECT id, name, access_code, created_at FROM classes WHERE teacher_id=? ORDER BY id DESC",
                          (teacher_id,))
    if classes.empty:
        st.info("No classes yet. Create one above.")
    else:
        for _, row in classes.iterrows():
            with st.expander(f"📚 {row['name']}  •  Code: {row['access_code']}"):
                cid = int(row["id"])
                tabs = st.tabs(["Assignments", "Students", "Settings"])
                # Assignments Tab
                with tabs[0]:
                    with st.form(f"add_asg_{cid}", clear_on_submit=True):
                        t = st.text_input("Title *", key=f"title_{cid}")
                        d = st.text_area("Description", key=f"desc_{cid}")
                        due = st.date_input("Due date (optional)", value=None, key=f"due_{cid}")
                        addbtn = st.form_submit_button("Add assignment")
                    if addbtn:
                        due_str = due.isoformat() if isinstance(due, date) else None
                        run("INSERT INTO assignments (class_id, title, description, due_date) VALUES (?,?,?,?)",
                            (cid, t, d, due_str))
                        st.success("Assignment added.")
                    asg = fetchall_df(
                        "SELECT id, title, description, due_date FROM assignments WHERE class_id=? ORDER BY COALESCE(due_date, '9999-12-31') ASC, id DESC",
                        (cid,))
                    if not asg.empty:
                        st.dataframe(asg, use_container_width=True)
                        for _, a in asg.iterrows():
                            with st.container(border=True):
                                st.markdown(f"**{a['title']}**  •  Due: {a['due_date'] or '—'}")
                                # Show completion table
                                comp = fetchall_df("""
                                    SELECT s.id as submission_id, stu.name as student, COALESCE(s.status,'pending') as status, s.completed_at
                                    FROM students stu
                                    LEFT JOIN submissions s ON s.student_id = stu.id
                                        AND s.assignment_id = ?
                                    WHERE stu.class_id = ?
                                    ORDER BY stu.name ASC
                                """, (int(a["id"]), cid))
                                if comp.empty:
                                    st.caption("_No students yet._")
                                else:
                                    # Toggle done/undo inline
                                    cols = st.columns([1, 2, 2, 1])
                                    cols[0].markdown("**Student**")
                                    cols[1].markdown("**Status**")
                                    cols[2].markdown("**Completed at**")
                                    cols[3].markdown("**Action**")
                                    for _, rr in comp.iterrows():
                                        c = st.columns([1, 2, 2, 1])
                                        c[0].write(rr["student"])
                                        c[1].write("✅ done" if rr["status"] == "done" else "⏳ pending")
                                        c[2].write(rr["completed_at"] or "—")
                                        if rr["status"] != "done":
                                            if c[3].button("Mark done", key=f"tdone_{a['id']}_{rr['student']}"):
                                                # Insert or update
                                                stuid = fetchall_df("SELECT id FROM students WHERE name=? AND class_id=?",
                                                                    (rr["student"], cid)).iloc[0]["id"]
                                                try:
                                                    run("INSERT INTO submissions (assignment_id, student_id, status, completed_at) VALUES (?,?,?,?)",
                                                        (int(a["id"]), int(stuid), "done", datetime.utcnow().isoformat()))
                                                except sqlite3.IntegrityError:
                                                    run("UPDATE submissions SET status='done', completed_at=? WHERE assignment_id=? AND student_id=?",
                                                        (datetime.utcnow().isoformat(), int(a["id"]), int(stuid)))
                                                st.rerun()
                                        else:
                                            if c[3].button("Undo", key=f"tundo_{a['id']}_{rr['student']}"):
                                                stuid = fetchall_df("SELECT id FROM students WHERE name=? AND class_id=?",
                                                                    (rr["student"], cid)).iloc[0]["id"]
                                                run("UPDATE submissions SET status='pending', completed_at=NULL WHERE assignment_id=? AND student_id=?",
                                                    (int(a["id"]), int(stuid)))
                                                st.rerun()

                # Students Tab
                with tabs[1]:
                    st.caption("Students appear as they join with your class code.")
                    studs = fetchall_df("SELECT id, name, created_at FROM students WHERE class_id=? ORDER BY name ASC", (cid,))
                    st.dataframe(studs, use_container_width=True)

                # Settings Tab
                with tabs[2]:
                    st.text_input("Class name", value=row["name"], key=f"cname_{cid}", disabled=True)
                    st.text_input("Access code", value=row["access_code"], key=f"ccode_{cid}", disabled=True)
                    cols = st.columns([1, 1, 3])
                    if cols[0].button("Regenerate code", key=f"regen_{cid}"):
                        new_code = code(6)
                        run("UPDATE classes SET access_code=? WHERE id=?", (new_code, cid))
                        st.success(f"New class code: **{new_code}**")
                        st.rerun()
                    if cols[1].button("Delete class", key=f"delclass_{cid}"):
                        run("DELETE FROM classes WHERE id=?", (cid,))
                        st.success("Class deleted.")
                        st.rerun()

# -----------------------------
# ADMIN Views
# -----------------------------
def admin_panel():
    st.subheader("Admin Panel")
    st.caption("Full manual editing ability. Handle with care.")
    tabs = st.tabs(["Teachers", "Classes", "Students", "Assignments", "Submissions", "Export/Import", "About"])
    # Teachers
    with tabs[0]:
        df = fetchall_df("SELECT id, username, password_hash, created_at FROM teachers ORDER BY id ASC")
        edited = st.data_editor(df, use_container_width=True, disabled=["id"])
        if st.button("Save Teachers"):
            # upsert loop
            for _, r in edited.iterrows():
                run("UPDATE teachers SET username=?, password_hash=? WHERE id=?",
                    (r["username"], r["password_hash"], int(r["id"])))
            st.success("Saved.")
        # Add / Delete
        with st.form("add_teacher", clear_on_submit=True):
            u = st.text_input("New username")
            p = st.text_input("New password", type="password")
            if st.form_submit_button("Add"):
                if not u or not p:
                    st.error("Username and password required.")
                else:
                    try:
                        run("INSERT INTO teachers (username, password_hash) VALUES (?,?)", (u, hash_password(p)))
                        st.success("Teacher added.")
                    except sqlite3.IntegrityError:
                        st.error("Username already exists.")
        del_id = st.text_input("Delete teacher by id")
        if st.button("Delete Teacher"):
            if del_id.isdigit():
                run("DELETE FROM teachers WHERE id=?", (int(del_id),))
                st.success("Deleted.")
                st.rerun()

    # Classes
    with tabs[1]:
        df = fetchall_df("SELECT id, teacher_id, name, access_code, created_at FROM classes ORDER BY id ASC")
        edited = st.data_editor(df, use_container_width=True, disabled=["id"])
        if st.button("Save Classes"):
            for _, r in edited.iterrows():
                run("UPDATE classes SET teacher_id=?, name=?, access_code=? WHERE id=?",
                    (int(r["teacher_id"]), r["name"], r["access_code"], int(r["id"])))
            st.success("Saved.")
        del_id = st.text_input("Delete class by id")
        if st.button("Delete Class"):
            if del_id.isdigit():
                run("DELETE FROM classes WHERE id=?", (int(del_id),))
                st.success("Deleted.")
                st.rerun()

    # Students
    with tabs[2]:
        df = fetchall_df("SELECT id, name, class_id, created_at FROM students ORDER BY id ASC")
        edited = st.data_editor(df, use_container_width=True, disabled=["id"])
        if st.button("Save Students"):
            for _, r in edited.iterrows():
                run("UPDATE students SET name=?, class_id=? WHERE id=?",
                    (r["name"], int(r["class_id"]), int(r["id"])))
            st.success("Saved.")
        del_id = st.text_input("Delete student by id")
        if st.button("Delete Student"):
            if del_id.isdigit():
                run("DELETE FROM students WHERE id=?", (int(del_id),))
                st.success("Deleted.")
                st.rerun()

    # Assignments
    with tabs[3]:
        df = fetchall_df("SELECT id, class_id, title, description, due_date, created_at FROM assignments ORDER BY id ASC")
        edited = st.data_editor(df, use_container_width=True, disabled=["id"])
        if st.button("Save Assignments"):
            for _, r in edited.iterrows():
                run("UPDATE assignments SET class_id=?, title=?, description=?, due_date=? WHERE id=?",
                    (int(r["class_id"]), r["title"], r["description"], r["due_date"], int(r["id"])))
            st.success("Saved.")
        del_id = st.text_input("Delete assignment by id")
        if st.button("Delete Assignment"):
            if del_id.isdigit():
                run("DELETE FROM assignments WHERE id=?", (int(del_id),))
                st.success("Deleted.")
                st.rerun()

    # Submissions
    with tabs[4]:
        df = fetchall_df("""SELECT id, assignment_id, student_id, status, completed_at
                            FROM submissions ORDER BY id ASC""")
        edited = st.data_editor(df, use_container_width=True, disabled=["id"])
        if st.button("Save Submissions"):
            for _, r in edited.iterrows():
                run("UPDATE submissions SET assignment_id=?, student_id=?, status=?, completed_at=? WHERE id=?",
                    (int(r["assignment_id"]), int(r["student_id"]), r["status"], r["completed_at"], int(r["id"])))
            st.success("Saved.")
        del_id = st.text_input("Delete submission by id")
        if st.button("Delete Submission"):
            if del_id.isdigit():
                run("DELETE FROM submissions WHERE id=?", (int(del_id),))
                st.success("Deleted.")
                st.rerun()

    # Export / Import
    with tabs[5]:
        st.markdown("#### Export CSVs")
        for table in ["teachers", "classes", "students", "assignments", "submissions"]:
            df = fetchall_df(f"SELECT * FROM {table}")
            st.download_button(f"Download {table}.csv", df.to_csv(index=False).encode("utf-8"),
                               file_name=f"{table}.csv", mime="text/csv")
        st.markdown("#### Import CSVs (schema must match)")
        up = st.file_uploader("Upload CSV to replace a table", type=["csv"])
        tgt = st.selectbox("Target table", ["teachers", "classes", "students", "assignments", "submissions"])
        if st.button("Replace with uploaded CSV"):
            if up is None:
                st.error("Please upload a CSV.")
            else:
                df = pd.read_csv(up)
                conn = get_conn()
                df.to_sql(tgt, conn, if_exists="replace", index=False)
                st.success(f"Replaced `{tgt}` with uploaded CSV.")
                st.rerun()

    with tabs[6]:
        st.markdown("""
        - Passwords for **teachers** are **bcrypt hashed** (one-way) before storage.
        - **Students** have no passwords; they stay signed in via encrypted cookies on their device.
        - **Access codes** for classes do not expire (you can regenerate in Teacher → Settings).
        - Storage: local `SQLite` file. On Streamlit Cloud, this persists across sessions but can reset on redeploys.
          Use **Admin → Export** to keep backups. You can also mount a cloud DB later if needed.
        """)

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

    # Sidebar Role Switcher
    role = st.sidebar.radio("Use as", ["Student", "Teacher", "Admin"])

    # Auto-redirect if cookie role present
    cookie_role = cookies.get("role")
    if cookie_role == "student" and role == "Student":
        student_home()
        mobile_install_tip()
        return
    if cookie_role == "teacher" and role == "Teacher":
        teacher_dashboard()
        mobile_install_tip()
        return

    # Selected role views
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

    else:  # Admin
        pw = st.text_input("Admin password", type="password")
        if require_admin(pw):
            admin_panel()
            mobile_install_tip()
        else:
            if pw:
                st.error("Invalid admin password.")
            st.info("Enter the admin password to proceed.")

main()

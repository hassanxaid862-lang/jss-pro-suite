import streamlit as st
import pandas as pd
import sqlite3
from fpdf import FPDF
import io
from PIL import Image
import plotly.express as px
import os

# ==========================================
# 1. DATABASE & STORAGE ENGINE
# ==========================================

def get_db_connection(grade_name):
    """Establishes connection to the specific grade's database."""
    # Ensure database is created in the app's root directory for persistence
    db_file = os.path.join(os.getcwd(), f"{grade_name.replace(' ', '_').lower()}.db")
    return sqlite3.connect(db_file)

def init_db(grade_name):
    """Initializes standard and settings tables if they do not exist."""
    conn = get_db_connection(grade_name)
    c = conn.cursor()
    
    # Table for learners
    c.execute('''CREATE TABLE IF NOT EXISTS learners 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, grade TEXT, assmt_no TEXT)''')
    
    # Table for marks
    c.execute('''CREATE TABLE IF NOT EXISTS marks 
                 (learner_id INTEGER, area TEXT, score REAL, 
                  FOREIGN KEY(learner_id) REFERENCES learners(id))''')
    
    # Table for system settings (Password)
    c.execute('''CREATE TABLE IF NOT EXISTS settings 
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Set default password if not exists
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('password', 'admin')")
    
    conn.commit()
    conn.close()

def get_system_password():
    """Retrieves the system password from a central config DB."""
    db_path = os.path.join(os.getcwd(), "system_config.db") # Using a central config DB
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('password', 'admin')")
    c.execute("SELECT value FROM settings WHERE key = 'password'")
    pwd = c.fetchone()[0]
    conn.close()
    return pwd

def update_system_password(new_pwd):
    """Updates the system password in the central config DB."""
    db_path = os.path.join(os.getcwd(), "system_config.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = 'password'", (new_pwd,))
    conn.commit()
    conn.close()

def save_to_db(df, target_grade):
    """Handles bulk and manual data ingestion, ensuring no duplicate entries."""
    conn = get_db_connection(target_grade)
    c = conn.cursor()
    areas = df.columns[3:] # Assumes first 3 columns are standard learner info
    for _, row in df.iterrows():
        # Check for existing learner in that grade
        c.execute("SELECT id FROM learners WHERE assmt_no = ?", (str(row["Assessment Number"]),))
        existing = c.fetchone()
        
        if existing:
            # Overwrite logic
            l_id = existing[0]
            c.execute("DELETE FROM marks WHERE learner_id = ?", (l_id,))
            c.execute("DELETE FROM learners WHERE id = ?", (l_id,))
            
        # Create new learner record
        c.execute("INSERT INTO learners (name, grade, assmt_no) VALUES (?, ?, ?)", 
                  (row["Learner's Name"], row["Grade"], str(row["Assessment Number"])))
        l_id = c.lastrowid
        
        # Save scores for each subject/area
        for area in areas:
            c.execute("INSERT INTO marks (learner_id, area, score) VALUES (?, ?, ?)", (l_id, area, row[area]))
            
    conn.commit()
    conn.close()

def delete_learner(assmt_no, grade_name):
    """Removes a learner and their associated marks."""
    conn = get_db_connection(grade_name)
    c = conn.cursor()
    c.execute("SELECT id FROM learners WHERE assmt_no = ?", (str(assmt_no),))
    result = c.fetchone()
    if result:
        l_id = result[0]
        c.execute("DELETE FROM marks WHERE learner_id = ?", (l_id,))
        c.execute("DELETE FROM learners WHERE id = ?", (l_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# ==========================================
# 2. PDF & GRADING ENGINE
# ==========================================

class CBC_Report_PDF(FPDF):
    def header(self):
        # Configure branding from session state
        logo = st.session_state.get('school_logo')
        school = st.session_state.get('school_name', 'TALITIA JUNIOR SCHOOL')
        motto = st.session_state.get('school_motto', 'HARD WORK AND PRAYER FOR SUCCESS')
        addr = st.session_state.get('school_address', 'P.O. Box 1439, TALITIA')
        term = st.session_state.get('term_info', 'Term 2, 2026')
        
        # Draw Logo and Watermark
        if logo:
            img = Image.open(logo)
            self.image(img, 10, 8, 22)
            # Watermark
            self.set_alpha(0.05) 
            self.image(img, 50, 110, 110)
            self.set_alpha(1)
            self.set_x(35)
            
        # School Details
        # Switched Arial to helvetica for better Linux compatibility
        self.set_font('helvetica', 'B', 15)
        self.cell(0, 10, school.upper(), 0, 1, 'L' if logo else 'C')
        self.set_font('helvetica', 'I', 8)
        if logo: self.set_x(35)
        self.cell(0, 5, motto, 0, 1, 'L' if logo else 'C')
        self.set_font('helvetica', '', 8)
        if logo: self.set_x(35)
        self.cell(0, 5, addr, 0, 1, 'L' if logo else 'C')
        
        # Header separation line
        self.ln(4)
        self.set_draw_color(0, 51, 102) # TALITIA JSS Deep Blue
        self.line(10, 36, 200, 36)
        
        # Report Title
        self.set_font('helvetica', 'B', 11)
        self.cell(0, 10, f"ACADEMIC ASSESSMENT REPORT: {term}", 0, 1, 'C')

def get_grading_logic(score):
    """Defines the CBC grading criteria."""
    if score >= 80: return "Exceeding Expectations", "Exceptional performance."
    if score >= 60: return "Meeting Expectations", "Good work, maintain pace."
    if score >= 40: return "Approaching Expectations", "Room for improvement."
    return "Below Expectations", "Urgent intervention required."

# ==========================================
# 3. LOGIN & SECURITY WRAPPER
# ==========================================

st.set_page_config(page_title="JSS Pro - Suite", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

def login_screen():
    st.markdown("### 🔐 System Access Control")
    
    # Check central config DB for password
    stored_pwd = get_system_password()
    user_pwd = st.text_input("Enter Admin Password", type="password")
    
    if st.button("Access Dashboard"):
        # The recovery key is 'admin', allowing a reset if the set password is lost.
        if user_pwd == stored_pwd or user_pwd == "admin":
            st.session_state.logged_in = True
            st.success("Access Granted!")
            st.rerun()
        else:
            st.error("Invalid Password. If forgotten, use the recovery master key.")

# ==========================================
# 4. MAIN APPLICATION
# ==========================================

if not st.session_state.logged_in:
    login_screen()
else:
    # Standard JSS Subjects for CBC
    subjects = ["Mathematics", "English", "Kiswahili", "Integrated Science", "Social Studies", 
                "Agriculture", "Pre-technical", "Religious Education", "Creative Arts & Sports"]

    # --- SIDEBAR CONFIGURATION ---
    with st.sidebar:
        st.markdown("### JSS Pro Suite")
        active_grade = st.selectbox("Active Grade Database", ["Grade 6", "Grade 7", "Grade 8", "Grade 9"])
        init_db(active_grade)
        
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

        st.divider()
        st.header("School Branding")
        st.session_state.school_logo = st.file_uploader("Logo", type=['png', 'jpg', 'jpeg'])
        st.session_state.school_name = st.text_input("School Name", "TALITIA JUNIOR SCHOOL")
        st.session_state.school_motto = st.text_input("Motto", "HARD WORK AND PRAYER FOR SUCCESS")
        st.session_state.school_address = st.text_area("Address", "P.O. Box 1439, TALITIA")
        
        st.header("🗓️ ACADEMIC DATES")
        st.session_state.term_info = st.text_input("Term", "Term 2, 2026")
        st.session_state.closing_date = st.text_input("Closing", "14th Aug 2026")
        st.session_state.opening_date = st.text_input("Opening", "7th Sept 2026")

        # ==========================================
        # RESTORED: ABOUT THIS SYSTEM (as seen in Image 4)
        # ==========================================
        st.divider()
        with st.expander("ℹ️ About This System", expanded=True):
            st.write("**System Developer**")
            st.write("Name: **Hassan web developers**")
            st.info("Email: hassanxaidi862@gmail.com\n\nPhone: +254794551087")

    # --- MAIN CONTENT AREA ---
    # Retrieve current grade data
    conn = get_db_connection(active_grade)
    query = 'SELECT l.name, l.grade, l.assmt_no, m.area, m.score FROM learners l JOIN marks m ON l.id = m.learner_id'
    raw_data = pd.read_sql(query, conn)
    conn.close()

    # Organized App Workflow
    t1, t2, t3, t4, t5, t6 = st.tabs(["DATA ENTRY", "MANAGER", "📊 ANALYTICS", "REPORTS", "CLEAN UP", "SETTINGS"])

    # Tab 1: Data Ingestion
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Bulk Excel Upload")
            up_file = st.file_uploader("Upload standard CBC spreadsheet", type=['xlsx', 'csv'])
            if up_file and st.button("Bulk Save to DB"):
                df_entry = pd.read_excel(up_file) if "xlsx" in up_file.name else pd.read_csv(up_file)
                save_to_db(df_entry, active_grade); st.success("Database Updated!"); st.rerun()
        with c2:
            st.subheader("Manual Score Entry")
            with st.form("manual_entry"):
                m_name = st.text_input("Learner Name"); m_no = st.text_input("Assessment Number")
                # Dynamic subject score fields
                m_marks = {sub: st.number_input(sub, 0.0, 100.0, 0.0) for sub in subjects}
                if st.form_submit_button("Save Entry"):
                    save_to_db(pd.DataFrame([{"Learner's Name": m_name, "Grade": active_grade, "Assessment Number": m_no, **m_marks}]), active_grade)
                    st.success("Entry Saved!"); st.rerun()

    # Tab 2: Data Manager
    with t2:
        if not raw_data.empty:
            # Pivot data to standard spreadsheet view
            pivot_view = raw_data.pivot_table(index=["name", "grade", "assmt_no"], columns="area", values="score").reset_index()
            st.dataframe(pivot_view, use_container_width=True)

    # Tab 3: Analytics
    with t3:
        if not raw_data.empty:
            st.subheader(f"Performance Overview: {active_grade}")
            # Calculate Mean scores for chart
            subject_averages = raw_data.groupby("area")["score"].mean().reset_index()
            # Plotly chart for professional view
            fig = px.bar(subject_averages, x="area", y="score", color="score", title=f"Subject Averages for {active_grade}")
            st.plotly_chart(fig, use_container_width=True)

    # Tab 4: Reports Generation
    with t4:
        if not raw_data.empty and st.button("Generate Reports for Whole Class"):
            # Prepare data
            clean_data = raw_data.drop_duplicates(subset=['assmt_no', 'area'])
            stats = clean_data.groupby(["name", "grade", "assmt_no"])['score'].mean().reset_index()
            # Calculate Rank
            stats['rank'] = stats['score'].rank(ascending=False, method='min').astype(int)
            total_students = len(stats) # Updated per your request to be out of xlsx file size
            
            # Initialize PDF bundle
            pdf_bundle = CBC_Report_PDF()
            for _, student in stats.iterrows():
                student_marks = clean_data[clean_data['assmt_no'] == student['assmt_no']]
                pdf_bundle.add_page()
                # Student Details Header
                pdf_bundle.set_fill_color(0, 51, 102); pdf_bundle.set_text_color(255, 255, 255); pdf_bundle.set_font('helvetica', 'B', 10)
                pdf_bundle.cell(95, 10, f" NAME: {student['name'].upper()}", 1, 0, 'L', True)
                pdf_bundle.cell(45, 10, f" GRADE: {student['grade']}", 1, 0, 'L', True)
                pdf_bundle.cell(50, 10, f" NO: {student['assmt_no']}", 1, 1, 'L', True)
                # Performance Table
                pdf_bundle.set_text_color(0,0,0); pdf_bundle.ln(4)
                # Table Header
                pdf_bundle.set_font('helvetica', 'B', 8)
                pdf_bundle.cell(60, 7, " LEARNING AREA", 1); pdf_bundle.cell(15, 7, "SCORE", 1, 0, 'C')
                pdf_bundle.cell(55, 7, " PERFORMANCE LEVEL", 1); pdf_bundle.cell(60, 7, " REMARKS", 1, 1)
                # Subject Rows
                for _, mark in student_marks.iterrows():
                    level, remark = get_grading_logic(mark['score'])
                    pdf_bundle.set_font('helvetica', '', 8)
                    pdf_bundle.cell(60, 7, f" {mark['area']}", 1)
                    pdf_bundle.cell(15, 7, str(int(mark['score'])), 1, 0, 'C')
                    pdf_bundle.cell(55, 7, f" {level}", 1)
                    pdf_bundle.cell(60, 7, f" {remark}", 1, 1)
                
                # Performance Summary and Restored Ranking logic
                pdf_bundle.ln(5); pdf_bundle.set_font('helvetica', 'B', 10)
                pdf_bundle.cell(0, 10, f"MEAN SCORE: {student['score']:.2f}%  |  RANK: {student['rank']} OUT OF {total_students}", 0, 1)
                
                # REMARKS & SIGNATURES section
                pdf_bundle.ln(8); pdf_bundle.set_font('helvetica', 'B', 9)
                pdf_bundle.cell(0, 6, "CLASS TEACHER'S REMARKS:", 0, 1)
                pdf_bundle.set_font('helvetica', '', 9); pdf_bundle.cell(0, 8, "." * 115, 0, 1) # Dotted line for remarks
                pdf_bundle.cell(100, 10, "Signature: .......................................", 0, 0)
                pdf_bundle.cell(0, 10, "Date: .........................", 0, 1)
                
                pdf_bundle.ln(4); pdf_bundle.set_font('helvetica', 'B', 9)
                pdf_bundle.cell(0, 6, "PRINCIPAL'S REMARKS:", 0, 1)
                pdf_bundle.set_font('helvetica', '', 9); pdf_bundle.cell(0, 8, "." * 115, 0, 1) # Dotted line for remarks
                pdf_bundle.cell(100, 10, "Signature & Stamp: ............................", 0, 0)
                pdf_bundle.cell(0, 10, "Date: .........................", 0, 1)

            st.download_button("Download Report Bundle", 
bytes(pdf_bundle.output(dest='S')),
f"CBC_Reports_{active_grade}_{st.session_state.term_info.replace(', ', '_')}.pdf")

    # Tab 5: Data Clean Up
    with t5:
        st.subheader("Manage Database integrity")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Delete Single Learner")
            delete_no = st.text_input("Enter Assessment No to delete")
            if st.button("Delete Learner"):
                if delete_learner(delete_no, active_grade):
                    st.success("Learner and associated marks deleted!")
                    st.rerun()
                else:
                    st.error("Learner not found.")
        with c2:
            st.markdown("#### Wipe Grade Database")
            st.warning(f"This will delete ALL data for {active_grade}. Operation cannot be undone.")
            if st.button(f"Yes, Wipe {active_grade}"):
                conn = get_db_connection(active_grade); c = conn.cursor()
                c.execute("DELETE FROM marks"); c.execute("DELETE FROM learners"); conn.commit(); conn.close()
                st.success(f"{active_grade} Database wiped clean."); st.rerun()

    # Tab 6: RESTORED & CORRECTED Security Settings (as seen in Image 5)
    with t6:
        st.markdown("### 🔐 Security Settings")
        
        current_password_view = get_system_password()
        
        # Display current password per image
        st.info(f"The current password is: **{current_password_view}**")
        
        st.divider()
        st.subheader("Update Admin Password")
        
        # RESTORED: Confirm New Password fields
        new_pwd_1 = st.text_input("Enter New System Password", type="password", key="new_p1")
        new_pwd_2 = st.text_input("Confirm New Password", type="password", key="new_p2")
        
        if st.button("Update Password", key="update_p_btn"):
            if new_pwd_1 == new_pwd_2:
                if new_pwd_1.strip() != "":
                    update_system_password(new_pwd_1)
                    st.success("System password updated successfully! Please note your new password.")
                else:
                    st.error("Password cannot be empty.")
            else:
                st.error("Passwords do not match. Please try again.")
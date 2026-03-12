import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

st.set_page_config(page_title="Rabine America", layout="wide")

# --- EMAIL ALERT ENGINE ---
def send_email_alert(client_name, client_email, location_count):
    """Silently sends an email notification to your inbox when a request is logged."""
    sender_email = st.secrets["email"]["sender_address"]
    sender_password = st.secrets["email"]["app_password"]
    recipient_email = st.secrets["email"]["receiver_address"]

    subject = f"New Pothole Request Logged - {client_name}"
    body = f"""
    A new pavement maintenance request has been submitted.
    
    Requested By: {client_name}
    Client Email: {client_email}
    Locations Submitted: {location_count}
    
    The backend pricing engine has automatically processed the regional multipliers and logged the Final Price Per SF for these locations in your Google Sheet.
    """

    msg = MIMEMultipart()
    msg['From'] = formataddr(("Rabine Bid Portal", sender_email)) 
    msg['To'] = recipient_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    # Connect to the email server 
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(sender_email, sender_password)
    server.send_message(msg)
    server.quit()


# --- DATABASE SETUP & PRICING ENGINE (Invisible to Client) ---
def setup_database():
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE tbl_Baseline_Tiers (Tier_ID INTEGER PRIMARY KEY, Scope_Name TEXT, Base_Price_Per_SF REAL)''')
    cursor.execute("INSERT INTO tbl_Baseline_Tiers VALUES (1, 'Cut & Patch (Price Per SF)', 28.50)")
    
    cursor.execute('''CREATE TABLE tbl_State_Labor (State_ID TEXT PRIMARY KEY, State_Name TEXT, Labor_CCI REAL, Has_Winter_Shutdown BOOLEAN)''')
    states_data = [('AL', 'Alabama', 0.85, 0), ('AK', 'Alaska', 1.30, 1), ('AZ', 'Arizona', 0.97, 0), ('AR', 'Arkansas', 0.83, 0), ('CA', 'California', 1.32, 0), ('CO', 'Colorado', 1.05, 1), ('CT', 'Connecticut', 1.25, 1), ('DE', 'Delaware', 1.08, 1), ('FL', 'Florida', 0.88, 0), ('GA', 'Georgia', 0.95, 0), ('HI', 'Hawaii', 1.45, 0), ('ID', 'Idaho', 0.96, 1), ('IL', 'Illinois', 1.18, 1), ('IN', 'Indiana', 1.01, 1), ('IA', 'Iowa', 0.98, 1), ('KS', 'Kansas', 0.94, 1), ('KY', 'Kentucky', 0.92, 1), ('LA', 'Louisiana', 0.87, 0), ('ME', 'Maine', 1.02, 1), ('MD', 'Maryland', 1.10, 1), ('MA', 'Massachusetts', 1.28, 1), ('MI', 'Michigan', 1.12, 1), ('MN', 'Minnesota', 1.15, 1), ('MS', 'Mississippi', 0.82, 0), ('MO', 'Missouri', 0.99, 1), ('MT', 'Montana', 0.95, 1), ('NE', 'Nebraska', 0.94, 1), ('NV', 'Nevada', 1.10, 0), ('NH', 'New Hampshire', 1.08, 1), ('NJ', 'New Jersey', 1.30, 1), ('NM', 'New Mexico', 0.93, 0), ('NY', 'New York', 1.35, 1), ('NC', 'North Carolina', 0.90, 0), ('ND', 'North Dakota', 0.96, 1), ('OH', 'Ohio', 1.02, 1), ('OK', 'Oklahoma', 0.88, 0), ('OR', 'Oregon', 1.15, 1), ('PA', 'Pennsylvania', 1.14, 1), ('RI', 'Rhode Island', 1.20, 1), ('SC', 'South Carolina', 0.85, 0), ('SD', 'South Dakota', 0.90, 1), ('TN', 'Tennessee', 0.89, 0), ('TX', 'Texas', 0.92, 0), ('UT', 'Utah', 0.98, 1), ('VT', 'Vermont', 1.03, 1), ('VA', 'Virginia', 1.01, 1), ('WA', 'Washington', 1.22, 1), ('WV', 'West Virginia', 0.91, 1), ('WI', 'Wisconsin', 1.11, 1), ('WY', 'Wyoming', 0.95, 1)]
    cursor.executemany("INSERT INTO tbl_State_Labor VALUES (?, ?, ?, ?)", states_data)
    
    cursor.execute('''CREATE TABLE tbl_Macro_Trend (Trend_ID INTEGER PRIMARY KEY, Year_Quarter TEXT, Oil_Freight_Multiplier REAL, Is_Active BOOLEAN)''')
    cursor.execute("INSERT INTO tbl_Macro_Trend VALUES (202601, 'Q1_2026', 1.08, 1)")
    cursor.execute('''CREATE TABLE tbl_Seasonal_Rules (Season_ID INTEGER PRIMARY KEY, Season_Name TEXT, Material_Multiplier REAL)''')
    cursor.executemany("INSERT INTO tbl_Seasonal_Rules VALUES (?, ?, ?)", [(1, 'Hot Mix Open', 1.00), (2, 'Winter/Plant Closed', 1.15)])
    
    cursor.execute('''CREATE TABLE tbl_State_Seasonality (Mapping_ID INTEGER PRIMARY KEY AUTOINCREMENT, State_ID TEXT, Month_Num INTEGER, Season_ID INTEGER)''')
    cursor.execute("SELECT State_ID, Has_Winter_Shutdown FROM tbl_State_Labor")
    for row in cursor.fetchall():
        for month in range(1, 13):
            season = 2 if (row[1] and month in [1, 2, 3, 4, 11, 12]) else 1
            cursor.execute("INSERT INTO tbl_State_Seasonality (State_ID, Month_Num, Season_ID) VALUES (?, ?, ?)", (row[0], month, season))
    conn.commit()
    return conn

def calculate_price_per_sf(conn, state_id, month_num):
    cursor = conn.cursor()
    cursor.execute('''SELECT b.Base_Price_Per_SF, l.Labor_CCI, m.Oil_Freight_Multiplier, r.Material_Multiplier FROM tbl_Baseline_Tiers b JOIN tbl_State_Labor l ON l.State_ID = ? JOIN tbl_State_Seasonality ss ON ss.State_ID = l.State_ID AND ss.Month_Num = ? JOIN tbl_Seasonal_Rules r ON r.Season_ID = ss.Season_ID CROSS JOIN tbl_Macro_Trend m WHERE m.Is_Active = 1 AND b.Tier_ID = 1''', (state_id, month_num))
    res = cursor.fetchone()
    return round(res[0] * res[1] * res[2] * res[3], 2) if res else None

# --- WEB INTERFACE (Client Facing) ---
st.title("🚧 Pothole Request")
st.markdown("Please fill out the form below to request pavement maintenance. A Rabine team member will review your submission shortly.")

st.subheader("Manager Contact Info")
col1, col2 = st.columns(2)
with col1:
    requested_by = st.text_input("Requested By:")
with col2:
    email = st.text_input("Email:")

st.subheader("Maintenance Locations")
st.markdown("Add your locations below. Click the **+** icon at the bottom of the table to add more rows.")

if 'locations_df' not in st.session_state:
    df = pd.DataFrame(columns=["Street", "City", "State", "Zip_Code", "Priority"])
    df.loc[1] = ["", "", "IL", "", "Moderate"]
    st.session_state.locations_df = df

state_list = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]

edited_df = st.data_editor(
    st.session_state.locations_df, num_rows="dynamic", use_container_width=True,
    column_config={"State": st.column_config.SelectboxColumn("State", options=state_list, required=True), "Priority": st.column_config.SelectboxColumn("Priority", options=["Moderate", "HIGH"], required=True, default="Moderate")}
)

# 3. Submission Engine
if st.button("Submit Request", type="primary"):
    if not requested_by or not email:
        st.error("Please fill out both the 'Requested By' and 'Email' fields.")
    elif edited_df["Street"].replace("", pd.NA).dropna().empty:
        st.error("Please provide at least one valid street address.")
    else:
        active_db = setup_database()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        valid_location_count = 0
        
        try:
            # 1. Authenticate with Google
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open_by_url(st.secrets["private_gsheet_url"]).sheet1
            
            # 2. Process Data
            for index, row in

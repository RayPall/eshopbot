import os
import streamlit as st
import requests

st.set_page_config(page_title="File → Webhook", layout="centered")

st.title("Upload files and forward to webhook")

# 1) Let user configure the webhook URL (or set via env var)
WEBHOOK_URL = st.text_input(
    "Webhook URL",
    value=os.getenv("WEBHOOK_URL", "https://hook.eu2.make.com/63hihe37jcpjcjjhqa0womzynff1ovqv"),
    help="The URL that will receive the uploaded files via POST."
)
if not WEBHOOK_URL:
    st.warning("Please enter a Webhook URL (or set the WEBHOOK_URL env var).")

# 2) File uploader (allow multiple)
uploaded_files = st.file_uploader(
    "Select files to send",
    type=None,  # allow any file type
    accept_multiple_files=True
)

# 3) Send button
if st.button("Send to webhook"):

    if not WEBHOOK_URL:
        st.error("Cannot send: webhook URL is missing.")
    elif not uploaded_files:
        st.error("No files selected.")
    else:
        with st.spinner("Uploading…"):
            # Prepare files dict for requests
            files = {}
            for idx, uploaded_file in enumerate(uploaded_files):
                # uploaded_file is a _io.BufferedReader-like with .name and .getvalue()
                files[f"file_{idx}"] = (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type or "application/octet-stream"
                )
            try:
                resp = requests.post(
                    WEBHOOK_URL,
                    files=files,
                    timeout=30
                )
                resp.raise_for_status()
            except Exception as e:
                st.error(f"Error sending files: {e}")
            else:
                st.success(f"Successfully sent {len(uploaded_files)} file(s) (Status {resp.status_code}).")
                # Optionally show webhook response
                if resp.text:
                    st.text_area("Webhook response", resp.text, height=200)

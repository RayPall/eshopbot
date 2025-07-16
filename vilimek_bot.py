import streamlit as st
import requests

st.title("📤 Forward to Make via Webhook")

# 1) Upload any files
files = st.file_uploader(
    "Vyberte soubory, které chcete poslat do Make",
    accept_multiple_files=True
)

if st.button("▶️ Odeslat do Make"):
    if not files:
        st.error("Nejdřív nahrajte alespoň jeden soubor.")
        st.stop()

    # 2) Prepare multipart data
    multipart = []
    for f in files:
        # each tuple: (field name, (filename, bytes, content_type))
        multipart.append(
            ("files", (f.name, f.getvalue(), f.type))
        )

    # add any additional JSON payload if needed
    payload = {
        "source": "streamlit_app",
        "note": "Files uploaded by user"
    }

    # 3) POST to your Make webhook
    webhook_url = "https://hook.eu2.make.com/63hihe37jcpjcjjhqa0womzynff1ovqv"
    try:
        resp = requests.post(
            webhook_url,
            files=multipart,
            data=payload,
            timeout=30
        )
        resp.raise_for_status()
    except Exception as e:
        st.error(f"Chyba při odesílání na Make: {e}")
    else:
        st.success(f"Soubory úspěšně odeslány! Make odpověděl: {resp.text}")

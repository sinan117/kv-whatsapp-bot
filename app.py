from flask import Flask, request, make_response
from twilio.twiml.messaging_response import MessagingResponse
import re

# --- Google Sheets Imports ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- Google Sheets Setup ---
scope = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
creds = ServiceAccountCredentials.from_json_keyfile_name("kv-idukki-bot-d3fc6b668abc.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key("1fKXE4T9L_Qv2_U_TuFkWi-90LlyttQu0jz72oiL7DRw").sheet1

app = Flask(__name__)
user_context = {}

def _normalize_sender(s):
    """Normalize sender strings by removing 'whatsapp:' prefix and trimming."""
    if not s:
        return ""
    return s.replace("whatsapp:", "").strip()

# ✅ FIXED count_entries() — uses normalized sender comparison and skips header
def count_entries(sender):
    sender_norm = _normalize_sender(sender)
    all_values = sheet.get_all_values()
    count = 0
    for row in all_values[1:]:  # skip header row
        if len(row) >= 4 and _normalize_sender(row[3]) == sender_norm:
            count += 1
    return count

def delete_entry_by_name(name, sender):
    """Delete the first matching entry where (name matches) AND (sender matches).
       Name matching is case-insensitive and strips whitespace.
       Sender matching uses normalized comparison to tolerate 'whatsapp:' prefix.
    """
    name_norm = name.strip().lower()
    sender_norm = _normalize_sender(sender)
    all_values = sheet.get_all_values()

    # iterate starting from 2 to avoid deleting header accidentally (row index is 1-based)
    for i, row in enumerate(all_values, start=1):
        # skip header row
        if i == 1:
            continue
        if len(row) >= 4:
            row_name = row[0].strip().lower()
            row_sender_norm = _normalize_sender(row[3])
            if row_name == name_norm and row_sender_norm == sender_norm:
                sheet.delete_row(i)
                return True
    return False

@app.route("/whatsapp", methods=["POST"])
def reply_whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    sender = request.form.get("From")
    print(f"📩 {sender}: {incoming_msg}")
    
    resp = MessagingResponse()
    lower_msg = incoming_msg.lower()

    def extract_class_number(text):
        matches = re.findall(r"\d+", text)
        if matches:
            return int(matches[0])
        return None

    reply = None
    image_url = None

    # --- DELETE ENTRY ---
    # Accept variants like "delete name", "delete: name", "del name"
    if lower_msg.startswith("delete ") or lower_msg.startswith("delete:") or lower_msg.startswith("del "):
        # Extract name robustly
        if lower_msg.startswith("delete:"):
            name_to_delete = incoming_msg.split(":", 1)[1].strip()
        else:
            # split on first space to preserve names with spaces
            parts = incoming_msg.split(" ", 1)
            name_to_delete = parts[1].strip() if len(parts) > 1 else ""
        if not name_to_delete:
            reply = "❌ Please provide the name to delete. Usage:\n👉 delete <name>"
            msg = resp.message(reply)
            return make_response(str(resp), 200, {"Content-Type": "application/xml"})

        deleted = delete_entry_by_name(name_to_delete, sender)
        if deleted:
            reply = f"✅ Entry for *{name_to_delete}* deleted successfully."
        else:
            reply = f"❌ No entry found for *{name_to_delete}* under your number."
        # respond immediately for delete command
        msg = resp.message()
        msg.body(reply)
        return make_response(str(resp), 200, {"Content-Type": "application/xml"})

    # Step 4: Admission - Ask phone number
    elif sender in user_context and user_context[sender]["step"] == "ask_phone":
        if not re.fullmatch(r"\d{10}", incoming_msg):
            reply = "⚠️ Please enter a valid *10-digit phone number* (digits only)."
        else:
            # Limit check BEFORE saving
            if count_entries(sender) >= 2:
                reply = "⚠️ You already submitted *2 entries*. Please delete one using:\n\n👉 delete <name>"
            else:
                user_context[sender]["phone"] = incoming_msg
                student_class = user_context[sender]["class"]
                student_name = user_context[sender]["name"]
                student_phone = user_context[sender]["phone"]

                reply = (
                    f"✅ Thank you, *{student_name}*! Your admission enquiry for *Class {student_class}* "
                    f"has been received.\n📱 Contact number: *{student_phone}*\n\n"
                    "📝 Please complete the admission form online:\n"
                    "👉 https://kvidukki.ac.in/admission\n\n"
                    "Our school team will contact you soon. 📞"
                )

                # SAVE to sheet: name, class, phone, sender
                sheet.append_row([student_name, student_class, student_phone, sender])

                user_context.pop(sender)

    # Step 3: Ask name
    elif sender in user_context and user_context[sender]["step"] == "ask_name":
        if not re.fullmatch(r"[A-Za-z ]+", incoming_msg):
            reply = "⚠️ Please enter your name using *alphabets only* (e.g., John Doe)."
        else:
            user_context[sender]["name"] = incoming_msg
            user_context[sender]["step"] = "ask_phone"
            reply = "📞 Please provide your *contact number* (10 digits)."

    # Step 2: Ask class
    elif sender in user_context and user_context[sender]["step"] == "ask_class":
        if not re.fullmatch(r"\d{1,2}", incoming_msg) or not (1 <= int(incoming_msg) <= 12):
            reply = "⚠️ Please enter your class as a number between *1 and 12* (e.g., 5)."
        else:
            user_context[sender]["class"] = incoming_msg
            user_context[sender]["step"] = "ask_name"
            reply = "👤 Great! Please tell me the *student's full name*."

    # Step 1: Admission start (WITH LIMIT CHECK)
    elif "admission" in lower_msg or lower_msg == "1":

        # LIMIT CHECK BEFORE STARTING ADMISSION
        if count_entries(sender) >= 2:
            reply = "⚠️ You already submitted *2 entries*. Please delete one using:\n\n👉 delete <name>"
            msg = resp.message(reply)
            return make_response(str(resp), 200, {"Content-Type": "application/xml"})

        reply = "📚 Admissions for 2025 are open!\nPlease tell me which *class* you are seeking admission for?"
        user_context[sender] = {"step": "ask_class"}

    # START MENU (hi/hello)
    elif "hi" in lower_msg or "hello" in lower_msg:
        reply = (
            "👋 Hello! Welcome to *KV Idukki School*.\n\n"
            "Please choose an option below:\n"
            "1️⃣ Admission Info\n"
            "2️⃣ Fee Details\n"
            "3️⃣ Contact Info\n\n"
            "👉 Type the *number* or *word* (e.g., 1 or Admission)."
        )
        image_url = "https://raw.githubusercontent.com/sinan117/kv-gupshup-bot/main/welcome.jpg"

    # Fee inquiry - Step 1
    elif "fee" in lower_msg or lower_msg == "2":
        reply = "💰 Please enter the *class number* (e.g., 1, 5, 10) to get the fee details."
        user_context[sender] = {"step": "ask_fee_class"}

    # Fee inquiry - Step 2
    elif sender in user_context and user_context[sender].get("step") == "ask_fee_class":
        cls = extract_class_number(incoming_msg)
        if cls and 1 <= cls <= 12:
            user_context[sender]["class"] = cls
            user_context[sender]["step"] = "ask_fee_category"
            reply = (
                "👩‍🎓 Please specify the *category*:\n"
                "1️⃣ General\n2️⃣ SC/ST/OBC\n3️⃣ Single Girl Child\n\n"
                "👉 Type 1, 2, or 3."
            )
        else:
            reply = "⚠️ Please enter a valid class number between 1 and 12."

    # Fee inquiry - Step 3
    elif sender in user_context and user_context[sender].get("step") == "ask_fee_category":
        cls = user_context[sender]["class"]
        if 1 <= cls <= 3:
            fees = {"general": 500, "sc/st/obc": 300, "single girl child": 350}
        elif 4 <= cls <= 7:
            fees = {"general": 800, "sc/st/obc": 600, "single girl child": 650}
        elif 8 <= cls <= 12:
            fees = {"general": 1100, "sc/st/obc": 800, "single girl child": 950}
        else:
            fees = None

        if "1" in lower_msg or "general" in lower_msg:
            category = "General"
            fee = fees["general"]
        elif "2" in lower_msg or "sc" in lower_msg or "st" in lower_msg or "obc" in lower_msg:
            category = "SC/ST/OBC"
            fee = fees["sc/st/obc"]
        elif "3" in lower_msg or "girl" in lower_msg:
            category = "Single Girl Child"
            fee = fees["single girl child"]
        else:
            msg = resp.message("⚠️ Please type 1, 2, or 3 to select a valid category.")
            return make_response(str(resp), 200, {"Content-Type": "application/xml"})

        reply = f"🏫 Fee for *Class {cls}* ({category} category) is *₹{fee}* per term."
        user_context.pop(sender)

    # Contact info
    elif lower_msg in ["3", "contact", "phone", "info"]:
        reply = "*🌐 Website*: https://painavu.kvs.ac.in\n*📧 Email*: kvidukki@yahoo.in\n*📞 Phone*: 04862-232205"

    elif "bye" in lower_msg:
        reply = "Goodbye! 👋 Have a great day!"

    else:
        reply = "❓ Sorry, I didn’t understand that. Please choose 1️⃣ Admission 2️⃣ Fees 3️⃣ Contact"

    msg = resp.message()
    msg.body(reply)
    if image_url:
        msg.media(image_url)

    return make_response(str(resp), 200, {"Content-Type": "application/xml"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

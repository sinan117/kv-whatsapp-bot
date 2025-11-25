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

# ---------- UTILITIES ----------
def normalize_sender(s):
    """Normalize sender strings so 'whatsapp:+911234...' and '+911234...' match."""
    if not s:
        return ""
    s = str(s).strip()
    # remove whatsapp: prefix if present
    s = re.sub(r"^whatsapp:", "", s, flags=re.IGNORECASE)
    # remove spaces
    s = s.replace(" ", "")
    return s

def find_header_indexes():
    """
    Return (name_col, sender_col) as 0-based indexes.
    Tries to find headers 'name' and 'whatsapp sender' (case-insensitive).
    Falls back to defaults: name -> 0, sender -> 3.
    """
    all_values = sheet.get_all_values()
    if not all_values:
        return 0, 3
    headers = [h.strip().lower() for h in all_values[0]]
    # attempt to find 'name' and 'whatsapp sender'
    try:
        name_col = headers.index("name")
    except ValueError:
        # try alternative common headers
        for alt in ("full name", "student name"):
            if alt in headers:
                name_col = headers.index(alt)
                break
        else:
            name_col = 0

    try:
        sender_col = headers.index("whatsapp sender")
    except ValueError:
        for alt in ("sender", "from", "whatsapp_from", "whatsappfrom"):
            if alt in headers:
                sender_col = headers.index(alt)
                break
        else:
            sender_col = 3

    return name_col, sender_col

# ---------- COUNT FUNCTION (uses header detection + normalization) ----------
def count_entries(sender):
    sender_norm = normalize_sender(sender)
    all_values = sheet.get_all_values()
    if not all_values:
        return 0
    name_col, sender_col = find_header_indexes()
    count = 0
    # iterate over data rows (skip header)
    for row in all_values[1:]:
        if len(row) > sender_col:
            row_sender_norm = normalize_sender(row[sender_col])
            if row_sender_norm == sender_norm:
                count += 1
    print(f"DEBUG count_entries: sender_norm={sender_norm} -> count={count}")
    return count

# ---------- DELETE FUNCTION (robust + debug) ----------
def delete_entry_by_name(name, sender):
    """
    Delete rows where name (case-insensitive) AND sender match.
    Returns True if deleted at least one row, otherwise False.
    """
    if not name:
        return False

    name_norm = name.strip().lower()
    sender_norm = normalize_sender(sender)

    all_values = sheet.get_all_values()
    if not all_values or len(all_values) == 1:
        print("DEBUG delete: sheet empty or only header")
        return False

    name_col, sender_col = find_header_indexes()
    print(f"DEBUG delete: name_col={name_col}, sender_col={sender_col}, name_norm='{name_norm}', sender_norm='{sender_norm}'")

    # iterate from bottom to top so row deletes don't shift remaining rows
    deleted_any = False
    for idx in range(len(all_values) - 1, 0, -1):  # data rows indices in all_values
        row = all_values[idx]
        # ensure row has enough columns
        if len(row) <= max(name_col, sender_col):
            continue
        row_name = row[name_col].strip().lower()
        row_sender_norm = normalize_sender(row[sender_col])
        print(f"DEBUG checking row {idx+1}: row_name='{row_name}', row_sender='{row_sender_norm}'")
        if row_name == name_norm and row_sender_norm == sender_norm:
            # sheet.delete_row expects 1-based index
            sheet.delete_row(idx + 1)
            print(f"DEBUG deleted row {idx+1} matching name='{name}' and sender='{sender}'")
            deleted_any = True
            # continue to delete all matching rows for safety

    return deleted_any

# ---------- ROUTE ----------
@app.route("/whatsapp", methods=["POST"])
def reply_whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    sender = request.form.get("From")
    print(f"📩 {sender}: {incoming_msg}")

    resp = MessagingResponse()
    lower_msg = incoming_msg.lower()

    reply = None
    image_url = None

    # ---------- DELETE TRIGGER (accept many formats) ----------
    # Matches: delete name, delete: name, del name, remove name (case-insensitive)
    delete_match = re.match(r"^(?:delete|del|remove)[:\s\-]*\s*(.+)$", incoming_msg, re.IGNORECASE)
    if delete_match:
        name_to_delete = delete_match.group(1).strip()
        print(f"DEBUG received delete request: raw='{incoming_msg}', parsed_name='{name_to_delete}', sender='{sender}'")
        if not name_to_delete:
            reply = "❌ Please provide the name to delete.\n👉 delete <name>"
        else:
            deleted = delete_entry_by_name(name_to_delete, sender)
            if deleted:
                reply = f"✅ Entry for *{name_to_delete}* deleted successfully."
            else:
                reply = f"❌ No entry found for *{name_to_delete}* under your number."
        msg = resp.message()
        msg.body(reply)
        return make_response(str(resp), 200, {"Content-Type": "application/xml"})

    # ---------- LIMIT CHECK BEFORE STARTING ADMISSION FLOW ----------
    # If user attempts admission (word or "1") we block if they already have 2 entries
    if (lower_msg == "1" or "admission" in lower_msg) and "fee" not in lower_msg:
        if count_entries(sender) >= 2:
            msg = resp.message(
                "⚠️ You already submitted *2 entries*. Please delete one using:\n\n👉 delete <name>"
            )
            return make_response(str(resp), 200, {"Content-Type": "application/xml"})
        # allow flow to continue and set step
        reply = "📚 Admissions for 2025 are open!\nPlease tell me which *class* you are seeking admission for?"
        user_context[sender] = {"step": "ask_class"}
        msg = resp.message(reply)
        return make_response(str(resp), 200, {"Content-Type": "application/xml"})

    # ---------- HELPERS ----------
    def extract_class_number(text):
        matches = re.findall(r"\d+", text)
        return int(matches[0]) if matches else None

    # ---------- ADMISSION PHONE STEP ----------
    if sender in user_context and user_context[sender].get("step") == "ask_phone":
        if not re.fullmatch(r"\d{10}", incoming_msg):
            reply = "⚠️ Please enter a valid *10-digit phone number* (digits only)."
        else:
            # Limit check before saving
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

                sheet.append_row([student_name, student_class, student_phone, sender])
                user_context.pop(sender)

    # ---------- ADMISSION NAME STEP ----------
    elif sender in user_context and user_context[sender].get("step") == "ask_name":
        if not re.fullmatch(r"[A-Za-z ]+", incoming_msg):
            reply = "⚠️ Please enter your name using *alphabets only* (e.g., John Doe)."
        else:
            user_context[sender]["name"] = incoming_msg
            user_context[sender]["step"] = "ask_phone"
            reply = "📞 Please provide your *contact number* (10 digits)."

    # ---------- ADMISSION CLASS STEP ----------
    elif sender in user_context and user_context[sender].get("step") == "ask_class":
        if not re.fullmatch(r"\d{1,2}", incoming_msg) or not (1 <= int(incoming_msg) <= 12):
            reply = "⚠️ Please enter your class as a number between *1 and 12* (e.g., 5)."
        else:
            user_context[sender]["class"] = incoming_msg
            user_context[sender]["step"] = "ask_name"
            reply = "👤 Great! Please tell me the *student's full name*."

    # ---------- START MENU ----------
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

    # ---------- FEES STEP 1 ----------
    elif "fee" in lower_msg or lower_msg == "2":
        reply = "💰 Please enter the *class number* (e.g., 1, 5, 10) to get the fee details."
        user_context[sender] = {"step": "ask_fee_class"}

    # ---------- FEES STEP 2 ----------
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

    # ---------- FEES STEP 3 ----------
    elif sender in user_context and user_context[sender].get("step") == "ask_fee_category":
        cls = user_context[sender]["class"]

        if 1 <= cls <= 3:
            fees = {"general": 500, "sc/st/obc": 300, "single girl child": 350}
        elif 4 <= cls <= 7:
            fees = {"general": 800, "sc/st/obc": 600, "single girl child": 650}
        elif 8 <= cls <= 12:
            fees = {"general": 1100, "sc/st/obc": 800, "single girl child": 950}

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

    # ---------- CONTACT INFO ----------
    elif lower_msg in ["3", "contact", "phone", "info"]:
        reply = "*🌐 Website*: https://painavu.kvs.ac.in\n*📧 Email*: kvidukki@yahoo.in\n*📞 Phone*: 04862-232205"

    # ---------- GOODBYE ----------
    elif "bye" in lower_msg:
        reply = "Goodbye! 👋 Have a great day!"

    # ---------- FALLBACK ----------
    else:
        reply = "❓ Sorry, I didn’t understand that. Please choose 1️⃣ Admission 2️⃣ Fees 3️⃣ Contact"

    # ---------- SEND RESPONSE ----------
    msg = resp.message()
    msg.body(reply)
    if 'image_url' in locals() and image_url:
        msg.media(image_url)

    return make_response(str(resp), 200, {"Content-Type": "application/xml"})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

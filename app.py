from flask import Flask, request, make_response
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

user_context = {}

@app.route("/whatsapp", methods=["POST"])
def reply_whatsapp():
    incoming_msg = request.form.get("Body").strip()
    sender = request.form.get("From")
    print(f"📩 {sender}: {incoming_msg}")

    resp = MessagingResponse()
    msg = resp.message()
    lower_msg = incoming_msg.lower()

    def extract_class_number(text):
        import re
        matches = re.findall(r"\d+", text)
        if matches:
            return int(matches[0])
        return None

    # ---- Step 4: Admission - Ask phone number ----
    if sender in user_context and user_context[sender]["step"] == "ask_phone":
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
        user_context.pop(sender)

    # ---- Step 3: Admission - Ask name ----
    elif sender in user_context and user_context[sender]["step"] == "ask_name":
        user_context[sender]["name"] = incoming_msg
        user_context[sender]["step"] = "ask_phone"
        reply = "📞 Please provide your *contact number* (10 digits)."

    # ---- Step 2: Admission - Ask class ----
    elif sender in user_context and user_context[sender]["step"] == "ask_class":
        user_context[sender]["class"] = incoming_msg
        user_context[sender]["step"] = "ask_name"
        reply = "👤 Great! Please tell me the *student's full name*."

    # ---- Step 1: Admission start ----
    elif "admission" in lower_msg or lower_msg == "1":
        reply = "📚 Admissions for 2025 are open!\nPlease tell me which *class* you are seeking admission for?"
        user_context[sender] = {"step": "ask_class"}

    # ---- Start Menu ----
    elif "hi" in lower_msg or "hello" in lower_msg:
        reply = (
            "👋 Hello! Welcome to *KV Idukki School*.\n\n"
            "Please choose an option below:\n"
            "1️⃣ Admission Info\n"
            "2️⃣ Fee Details\n"
            "3️⃣ Contact Info\n\n"
            "👉 Type the *number* or *word* (e.g., 1 or Admission)."
        )

    # ---- Step F1: Fee inquiry - Ask class ----
    elif "fee" in lower_msg or lower_msg == "2":
        reply = "💰 Please enter the *class number* (e.g., 1, 5, 10) to get the fee details."
        user_context[sender] = {"step": "ask_fee_class"}

    # ---- Step F2: Fee inquiry - After class entered ----
    elif sender in user_context and user_context[sender].get("step") == "ask_fee_class":
        cls = extract_class_number(incoming_msg)
        if cls and 1 <= cls <= 12:
            user_context[sender]["class"] = cls
            user_context[sender]["step"] = "ask_fee_category"
            reply = (
                "👩‍🎓 Please specify the *category*:\n"
                "1️⃣ General\n"
                "2️⃣ SC/ST/OBC\n"
                "3️⃣ Single Girl Child\n\n"
                "👉 Type 1, 2, or 3."
            )
        else:
            reply = "⚠️ Please enter a valid class number between 1 and 12."

    # ---- Step F3: Fee inquiry - After category entered ----
    elif sender in user_context and user_context[sender].get("step") == "ask_fee_category":
        cls = user_context[sender]["class"]

        # Determine fee based on class range
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
            reply = "⚠️ Please type 1, 2, or 3 to select a valid category."
            msg.body(reply)
            return make_response(str(resp), 200, {"Content-Type": "application/xml"})

        reply = f"🏫 Fee for *Class {cls}* ({category} category) is *₹{fee}* per term."
        user_context.pop(sender)

    # ---- Contact info ----
    elif lower_msg in ["3", "contact", "phone", "info"]:
        reply = "📞 You can reach us at +91-9446XXXXXX or email kv.idukki@kvs.gov.in"

    elif "bye" in lower_msg:
        reply = "Goodbye! 👋 Have a great day!"

    else:
        reply = (
            "❓ Sorry, I didn’t understand that.\n"
            "Please choose one of these:\n"
            "1️⃣ Admission  2️⃣ Fees  3️⃣ Contact"
        )

    msg.body(reply)
    return make_response(str(resp), 200, {"Content-Type": "application/xml"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



from flask import Flask, request, make_response
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import re

app = Flask(__name__)

# Initialize OpenAI safely using environment variable
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

user_context = {}

@app.route("/whatsapp", methods=["POST"])
def reply_whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    sender = request.form.get("From")
    print(f"📩 {sender}: {incoming_msg}")

    resp = MessagingResponse()
    lower_msg = incoming_msg.lower()

    def extract_class_number(text):
        matches = re.findall(r"\d+", text)
        return int(matches[0]) if matches else None

    reply = None

    # Step 4: Ask phone number
    if sender in user_context and user_context[sender]["step"] == "ask_phone":
        if not re.fullmatch(r"\d{10}", incoming_msg):
            reply = "⚠️ Please enter a valid *10-digit phone number*."
        else:
            user_context[sender]["phone"] = incoming_msg
            cls = user_context[sender]["class"]
            name = user_context[sender]["name"]
            phone = user_context[sender]["phone"]
            reply = (
                f"✅ Thank you, *{name}*! Your admission enquiry for *Class {cls}* "
                f"has been received.\n📱 Contact: *{phone}*\n\n"
                "📝 Please complete the admission form:\n"
                "👉 https://kvidukki.ac.in/admission\n\n"
                "Our team will contact you soon. 📞"
            )
            user_context.pop(sender)

    # Step 3: Ask name
    elif sender in user_context and user_context[sender]["step"] == "ask_name":
        if not re.fullmatch(r"[A-Za-z ]+", incoming_msg):
            reply = "⚠️ Please enter your name using alphabets only (e.g., John Doe)."
        else:
            user_context[sender]["name"] = incoming_msg
            user_context[sender]["step"] = "ask_phone"
            reply = "📞 Please provide your contact number (10 digits)."

    # Step 2: Ask class
    elif sender in user_context and user_context[sender]["step"] == "ask_class":
        if not re.fullmatch(r"\d{1,2}", incoming_msg) or not (1 <= int(incoming_msg) <= 12):
            reply = "⚠️ Please enter class as a number between 1 and 12."
        else:
            user_context[sender]["class"] = incoming_msg
            user_context[sender]["step"] = "ask_name"
            reply = "👤 Great! Please tell me the student's full name."

    # Step 1: Admission start
    elif "admission" in lower_msg or lower_msg == "1":
        reply = "📚 Admissions 2025 are open!\nPlease tell me which *class* you are seeking admission for?"
        user_context[sender] = {"step": "ask_class"}

    # Menu
    elif "hi" in lower_msg or "hello" in lower_msg:
        reply = (
            "👋 Hello! Welcome to *KV Idukki School*.\n\n"
            "Please choose an option:\n"
            "1️⃣ Admission Info\n"
            "2️⃣ Fee Details\n"
            "3️⃣ Contact Info\n\n"
            "👉 Type 1, 2, or 3 to continue."
        )

    # Fee inquiry - class
    elif "fee" in lower_msg or lower_msg == "2":
        reply = "💰 Please enter the *class number* (e.g., 1, 5, 10) to get the fee details."
        user_context[sender] = {"step": "ask_fee_class"}

    elif sender in user_context and user_context[sender].get("step") == "ask_fee_class":
        cls = extract_class_number(incoming_msg)
        if cls and 1 <= cls <= 12:
            user_context[sender]["class"] = cls
            user_context[sender]["step"] = "ask_fee_category"
            reply = (
                "👩‍🎓 Please specify the *category*:\n"
                "1️⃣ General\n2️⃣ SC/ST/OBC\n3️⃣ Single Girl Child\n"
                "👉 Type 1, 2, or 3."
            )
        else:
            reply = "⚠️ Please enter a valid class number between 1 and 12."

    elif sender in user_context and user_context[sender].get("step") == "ask_fee_category":
        cls = user_context[sender]["class"]
        if 1 <= cls <= 3:
            fees = {"general": 500, "sc/st/obc": 300, "single girl child": 350}
        elif 4 <= cls <= 7:
            fees = {"general": 800, "sc/st/obc": 600, "single girl child": 650}
        elif 8 <= cls <= 12:
            fees = {"general": 1100, "sc/st/obc": 800, "single girl child": 950}
        else:
            fees = {}

        if "1" in lower_msg or "general" in lower_msg:
            reply = f"🏫 Fee for *Class {cls}* (General) is ₹{fees['general']} per term."
        elif "2" in lower_msg or "sc" in lower_msg or "st" in lower_msg or "obc" in lower_msg:
            reply = f"🏫 Fee for *Class {cls}* (SC/ST/OBC) is ₹{fees['sc/st/obc']} per term."
        elif "3" in lower_msg or "girl" in lower_msg:
            reply = f"🏫 Fee for *Class {cls}* (Single Girl Child) is ₹{fees['single girl child']} per term."
        else:
            reply = "⚠️ Please type 1, 2, or 3 to select a valid category."
        user_context.pop(sender, None)

    # Contact info
    elif lower_msg in ["3", "contact", "phone", "info"]:
        reply = "*🌐 Website*: https://painavu.kvs.ac.in\n📧 *Email*: kvidukki@yahoo.in\n📞 *Phone*: 04862-232205"

    elif "bye" in lower_msg:
        reply = "👋 Goodbye! Have a great day!"

    # 🧠 AI fallback
    else:
        try:
            ai_response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a friendly school assistant for KV Idukki."},
                    {"role": "user", "content": incoming_msg},
                ],
            )
            reply = ai_response.choices[0].message.content.strip()
        except Exception as e:
            print("❌ AI Error:", e)
            reply = "⚠️ Sorry, I'm having trouble responding right now."

    msg = resp.message(reply)
    return make_response(str(resp), 200, {"Content-Type": "application/xml"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

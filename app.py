"""
app.py — Prism: Inbox Intelligence
Run: python app.py → http://127.0.0.1:7860
"""

import json
import os
import gradio as gr
from src.drafting import draft_reply
from src.memory_store import initialize_db, get_sender_pattern, confirm_batch_results

CHECKPOINT_PATH = "data/triage_results_checkpoint.json"
EMAILS_PATH = "data/sample_emails.json"
DB_PATH = "data/memory.db"

CATEGORY_ORDER = ["time-sensitive", "actionable", "informational", "noise"]

CATEGORY_COLORS = {
    "time-sensitive": "#E8453C",
    "actionable":     "#1A7F5A",
    "informational":  "#2B6CB0",
    "noise":          "#9B9EAD",
}

CATEGORY_BG = {
    "time-sensitive": "#FEF2F2",
    "actionable":     "#F0FDF4",
    "informational":  "#EFF6FF",
    "noise":          "#F8F9FF",
}

CATEGORY_ICONS = {
    "time-sensitive": "⏰",
    "actionable":     "✅",
    "informational":  "ℹ️",
    "noise":          "🔇",
}

CATEGORY_LABELS = {
    "time-sensitive": "Time-sensitive",
    "actionable":     "Actionable",
    "informational":  "Informational",
    "noise":          "Noise",
}


def load_data():
    if not os.path.exists(CHECKPOINT_PATH):
        return {}, {}
    with open(CHECKPOINT_PATH) as f:
        all_results = json.load(f)
    results = {r["email_id"]: r for r in all_results if not r.get("mock", False)}
    if not os.path.exists(EMAILS_PATH):
        return results, {}
    with open(EMAILS_PATH) as f:
        emails = {e["id"]: e for e in json.load(f)}
    return results, emails


def get_counts(results):
    counts = {c: 0 for c in CATEGORY_ORDER}
    for r in results.values():
        cat = r.get("category", "noise")
        if cat in counts:
            counts[cat] += 1
    return counts


def build_inbox_html(results, emails, active_cat, search_query=""):
    counts = get_counts(results)
    total = len(results)

    # Sidebar
    sidebar_items = ""
    for cat in CATEGORY_ORDER:
        color = CATEGORY_COLORS[cat]
        active = cat == active_cat
        border = f"border-right:3px solid {color};" if active else "border-right:3px solid transparent;"
        bg = "background:#F2F3FA;" if active else ""
        sidebar_items += f"""
        <div style="padding:9px 16px;display:flex;align-items:center;justify-content:space-between;{bg}{border}cursor:pointer;">
            <div style="display:flex;align-items:center;gap:8px;">
                <div style="width:8px;height:8px;border-radius:50%;background:{color};flex-shrink:0;"></div>
                <span style="font-size:13px;color:#3B3E4F;">{CATEGORY_LABELS[cat]}</span>
            </div>
            <span style="font-size:12px;font-weight:600;color:{color};">{counts[cat]}</span>
        </div>"""

    sidebar = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding-top:4px;">
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#C4C7D4;padding:0 16px;margin-bottom:8px;">Categories</div>
        {sidebar_items}
        <div style="height:0.5px;background:#E2E5F0;margin:12px 16px;"></div>
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#C4C7D4;padding:0 16px;margin-bottom:6px;">Memory</div>
        <div style="padding:6px 16px;font-size:12px;color:#9B9EAD;">{total} emails triaged</div>
    </div>"""

    # Email list
    group = [r for r in results.values() if r.get("category") == active_cat]

    if search_query.strip():
        q = search_query.strip().lower()
        group = [r for r in group if q in r.get("from", "").lower() or q in r.get("subject", "").lower()]

    color = CATEGORY_COLORS[active_cat]
    bg = CATEGORY_BG[active_cat]
    icon = CATEGORY_ICONS[active_cat]
    label = CATEGORY_LABELS[active_cat]

    if not group:
        cards = '<div style="padding:40px;text-align:center;color:#9B9EAD;font-size:14px;">No emails found.</div>'
    else:
        cards = ""
        for r in group:
            email = emails.get(r["email_id"], {})
            subject = r.get("subject", "")
            sender = r.get("from", "")
            reasoning = r.get("reasoning", "")[:150]
            body_preview = email.get("body", "")[:110]
            parse_flag = " ⚠" if r.get("parse_error") else ""
            conf = r.get("confidence", "high")
            conf_note = f' · <span style="color:#B45309;">{conf} confidence</span>' if conf in ("low","medium") else ""

            cards += f"""
            <div style="background:#FFFFFF;border-radius:10px;border:0.5px solid #E2E5F0;padding:16px 18px;display:flex;align-items:flex-start;gap:14px;margin-bottom:10px;">
                <div style="width:3px;border-radius:2px;background:{color};align-self:stretch;min-height:60px;flex-shrink:0;"></div>
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:5px;">
                        <div style="font-size:15px;font-weight:600;color:#0A0A0F;">{subject}{parse_flag}</div>
                        <div style="background:{bg};color:{color};border-radius:5px;padding:3px 10px;font-size:11px;font-weight:700;white-space:nowrap;flex-shrink:0;">{icon} {label.upper()}</div>
                    </div>
                    <div style="font-size:12px;color:#9B9EAD;margin-bottom:10px;">{sender}{conf_note}</div>
                    <div style="font-size:12px;color:#6B6F7E;background:#F8F9FF;border-radius:6px;padding:10px 12px;margin-bottom:8px;line-height:1.5;border:0.5px solid #E2E5F0;">
                        <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#C4C7D4;margin-bottom:4px;">Email preview</div>
                        {body_preview}...
                    </div>
                    <div style="font-size:12px;color:#5B5F72;line-height:1.6;font-style:italic;font-family:Georgia,serif;border-left:2px solid {color};padding-left:10px;">
                        <div style="font-size:10px;font-style:normal;font-family:-apple-system,sans-serif;text-transform:uppercase;letter-spacing:0.5px;color:{color};margin-bottom:3px;">🤖 AI reasoning</div>
                        "{reasoning}..."
                    </div>
                </div>
            </div>"""

    email_list = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:4px 0;">
        <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:14px;">
            <div style="font-size:16px;font-weight:700;color:#0A0A0F;">{label}</div>
            <div style="font-size:12px;color:#9B9EAD;">{len(group)} emails</div>
        </div>
        {cards}
    </div>"""

    return sidebar, email_list


def get_email_choices(active_cat, search_query=""):
    results, _ = load_data()
    group = [r for r in results.values() if r.get("category") == active_cat]
    if search_query.strip():
        q = search_query.strip().lower()
        group = [r for r in group if q in r.get("from","").lower() or q in r.get("subject","").lower()]
    return [f"{r.get('subject','')[:55]} — {r.get('from','')}" for r in group]


def refresh_inbox(active_cat, search_query=""):
    results, emails = load_data()
    if not results:
        empty = '<div style="padding:40px;text-align:center;color:#9B9EAD;font-size:14px;">No triage results.<br><br>Run: <code>python -m src.triage --grouped --full</code></div>'
        return empty, empty, gr.update(choices=[])
    sidebar, email_list = build_inbox_html(results, emails, active_cat, search_query)
    choices = get_email_choices(active_cat, search_query)
    return sidebar, email_list, gr.update(choices=choices, value=None)


def switch_category(cat, search_query=""):
    return refresh_inbox(cat, search_query)


def view_email(choice, active_cat):
    if not choice:
        return "", gr.update(visible=False)
    results, emails = load_data()
    group = [r for r in results.values() if r.get("category") == active_cat]
    result = next((r for r in group if f"{r.get('subject','')[:55]} — {r.get('from','')}" == choice), None)
    if not result:
        return "", gr.update(visible=False)
    email = emails.get(result["email_id"], {})
    initialize_db(DB_PATH)
    memory = get_sender_pattern(email.get("from", ""), DB_PATH)

    cat = result.get("category", "noise")
    color = CATEGORY_COLORS[cat]
    bg = CATEGORY_BG[cat]
    icon = CATEGORY_ICONS[cat]
    label = CATEGORY_LABELS[cat]

    memory_html = ""
    if memory.get("known"):
        memory_html = f"""
        <div style="background:#F5F3FF;border-radius:8px;padding:12px 14px;margin-top:14px;border-left:3px solid #7C3AED;">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#7C3AED;margin-bottom:4px;">🧠 Sender memory</div>
            <div style="font-size:13px;color:#3B3E4F;"><strong>{email.get('from','')}</strong> is {memory['pattern']} <span style="color:#9B9EAD;">— {memory['sample_size']} past emails</span></div>
        </div>"""

    parse_html = ""
    if result.get("parse_error"):
        parse_html = '<div style="background:#FEF2F2;border:0.5px solid #E8453C;border-radius:8px;padding:12px;margin-top:12px;color:#E8453C;font-size:13px;">⚠️ Flagged for manual review — AI response was incomplete.</div>'

    detail = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
            <div style="background:{bg};color:{color};border-radius:6px;padding:4px 12px;font-size:11px;font-weight:700;text-transform:uppercase;">{icon} {label}</div>
            <div style="font-size:12px;color:#9B9EAD;">Confidence: {result.get('confidence','high')}</div>
        </div>
        <div style="font-size:20px;font-weight:700;color:#0A0A0F;margin-bottom:4px;">{result.get('subject','')}</div>
        <div style="font-size:13px;color:#9B9EAD;margin-bottom:18px;">From: {email.get('from','')} · {email.get('date','')[:10]}</div>
        <div style="background:#F8F9FF;border-radius:8px;padding:16px;font-family:'Courier New',monospace;font-size:13px;color:#3B3E4F;line-height:1.7;white-space:pre-wrap;border:0.5px solid #E2E5F0;margin-bottom:14px;">
            <div style="font-family:-apple-system,sans-serif;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#C4C7D4;margin-bottom:8px;">Email content</div>{email.get('body','')}
        </div>
        <div style="border-left:3px solid {color};padding-left:12px;">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:{color};margin-bottom:4px;">🤖 AI reasoning</div>
            <div style="font-size:13px;color:#5B5F72;font-style:italic;font-family:Georgia,serif;line-height:1.6;">"{result.get('reasoning','')}"</div>
        </div>
        {memory_html}
        {parse_html}
    </div>"""

    show_draft = cat in ("time-sensitive", "actionable")
    return detail, gr.update(visible=show_draft)


def generate_draft(choice, active_cat, intent, name):
    if not choice or not intent.strip():
        return '<div style="color:#E8453C;font-family:sans-serif;padding:12px;font-size:14px;">Select an email and enter your intent first.</div>', gr.update(visible=False), gr.update(visible=False)
    results, emails = load_data()
    group = [r for r in results.values() if r.get("category") == active_cat]
    result = next((r for r in group if f"{r.get('subject','')[:55]} — {r.get('from','')}" == choice), None)
    if not result:
        return "", gr.update(visible=False), gr.update(visible=False)
    email = emails.get(result["email_id"], {})
    user_name = name.strip() or "Your Name"
    draft = draft_reply(email, result, intent, user_name=user_name)

    if draft.get("needs_clarification"):
        html = f'<div style="background:#FFFBEB;border:0.5px solid #F59E0B;border-radius:10px;padding:16px;font-family:sans-serif;"><div style="font-size:13px;font-weight:600;color:#B45309;margin-bottom:6px;">⚠️ Intent unclear — please clarify</div><div style="font-size:13px;color:#78350F;">{draft.get("question","")}</div></div>'
        return html, gr.update(visible=False), gr.update(visible=False)

    tone = draft.get("tone_detected", "unknown")
    color = CATEGORY_COLORS.get(active_cat, "#2B6CB0")
    warn = f'<div style="color:#B45309;font-size:12px;margin-bottom:10px;">⚠️ {draft["warnings"]}</div>' if draft.get("warnings") else ""

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;">
            <div style="background:#F8F9FF;border-radius:6px;padding:4px 12px;font-size:13px;color:#5B5F72;">To: <strong>{email.get('from','')}</strong></div>
            <div style="background:#F8F9FF;border-radius:6px;padding:4px 12px;font-size:13px;color:#5B5F72;">Tone: <strong style="color:{color};">{tone}</strong></div>
        </div>
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#C4C7D4;margin-bottom:4px;">Subject</div>
        <div style="font-size:15px;font-weight:600;color:#0A0A0F;margin-bottom:14px;">{draft.get('subject','')}</div>
        {warn}
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#C4C7D4;margin-bottom:6px;">Draft reply</div>
        <div style="background:#F8F9FF;border-radius:8px;padding:16px;font-family:'Courier New',monospace;font-size:13px;color:#3B3E4F;line-height:1.8;white-space:pre-wrap;border:0.5px solid #E2E5F0;">{draft.get('body','')}</div>
        <div style="font-size:12px;color:#9B9EAD;margin-top:10px;">Review carefully. No email will be sent without your explicit approval.</div>
    </div>"""

    return html, gr.update(visible=True), gr.update(visible=True)


def approve_send(choice, active_cat, intent, name):
    results, emails = load_data()
    group = [r for r in results.values() if r.get("category") == active_cat]
    result = next((r for r in group if f"{r.get('subject','')[:55]} — {r.get('from','')}" == choice), None)
    if not result:
        return "Error: email not found."
    email = emails.get(result["email_id"], {})
    user_name = name.strip() or "Your Name"
    draft = draft_reply(email, result, intent, user_name=user_name)
    from datetime import datetime
    log_entry = {"sent_at": datetime.now().isoformat(), "to": email.get("from",""), "original_subject": email.get("subject",""), "reply_subject": draft.get("subject",""), "reply_body": draft.get("body",""), "tone_detected": draft.get("tone_detected",""), "user_intent": intent, "simulated": True}
    log_path = "data/sent_log.json"
    existing = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            existing = json.load(f)
    existing.append(log_entry)
    with open(log_path, "w") as f:
        json.dump(existing, f, indent=2)
    return f"✓ Reply logged (simulated — no real email sent)\nTo: {email.get('from','')}\nSubject: {draft.get('subject','')}"


def do_confirm_memory():
    results, _ = load_data()
    if not results:
        return "No results to confirm."
    initialize_db(DB_PATH)
    live = [r for r in results.values() if not r.get("mock")]
    result = confirm_batch_results(live, DB_PATH)
    return f"✓ {result['confirmed']} results confirmed. ({result['skipped_parse_errors']} parse errors skipped.)"


with gr.Blocks(
    title="Prism — Inbox Intelligence",
    theme=gr.themes.Base(
        primary_hue="slate",
        neutral_hue="slate",
        font=gr.themes.GoogleFont("Inter"),
    ),
) as demo:

    gr.HTML("""
    <div style="background:#FFFFFF;border-bottom:0.5px solid #E2E5F0;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <div style="display:flex;align-items:center;gap:12px;">
            <svg width="30" height="30" viewBox="0 0 32 32" fill="none">
                <polygon points="16,4 28,26 4,26" fill="none" stroke="#0A0A0F" stroke-width="1.5" stroke-linejoin="round"/>
                <line x1="16" y1="4" x2="16" y2="26" stroke="#E8453C" stroke-width="1.2" opacity="0.7"/>
                <line x1="16" y1="4" x2="9" y2="26" stroke="#1A7F5A" stroke-width="1.2" opacity="0.7"/>
                <line x1="16" y1="4" x2="23" y2="26" stroke="#2B6CB0" stroke-width="1.2" opacity="0.7"/>
            </svg>
            <div>
                <div style="font-size:18px;font-weight:700;color:#0A0A0F;letter-spacing:-0.5px;">Prism</div>
                <div style="font-size:11px;color:#9B9EAD;">inbox intelligence</div>
            </div>
        </div>
        <div style="font-size:12px;color:#9B9EAD;">AI-powered triage · tone-matched drafting · sender memory</div>
    </div>
    """)

    active_cat_state = gr.State("time-sensitive")

    with gr.Row(equal_height=True):
        with gr.Column(scale=1, min_width=190):
            sidebar_html = gr.HTML()
            gr.HTML('<div style="height:0.5px;background:#E2E5F0;margin:8px 16px;"></div>')
            confirm_btn = gr.Button("🧠 Confirm to memory", size="sm", variant="secondary")
            confirm_out = gr.Textbox(label="", interactive=False, lines=2)

        with gr.Column(scale=4):
            with gr.Tabs():

                with gr.TabItem("📬 Inbox"):
                    with gr.Row():
                        cat_dropdown = gr.Dropdown(
                            choices=CATEGORY_ORDER,
                            value="time-sensitive",
                            label="Category",
                            scale=1,
                        )
                        search_box = gr.Textbox(
                            placeholder="Search by sender or subject...",
                            label="Search",
                            scale=2,
                        )
                    email_list_html = gr.HTML()

                with gr.TabItem("✉️ View & Reply"):
                    gr.HTML('<div style="font-size:13px;color:#9B9EAD;font-family:sans-serif;margin-bottom:12px;">Select a category and email to view full details and draft a reply.</div>')
                    with gr.Row():
                        reply_cat = gr.Dropdown(
                            choices=CATEGORY_ORDER,
                            value="time-sensitive",
                            label="Category",
                            scale=1,
                        )
                        reply_search = gr.Textbox(
                            placeholder="Search by sender or subject...",
                            label="Search",
                            scale=2,
                        )
                    email_selector = gr.Dropdown(choices=[], label="Select email", interactive=True)
                    view_btn = gr.Button("👁 View email", variant="secondary")
                    email_detail_html = gr.HTML()

                    draft_col = gr.Column(visible=False)
                    with draft_col:
                        gr.HTML('<div style="height:0.5px;background:#E2E5F0;margin:16px 0;"></div>')
                        gr.HTML('<div style="font-size:14px;font-weight:600;color:#0A0A0F;font-family:sans-serif;margin-bottom:12px;">Draft a reply</div>')
                        with gr.Row():
                            name_in = gr.Textbox(placeholder="Your name", label="Your name", scale=1)
                            intent_in = gr.Textbox(placeholder="What do you want to say? e.g. 'confirm I'll send the form by Sunday morning'", label="Your intent", scale=3)
                        draft_btn = gr.Button("✍️ Generate draft", variant="primary")
                        draft_html = gr.HTML()
                        with gr.Row():
                            approve_btn = gr.Button("✅ Approve & send (simulated)", variant="primary", visible=False)
                            reject_btn = gr.Button("❌ Reject draft", visible=False)
                        send_out = gr.Textbox(label="", interactive=False, lines=2)

                with gr.TabItem("ℹ️ About"):
                    gr.HTML("""
                    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;padding:8px 0;">
                        <div style="font-size:22px;font-weight:700;color:#0A0A0F;margin-bottom:8px;">Prism — Inbox Intelligence</div>
                        <div style="font-size:14px;color:#5B5F72;line-height:1.8;margin-bottom:20px;">An AI agent that reads your inbox and separates it into what actually matters — like light through a prism. Every classification comes with a plain-English explanation. Every reply is drafted only when you ask, and sent only when you approve.</div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
                            <div style="background:#FEF2F2;border-radius:8px;padding:14px;border-left:3px solid #E8453C;">
                                <div style="color:#E8453C;font-weight:600;margin-bottom:4px;font-size:14px;">⏰ Time-sensitive</div>
                                <div style="color:#7F1D1D;font-size:13px;">Real deadlines, even without urgency keywords</div>
                            </div>
                            <div style="background:#F0FDF4;border-radius:8px;padding:14px;border-left:3px solid #1A7F5A;">
                                <div style="color:#1A7F5A;font-weight:600;margin-bottom:4px;font-size:14px;">✅ Actionable</div>
                                <div style="color:#14532D;font-size:13px;">Needs a specific response or decision</div>
                            </div>
                            <div style="background:#EFF6FF;border-radius:8px;padding:14px;border-left:3px solid #2B6CB0;">
                                <div style="color:#2B6CB0;font-weight:600;margin-bottom:4px;font-size:14px;">ℹ️ Informational</div>
                                <div style="color:#1E3A5F;font-size:13px;">Useful to know, nothing to do</div>
                            </div>
                            <div style="background:#F8F9FF;border-radius:8px;padding:14px;border-left:3px solid #9B9EAD;">
                                <div style="color:#6B6F82;font-weight:600;margin-bottom:4px;font-size:14px;">🔇 Noise</div>
                                <div style="color:#3B3E4F;font-size:13px;">Marketing, alerts, low-value content</div>
                            </div>
                        </div>
                        <div style="font-size:13px;color:#9B9EAD;line-height:1.8;">
                            <strong style="color:#3B3E4F;">Stack:</strong> Python · Gemini 2.5 Flash-Lite · SQLite · Gradio<br>
                            <strong style="color:#3B3E4F;">Guardrails:</strong> Never auto-sends · Human confirms memory · Flags uncertainty<br>
                            <strong style="color:#3B3E4F;">Future scope:</strong> MCP integration for live Gmail access
                        </div>
                    </div>""")

    # ── Event wiring ──────────────────────────────────────────────────────────

    def inbox_update(cat, search):
        return refresh_inbox(cat, search)

    cat_dropdown.change(fn=inbox_update, inputs=[cat_dropdown, search_box], outputs=[sidebar_html, email_list_html, email_selector])
    search_box.change(fn=inbox_update, inputs=[cat_dropdown, search_box], outputs=[sidebar_html, email_list_html, email_selector])

    def reply_tab_update(cat, search):
        choices = get_email_choices(cat, search)
        return gr.update(choices=choices, value=None)

    reply_cat.change(fn=reply_tab_update, inputs=[reply_cat, reply_search], outputs=[email_selector])
    reply_search.change(fn=reply_tab_update, inputs=[reply_cat, reply_search], outputs=[email_selector])

    view_btn.click(fn=view_email, inputs=[email_selector, reply_cat], outputs=[email_detail_html, draft_col])
    email_selector.change(fn=view_email, inputs=[email_selector, reply_cat], outputs=[email_detail_html, draft_col])

    draft_btn.click(fn=generate_draft, inputs=[email_selector, reply_cat, intent_in, name_in], outputs=[draft_html, approve_btn, reject_btn])
    approve_btn.click(fn=approve_send, inputs=[email_selector, reply_cat, intent_in, name_in], outputs=[send_out])
    reject_btn.click(fn=lambda: ("Draft rejected. Nothing sent.", gr.update(visible=False), gr.update(visible=False)), outputs=[send_out, approve_btn, reject_btn])
    confirm_btn.click(fn=do_confirm_memory, outputs=[confirm_out])

    demo.load(fn=lambda: refresh_inbox("time-sensitive"), outputs=[sidebar_html, email_list_html, email_selector])


if __name__ == "__main__":
    initialize_db(DB_PATH)
    demo.launch(share=False)

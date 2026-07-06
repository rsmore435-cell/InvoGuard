import asyncio
import json
import streamlit as st
from google.adk.runners import InMemoryRunner
from google.genai import types
from google.adk.events.request_input import RequestInput
from google.adk.models.llm_response import LlmResponse

# Import agent and app from our codebase
from app.agent import app

# Set page configuration with premium title and layout
st.set_page_config(
    page_title="InvoGuard - B2B Invoice Compliance & Audit",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Premium Custom CSS styling
st.markdown("""
<style>
    /* Dark mode premium styling */
    .main {
        background-color: #0e1117;
        color: #ffffff;
        font-family: 'Outfit', 'Inter', sans-serif;
    }
    h1, h2, h3 {
        color: #f0f2f6;
        font-weight: 700;
    }
    .stButton>button {
        background-color: #1a73e8; /* Google Blue */
        color: white;
        border-radius: 8px;
        border: none;
        padding: 0.6rem 1.5rem;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #1557b0;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(26, 115, 232, 0.4);
    }
    /* Specific styles for override panel buttons to color Approve Blue and Reject Red */
    div[data-testid="stColumn"]:nth-child(2) div[data-testid="stHorizontalBlock"] div[data-testid="stColumn"]:nth-child(1) button {
        background-color: #10b981 !important; /* Emerald Green */
        color: white !important;
    }
    div[data-testid="stColumn"]:nth-child(2) div[data-testid="stHorizontalBlock"] div[data-testid="stColumn"]:nth-child(1) button:hover {
        background-color: #059669 !important;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4) !important;
        transform: translateY(-2px);
    }
    div[data-testid="stColumn"]:nth-child(2) div[data-testid="stHorizontalBlock"] div[data-testid="stColumn"]:nth-child(2) button {
        background-color: #d32f2f !important; /* Bold Red */
        color: white !important;
    }
    div[data-testid="stColumn"]:nth-child(2) div[data-testid="stHorizontalBlock"] div[data-testid="stColumn"]:nth-child(2) button:hover {
        background-color: #b71c1c !important;
        box-shadow: 0 4px 12px rgba(211, 47, 47, 0.4) !important;
        transform: translateY(-2px);
    }
    .send-email-container button {
        background-color: #5f6368 !important; /* Neutral Grey */
        color: white !important;
        margin-top: -0.5rem;
        margin-bottom: 1.5rem;
    }
    .send-email-container button:hover:not(:disabled) {
        background-color: #4b4f53 !important;
        box-shadow: 0 4px 12px rgba(95, 99, 104, 0.4) !important;
        transform: translateY(-2px);
    }
    .send-email-container button:disabled {
        background-color: #2a2a2a !important;
        color: #666666 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
        transform: none !important;
        opacity: 0.6;
    }
    .stTextArea textarea {
        background-color: #1e222b !important;
        color: #ffffff !important;
        border: 1px solid #3f444e !important;
        border-radius: 8px !important;
    }
    .status-card {
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        border-left: 5px solid;
    }
    .status-compliant {
        background-color: #11261d;
        border-left-color: #2e7d32;
        color: #a5d6a7;
    }
    .status-pending {
        background-color: #2d2613;
        border-left-color: #f57f17;
        color: #ffe082;
    }
    .status-security {
        background-color: #2d1316;
        border-left-color: #c62828;
        color: #ef9a9a;
    }
    .telemetry-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #90caf9;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session State variables if not set
if "telemetry_logs" not in st.session_state:
    st.session_state.telemetry_logs = []
if "compliance_status" not in st.session_state:
    st.session_state.compliance_status = None
if "audit_result" not in st.session_state:
    st.session_state.audit_result = None
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "runner" not in st.session_state:
    st.session_state.runner = InMemoryRunner(app=app)

runner = st.session_state.runner

# Page Title
st.title("🛡️ InvoGuard B2B Compliance & Audit Dashboard")

# Rate limit / Mock mode toggle
mock_mode = st.toggle("🛠️ Enable Mock Mode (Bypass Gemini API Daily Quota Limits)", value=True, help="Toggle this on to bypass rate limits by using mock LLM responses. Toggle off to make live calls to your Gemini API key.")
st.session_state.mock_mode = mock_mode

st.markdown("---")

# Layout: Two columns
col_left, col_right = st.columns([1, 1], gap="large")

# Global placeholder for telemetry log output
log_placeholder = None

async def mock_generate_content_async(self, llm_request, stream=False):
    prompt_text = ""
    for content in llm_request.contents:
        for part in content.parts:
            if hasattr(part, "text") and part.text:
                prompt_text += part.text
            elif isinstance(part, str):
                prompt_text += part
                
    prompt_text_lower = prompt_text.lower()
    
    # Determine which agent is calling by looking at the system instruction
    system_instruction = ""
    if hasattr(llm_request, "config") and llm_request.config:
        if hasattr(llm_request.config, "system_instruction") and llm_request.config.system_instruction:
            sys_inst = llm_request.config.system_instruction
            if isinstance(sys_inst, str):
                system_instruction = sys_inst
            elif hasattr(sys_inst, "parts"):
                for part in sys_inst.parts:
                    if hasattr(part, "text") and part.text:
                        system_instruction += part.text
    
    sys_lower = system_instruction.lower()
    
    # Extract response schema name from config to distinguish agents cleanly
    schema_name = ""
    if hasattr(llm_request, "config") and llm_request.config:
        if hasattr(llm_request.config, "response_schema") and llm_request.config.response_schema:
            schema_name = getattr(llm_request.config.response_schema, "__name__", "")
            if not schema_name and hasattr(llm_request.config.response_schema, "schema"):
                schema_name = str(llm_request.config.response_schema)
                
    is_parser = "ParsedInvoice" in schema_name
    is_auditor = "AuditedInvoice" in schema_name
    
    # Fallback to system instructions if schema name is not resolved
    if not is_parser and not is_auditor:
        is_parser = "extraction" in sys_lower or "documentparseragent" in sys_lower
        is_auditor = "compliance" in sys_lower or "auditoragent" in sys_lower
    
    import re
    import json
    
    parsed_json = None
    try:
        parsed_json = json.loads(prompt_text)
    except Exception:
        # Search for JSON substring
        for candidate in re.findall(r"(\{.*?\})", prompt_text, re.DOTALL):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and ("vendor_name" in data or "invoice_number" in data):
                    parsed_json = data
                    break
            except Exception:
                pass
                
    if parsed_json and isinstance(parsed_json, dict) and "vendor_name" in parsed_json:
        vendor_name = parsed_json.get("vendor_name", "Acme Corp")
        invoice_number = parsed_json.get("invoice_number", "INV-UNKNOWN")
        invoice_date = parsed_json.get("invoice_date", "2026-07-06")
        subtotal = float(parsed_json.get("subtotal", 0.0))
        tax_rate = float(parsed_json.get("tax_rate", 0.0))
        tax_amount = float(parsed_json.get("tax_amount", 0.0))
        total_amount = float(parsed_json.get("total_amount", 0.0))
        line_items = parsed_json.get("line_items", [])
    else:
        # Extract Vendor Name
        vendor_match = re.search(r"Vendor:\s*([^\n\r]+)", prompt_text, re.IGNORECASE)
        vendor_name = vendor_match.group(1).strip() if vendor_match else "Acme Corp"
        
        # Extract Invoice Number
        inv_match = re.search(r"Invoice\s*#?:\s*([^\n\r]+)", prompt_text, re.IGNORECASE)
        invoice_number = inv_match.group(1).strip() if inv_match else "INV-UNKNOWN"
        
        # Extract Date
        date_match = re.search(r"Date:\s*([^\n\r]+)", prompt_text, re.IGNORECASE)
        invoice_date = date_match.group(1).strip() if date_match else "2026-07-06"
        
        # Extract Subtotal
        subtotal_match = re.search(r"Subtotal:\s*\$?([\d.]+)", prompt_text, re.IGNORECASE)
        subtotal = float(subtotal_match.group(1)) if subtotal_match else 0.0
        
        # Extract Tax Rate
        tax_rate = 0.0
        tax_rate_match = re.search(r"Tax Rate:\s*[\d.]+%?\s*\(?([\d.]+)\)?", prompt_text, re.IGNORECASE)
        if tax_rate_match:
            tax_rate = float(tax_rate_match.group(1))
        else:
            simple_rate_match = re.search(r"Tax Rate:\s*([\d.]+)%", prompt_text, re.IGNORECASE)
            if simple_rate_match:
                tax_rate = float(simple_rate_match.group(1)) / 100.0
                
        # Extract Tax Amount
        tax_amt_match = re.search(r"Tax Amount:\s*\$?([\d.]+)", prompt_text, re.IGNORECASE)
        tax_amount = float(tax_amt_match.group(1)) if tax_amt_match else 0.0
        
        # Extract Total Amount
        total_match = re.search(r"Total Amount:\s*\$?([\d.]+)", prompt_text, re.IGNORECASE)
        total_amount = float(total_match.group(1)) if total_match else 0.0
        
        # Parse line items
        line_items = []
        for line in prompt_text.splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                item_match = re.search(r"[-*]\s*([^:]+):\s*([\d.]+)\s*(units?|hours?)\s*@\s*\$?([\d.]+)", line, re.IGNORECASE)
                if item_match:
                    desc = item_match.group(1).strip()
                    qty = float(item_match.group(2))
                    price = float(item_match.group(4))
                    line_items.append({
                        "description": desc,
                        "quantity": qty,
                        "unit_price": price,
                        "total": qty * price
                    })
                    
        if not line_items and subtotal > 0:
            line_items.append({
                "description": "Consulting" if "globex" in vendor_name.lower() else "Items",
                "quantity": 1.0,
                "unit_price": subtotal,
                "total": subtotal
            })

    parsed_invoice = {
        "vendor_name": vendor_name,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "line_items": line_items,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "raw_text": invoice_number
    }
    
    if is_parser:
        text_response = json.dumps(parsed_invoice)
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=text_response)]
            ),
            finish_reason=types.FinishReason.STOP
        )
        return
        
    elif is_auditor:
        has_query_contract = False
        has_verify_math = False
        for content in llm_request.contents:
            for part in content.parts:
                if part.function_response:
                    if part.function_response.name in ("query_contract_registry", "get_vendor_profile"):
                        has_query_contract = True
                    if part.function_response.name == "verify_math_calculations":
                        has_verify_math = True
                        
        if not has_query_contract:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="query_contract_registry",
                                args={"vendor_name": vendor_name}
                            )
                        ),
                        types.Part(
                            function_call=types.FunctionCall(
                                name="get_vendor_profile",
                                args={"vendor_name": vendor_name}
                            )
                        )
                    ]
                ),
                finish_reason=types.FinishReason.STOP
            )
            return
        elif not has_verify_math:
            expected_total = subtotal + tax_amount
            if abs(expected_total - total_amount) > 0.01:
                code = f"subtotal_ok = True; item_totals_ok = True; total_ok = False"
            else:
                code = "subtotal_ok = True; item_totals_ok = True; total_ok = True"
                
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="verify_math_calculations",
                                args={"code_to_verify": code}
                            )
                        )
                    ]
                ),
                finish_reason=types.FinishReason.STOP
            )
            return
        else:
            findings = []
            expected_total = subtotal + tax_amount
            is_compliant = True
            summary = "Invoice is fully compliant with contract terms and calculations are correct."
            
            if abs(expected_total - total_amount) > 0.01:
                findings.append({
                    "category": "math_error",
                    "description": f"The invoice total amount ({total_amount}) does not equal the sum of subtotal and tax amount ({subtotal} + {tax_amount} = {expected_total}).",
                    "severity": "high"
                })
                is_compliant = False
                summary = "Math calculation errors found."
                
            for item in line_items:
                desc_lower = item["description"].lower()
                price = item["unit_price"]
                if "widget a" in desc_lower and price > 12.0:
                    findings.append({
                        "category": "rate_breach",
                        "description": f"Line item Widget A rate of ${price} exceeds contracted limit of $12.00.",
                        "severity": "high"
                    })
                    is_compliant = False
                    summary = "Contract rate breach found."
                elif "service b" in desc_lower and price > 160.0:
                    findings.append({
                        "category": "rate_breach",
                        "description": f"Line item Service B rate of ${price} exceeds contracted limit of $160.00.",
                        "severity": "high"
                    })
                    is_compliant = False
                    summary = "Contract rate breach found."
                    
            audited_invoice = {
                "invoice_metadata": parsed_invoice,
                "findings": findings,
                "is_compliant": is_compliant,
                "audit_summary": summary
            }
            
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=json.dumps(audited_invoice))]
                ),
                finish_reason=types.FinishReason.STOP
            )
            return
            
    yield LlmResponse(
        content=types.Content(role="model", parts=[types.Part.from_text(text='{}')]),
        finish_reason=types.FinishReason.STOP
    )


# Async execution helper
async def run_pipeline(raw_text: str):
    st.session_state.telemetry_logs = ["🚀 Initializing InvoGuard multi-agent pipeline..."]
    log_placeholder.code("\n".join(st.session_state.telemetry_logs))
    
    st.session_state.compliance_status = None
    st.session_state.audit_result = None
    
    # Create session
    session = await runner.session_service.create_session(app_name="app", user_id="admin")
    st.session_state.session_id = session.id
    
    st.session_state.telemetry_logs.append(f"🔑 Created session: {session.id}")
    log_placeholder.code("\n".join(st.session_state.telemetry_logs))
    
    async def _execute():
        # Execute workflow graph
        async for event in runner.run_async(
            user_id="admin",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=raw_text)])
        ):
            if hasattr(event, "author") and event.author:
                st.session_state.telemetry_logs.append(f"🟢 [Node: {event.author}] executing...")
            
            # Check if the event is a workflow pause due to interrupt
            if isinstance(event, RequestInput) or hasattr(event, "interrupt_id"):
                st.session_state.telemetry_logs.append("⚠️ [HITL] Workflow PAUSED. Interruption ID: admin_override. Awaiting approval...")
                
            log_placeholder.code("\n".join(st.session_state.telemetry_logs))
            await asyncio.sleep(0.1) # simulated delay for execution traceability

    use_mock = st.session_state.get("mock_mode", True)
    if use_mock:
        from unittest.mock import patch
        from google.adk.models.google_llm import Gemini
        with patch.object(Gemini, "generate_content_async", mock_generate_content_async):
            await _execute()
    else:
        await _execute()
        
    # Fetch final state from session registry
    session_data = await runner.session_service.get_session(app_name="app", session_id=session.id, user_id="admin")
    st.session_state.compliance_status = session_data.state.get("compliance_status")
    st.session_state.audit_result = session_data.state.get("audit_result")
    
    st.session_state.telemetry_logs.append(f"🏁 Pipeline execution paused/finished. Status: {st.session_state.compliance_status}")
    log_placeholder.code("\n".join(st.session_state.telemetry_logs))


async def resume_pipeline(decision: str = "APPROVED"):
    if not st.session_state.session_id:
        return
        
    st.session_state.telemetry_logs.append(f"🔄 Resuming pipeline with programmatic '{decision}' token override...")
    log_placeholder.code("\n".join(st.session_state.telemetry_logs))
    
    # Construct the function response payload for resuming the paused node
    resume_msg = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    name="admin_override",
                    id="admin_override",
                    response={"result": decision}
                )
            )
        ]
    )
    
    async def _execute_resume():
        async for event in runner.run_async(
            user_id="admin",
            session_id=st.session_state.session_id,
            new_message=resume_msg
        ):
            if hasattr(event, "author") and event.author:
                st.session_state.telemetry_logs.append(f"🟢 [Node: {event.author}] executing...")
                
            log_placeholder.code("\n".join(st.session_state.telemetry_logs))
            await asyncio.sleep(0.1)

    use_mock = st.session_state.get("mock_mode", True)
    if use_mock:
        from unittest.mock import patch
        from google.adk.models.google_llm import Gemini
        with patch.object(Gemini, "generate_content_async", mock_generate_content_async):
            await _execute_resume()
    else:
        await _execute_resume()
        
    # Fetch final state from session registry
    session_data = await runner.session_service.get_session(app_name="app", session_id=st.session_state.session_id, user_id="admin")
    st.session_state.compliance_status = session_data.state.get("compliance_status")
    st.session_state.audit_result = session_data.state.get("audit_result")
    
    st.session_state.telemetry_logs.append(f"🏁 Pipeline finished. Final Status: {st.session_state.compliance_status}")
    log_placeholder.code("\n".join(st.session_state.telemetry_logs))


# LEFT COLUMN: Input & Telemetry Logs
with col_left:
    st.subheader("📥 Invoice Input & Ingestion")
    
    # Text input or file upload
    uploaded_file = st.file_uploader("Upload raw Invoice text file (.txt)", type=["txt"])
    
    default_text = """INVOICE
Vendor: Acme Corp
Invoice #: INV-2026-991
Date: 2026-07-06

Line Items:
- Widget A: 50 units @ $10.00 each -> Total: $500.00
- Service B: 10 hours @ $150.00 each -> Total: $1500.00

Subtotal: $2000.00
Tax Rate: 5% (0.05)
Tax Amount: $100.00
Total Amount: $2100.00"""
    
    if uploaded_file is not None:
        invoice_text = uploaded_file.read().decode("utf-8")
    else:
        invoice_text = st.text_area("Paste Raw Invoice Data:", default_text, height=250)
        
    st.markdown("<div class='telemetry-header'>🕵️‍♂️ ADK Agent Live Telemetry Logs</div>", unsafe_allow_html=True)
    log_placeholder = st.empty()
    if st.session_state.telemetry_logs:
        log_placeholder.code("\n".join(st.session_state.telemetry_logs))
    else:
        log_placeholder.code("System idle. Awaiting invoice audit execution.")

    # Start button
    if st.button("🚀 Execute compliance audit", use_container_width=True):
        with st.spinner("Processing invoice through multi-agent graph..."):
            asyncio.run(run_pipeline(invoice_text))


# RIGHT COLUMN: Compliance Status & Human-in-the-Loop Override
with col_right:
    st.subheader("📊 Financial Compliance Status")
    
    status = st.session_state.compliance_status
    result = st.session_state.audit_result
    
    if status is None:
        st.info("Run the audit pipeline to see results.")
    else:
        # Display the custom status box
        if status == "COMPLIANT_APPROVED":
            st.markdown("""
            <div class='status-card status-compliant'>
                <h4>✅ COMPLIANT & APPROVED</h4>
                <p>The invoice has passed all contract rate audits and mathematical verification checks.</p>
            </div>
            """, unsafe_allow_html=True)
            
        elif status == "PENDING_APPROVAL":
            st.markdown("""
            <div class='status-card status-pending'>
                <h4>⚠️ PENDING HUMAN APPROVAL</h4>
                <p>Discrepancies found. The workflow has been paused. Review the breakdown below and action an override if acceptable.</p>
            </div>
            """, unsafe_allow_html=True)
            
        elif status == "APPROVED_WITH_OVERRIDE":
            st.markdown("""
            <div class='status-card status-compliant'>
                <h4>🟢 APPROVED WITH OVERRIDE</h4>
                <p>This invoice has been approved via manual administrator override despite flagged warnings.</p>
            </div>
            """, unsafe_allow_html=True)
            
        elif status == "SECURITY_REJECTED":
            st.markdown("""
            <div class='status-card status-security'>
                <h4>🚨 SECURITY REJECTED (PAYLOAD BLOCKED)</h4>
                <p>An adversarial prompt injection attempt was detected in the raw input text. Processing aborted immediately.</p>
            </div>
            """, unsafe_allow_html=True)
            
        # Display discrepancy findings
        if result:
            findings = result.get("findings", [])
            st.markdown("#### 🔍 Discrepancy & Validation Findings")
            if not findings:
                st.success("No validation issues or contract breaches found.")
            else:
                for idx, finding in enumerate(findings):
                    severity_color = "🔴" if finding["severity"] == "high" else "🟡"
                    st.markdown(f"{severity_color} **{finding['category'].upper()}**: {finding['description']} *(Severity: {finding['severity']})*")
            
            # Display Extracted Data Preview
            metadata = result.get("invoice_metadata", {})
            if metadata and metadata.get("vendor_name") != "SUSPECTED_ATTACKER":
                with st.expander("📄 Extracted Invoice Metadata Preview"):
                    st.write(f"**Vendor Name:** {metadata.get('vendor_name')}")
                    st.write(f"**Invoice Number:** {metadata.get('invoice_number')}")
                    st.write(f"**Invoice Date:** {metadata.get('invoice_date')}")
                    st.write(f"**Calculated Subtotal:** ${metadata.get('subtotal')}")
                    st.write(f"**Tax Amount:** ${metadata.get('tax_amount')}")
                    st.write(f"**Total Amount:** ${metadata.get('total_amount')}")
                    
            # Generate email if compliance flagged
            if findings:
                st.markdown("#### ✉️ Draft Email for Vendor")
                vendor_name = metadata.get("vendor_name", "Vendor")
                invoice_num = metadata.get("invoice_number", "UNKNOWN")
                invoice_date = metadata.get("invoice_date", "UNKNOWN")
                
                discrepancy_list = "\n".join([f"- {f['description']}" for f in findings])
                
                draft_email = f"""Subject: Flagged Invoice #{invoice_num} - Action Required

Dear Accounts Payable team at {vendor_name},

Our automated auditing system (InvoGuard) has processed your invoice #{invoice_num} dated {invoice_date} and identified compliance discrepancies that prevent processing:

{discrepancy_list}

Please review your invoice calculations and ensure contract terms are strictly met. Re-submit a corrected invoice at your earliest convenience.

Best regards,
InvoGuard Compliance Team
"""
                is_injection = (metadata.get("vendor_name") == "SUSPECTED_ATTACKER")
                
                if is_injection:
                    # Prompt injection: suppress the draft email entirely
                    st.info("ℹ️ Vendor email draft suppressed for suspected adversarial payload.")
                else:
                    # Normal compliance finding: show draft email + Send Email button
                    st.text_area("Draft Notification Email:", draft_email, height=180)
                    
                    if st.button("✉️ Send Email", key="send_email_btn", use_container_width=True):
                        st.success("✅ Email successfully sent to vendor!")


            # HITL Override Buttons
            if status in ["PENDING_APPROVAL", "SECURITY_REJECTED"]:
                st.markdown("#### 🛠️ Administrator Override Panel")
                st.warning("Actioning an override bypasses standard compliance checks. A security rejection override should be audited carefully.")
                
                col_btn1, col_btn2 = st.columns([1, 1])
                with col_btn1:
                    if st.button("✔️ Approve Override & Resolve Block", use_container_width=True):
                        with st.spinner("Executing programmatic override..."):
                            asyncio.run(resume_pipeline("APPROVED"))
                            st.rerun()
                with col_btn2:
                    if st.button("🔴 Reject Invoice", use_container_width=True):
                        with st.spinner("Executing rejection override..."):
                            asyncio.run(resume_pipeline("REJECTED"))
                            st.success("Rejection notification sent successfully!")
                            st.rerun()

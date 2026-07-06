import os
from typing import List, Optional, Any
from pydantic import BaseModel, Field

# Try to load env vars from .env file (check local or parent directories)
for env_path in [".env", "../.env", "invoguard/.env"]:
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

# Set up local environment flags for Gemini API client
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
else:
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            import google.auth
            _, project_id = google.auth.default()
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        except Exception:
            pass
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.workflow import Workflow, START, node
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.genai import types

# Import custom tools
from .tools import query_contract_registry, verify_math_calculations, vendor_mcp_toolset

# --- 1. PYDANTIC SCHEMAS FOR STRUCTURED DATA PASSING ---

class LineItem(BaseModel):
    description: str = Field(description="Description of the item or service.")
    quantity: float = Field(description="Quantity purchased.")
    unit_price: float = Field(description="Unit price of the item or service.")
    total: float = Field(description="Total cost for this line item (quantity * unit_price).")

class ParsedInvoice(BaseModel):
    vendor_name: str = Field(description="The legal name of the vendor.")
    invoice_number: str = Field(description="The invoice ID or number.")
    invoice_date: str = Field(description="The date of the invoice.")
    line_items: List[LineItem] = Field(description="List of all invoice line items.")
    subtotal: float = Field(description="The calculated subtotal (sum of line item totals).")
    tax_rate: float = Field(description="The tax rate applied (e.g. 0.05 for 5%).")
    tax_amount: float = Field(description="The tax amount charged.")
    total_amount: float = Field(description="The total amount of the invoice including tax.")
    raw_text: str = Field(description="The raw unparsed text content of the invoice.")

class AuditFinding(BaseModel):
    category: str = Field(description="The category of error: 'math_error', 'contract_rate_violation', 'security_flag', or 'vendor_status_warning'.")
    description: str = Field(description="Detailed explanation of the discrepancy or validation issue.")
    severity: str = Field(description="The severity level: 'high', 'medium', or 'low'.")

class AuditedInvoice(BaseModel):
    invoice_metadata: ParsedInvoice = Field(description="The parsed invoice metadata.")
    findings: List[AuditFinding] = Field(default=[], description="List of compliance or validation findings.")
    is_compliant: bool = Field(description="True if there are no warnings or errors, False otherwise.")
    audit_summary: str = Field(description="A concise summary of the audit findings.")

# Workflow Input/Output schemas
class WorkflowInput(BaseModel):
    raw_invoice_text: str = Field(description="The raw unformatted invoice text to process.")

class WorkflowOutput(BaseModel):
    invoice: Optional[AuditedInvoice] = None
    status: str = Field(description="Result status: 'COMPLIANT_APPROVED', 'PENDING_APPROVAL', 'APPROVED_WITH_OVERRIDE', or 'SECURITY_REJECTED'.")
    findings: List[AuditFinding] = Field(default=[])
    message: str = Field(description="Audit summary message.")


# --- 2. MULTI-AGENT GRAPH NODES & SAFETY GUARDRAILS ---

# Adversarial Input-Sanitization Layer (Node 1)
def sanitization_node(ctx: Context, node_input: Any):
    """Adversarial preprocessing function that checks for prompt injection attacks.
    
    Treats raw text strictly as untrusted input to block forced compliance/bypass payloads.
    """
    # Safely extract raw text from different potential input formats
    if hasattr(node_input, "parts") and node_input.parts:
        raw_text = node_input.parts[0].text
    elif isinstance(node_input, str):
        raw_text = node_input
    else:
        raw_text = str(node_input)
        
    raw_text_lower = raw_text.lower()
    
    adversarial_patterns = [
        "ignore previous instructions",
        "bypass audit",
        "force approval",
        "override compliance",
        "set compliant to true",
        "system: override",
        "bypass calculations",
        "do not audit",
        "trust this vendor",
        "flag as compliant",
        "force compliant",
        "approve without check",
        "ignore rules"
    ]
    
    detected = [pattern for pattern in adversarial_patterns if pattern in raw_text_lower]
    
    if detected:
        # Create a security alert audit finding
        finding = AuditFinding(
            category="security_flag",
            description=f"Prompt injection pattern detected: '{', '.join(detected)}'",
            severity="high"
        )
        
        # Build an AuditedInvoice structure representing the security failure
        security_audit = AuditedInvoice(
            invoice_metadata=ParsedInvoice(
                vendor_name="SUSPECTED_ATTACKER",
                invoice_number="UNKNOWN",
                invoice_date="UNKNOWN",
                line_items=[],
                subtotal=0.0,
                tax_rate=0.0,
                tax_amount=0.0,
                total_amount=0.0,
                raw_text=raw_text
            ),
            findings=[finding],
            is_compliant=False,
            audit_summary="SECURITY VIOLATION: Adversarial prompt injection detected and blocked."
        )
        
        # Route directly to TriageAgent bypassing parser and auditor
        yield Event(
            output=security_audit,
            route="security_blocked",
            state={
                "compliance_status": "SECURITY_REJECTED",
                "audit_result": security_audit.model_dump()
            }
        )
        return
        
    # Input is safe, yield the raw_text string downstream to DocumentParserAgent
    yield Event(output=raw_text, route="clear")
    return


# Document Parser Agent (Node 2)
DocumentParserAgent = LlmAgent(
    name="DocumentParserAgent",
    model=Gemini(
        model="gemini-2.0-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a B2B Invoice Document Extraction specialist.
Your task is to parse unstructured raw invoice text and structure it according to the output schema.
Extract all details: vendor name, invoice date, number, line items (desc, quantity, unit price, total), subtotal, tax rate, tax amount, and total.
Ensure all numeric fields are populated as floats. Preserve the exact raw text in the raw_text field.
Do not perform calculations yourself, just extract what is written on the document.""",
    output_schema=ParsedInvoice,
    output_key="parsed_invoice"
)


# Auditor Agent (Node 3)
AuditorAgent = LlmAgent(
    name="AuditorAgent",
    model=Gemini(
        model="gemini-2.0-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are an Invoice Compliance Auditor.
Your job is to audit a ParsedInvoice.
You MUST execute the following sequence:
1. Call query_contract_registry with vendor_name to retrieve contracted rates and spending limits.
2. Call get_vendor_profile (via the vendor_mcp_toolset) to fetch the vendor profile configuration (tier, discount_rate, status, etc.).
3. Write and run a python snippet using verify_math_calculations to check the invoice math:
   - Does subtotal equal sum(item.total)?
   - Does total for each item equal item.quantity * item.unit_price?
   - Does tax_amount equal subtotal * tax_rate?
   - Does total_amount equal subtotal + tax_amount?
4. Identify compliance issues:
   - Math discrepancies.
   - Any unit price in the invoice exceeding the contracted rate for that item.
   - Total amount exceeding the vendor's max_invoice_limit.
   - Vendor registration status is not 'ACTIVE'.
   
Collate all discrepancies into the findings list. If no findings are found, is_compliant must be True. Otherwise, is_compliant must be False.""",
    tools=[query_contract_registry, verify_math_calculations, vendor_mcp_toolset],
    output_schema=AuditedInvoice,
    output_key="audited_invoice"
)


# Human-in-the-Loop Triage Node (Node 4)
@node(name="TriageAgent", rerun_on_resume=True)
async def TriageAgent(ctx: Context, node_input: AuditedInvoice):
    """Evaluates audit findings and handles exceptions, routing, and Human-in-the-Loop triage.
    
    If discrepancies (or security alerts) are found, pauses workflow execution and requests manual override.
    """
    findings = node_input.findings
    is_compliant = node_input.is_compliant
    
    # Check if there are any compliance issues or security flags
    if findings or not is_compliant:
        # Determine if it's a security block or a standard compliance flag
        is_security_alert = any(f.category == "security_flag" for f in findings)
        
        # Check if the programmatic HITL approval or rejection has been provided
        if ctx.resume_inputs and "admin_override" in ctx.resume_inputs:
            override_val = ctx.resume_inputs.get("admin_override")
            if override_val == "APPROVED":
                status = "APPROVED_WITH_OVERRIDE"
                msg = "Invoice compliance audit failed, but was manually approved by administrator override."
            else:
                status = "SECURITY_REJECTED" if is_security_alert else "REJECTED"
                msg = f"Invoice compliance audit failed and was rejected by manual administrator decision (Reason: {override_val})."
                
            yield Event(
                output=WorkflowOutput(
                    invoice=node_input,
                    status=status,
                    findings=findings,
                    message=msg
                ),
                state={
                    "compliance_status": status,
                    "audit_result": node_input.model_dump()
                }
            )
            return
        else:
            # First execution: Set state to PENDING_APPROVAL and yield RequestInput to pause the graph
            status = "SECURITY_REJECTED" if is_security_alert else "PENDING_APPROVAL"
            ctx.state["compliance_status"] = status
            ctx.state["audit_result"] = node_input.model_dump()
            
            # Pause workflow using RequestInput
            yield RequestInput(
                interrupt_id="admin_override",
                message=f"Compliance check failed ({len(findings)} findings). Requires administrator override approval."
            )
            return
    else:
        # Clean invoice - auto-approves
        status = "COMPLIANT_APPROVED"
        yield Event(
            output=WorkflowOutput(
                invoice=node_input,
                status=status,
                findings=[],
                message="Invoice successfully audited and approved (no compliance issues found)."
            ),
            state={
                "compliance_status": status,
                "audit_result": node_input.model_dump()
            }
        )
        return


# --- 3. WORKFLOW GRAPH CONFIGURATION ---

root_agent = Workflow(
    name="invoguard_workflow",
    edges=[
        (START, sanitization_node),
        # If input is sanitized (clear), proceed to parsing; otherwise, go to TriageAgent
        (sanitization_node, {"clear": DocumentParserAgent, "security_blocked": TriageAgent}),
        # Standard flow
        (DocumentParserAgent, AuditorAgent),
        (AuditorAgent, TriageAgent),
    ],
    output_schema=WorkflowOutput,
)

app = App(
    name="app",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True)
)

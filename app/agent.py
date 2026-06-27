import os
import re
import datetime
import json
from typing import Any, Optional
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.tools import AgentTool, McpToolset
from mcp import StdioServerParameters
from google.adk.workflow import Workflow, node, START, Edge
from google.genai import types

from app.config import config

# Define State Schema
class DineOutState(BaseModel):
    cuisine_preferences: list[str] = []
    dietary_restrictions: list[str] = []
    budget: Optional[str] = None
    restaurant_name: Optional[str] = None
    date_time: Optional[str] = None
    party_size: Optional[int] = None
    response_text: Optional[str] = None

# Define Orchestrator Output Schema
class OrchestratorOutput(BaseModel):
    action: str = Field(description="The action to take: 'respond' to chat normally, or 'reserve' to book a reservation.")
    response_text: str = Field(description="The text response to show the user.")
    restaurant_name: Optional[str] = Field(default=None, description="The name of the restaurant to reserve.")
    date_time: Optional[str] = Field(default=None, description="The date and time for the reservation.")
    party_size: Optional[int] = Field(default=None, description="The number of guests for the reservation.")

# Initialize McpToolset pointing to the local mcp_server.py
mcp_server_path = os.path.join(os.path.dirname(__file__), 'mcp_server.py')
mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="python",
        args=[mcp_server_path],
    )
)

# Initialize Sub-Agents
preference_manager = LlmAgent(
    name="preference_manager",
    model=Gemini(model=config.model),
    instruction=(
        "You are a dining preference manager. You analyze the user's input "
        "to identify dietary restrictions (e.g. vegan, gluten-free), favorite cuisines, "
        "and budget preferences. Help the user manage their preferences."
    )
)

restaurant_finder = LlmAgent(
    name="restaurant_finder",
    model=Gemini(model=config.model),
    instruction=(
        "You are a restaurant finder. You look for restaurants based on cuisine, "
        "location, and price. Use the get_restaurants tool to find options and get_menu "
        "to check their details."
    ),
    tools=[mcp_toolset]
)

# Initialize Orchestrator Agent
orchestrator = LlmAgent(
    name="orchestrator",
    model=Gemini(model=config.model),
    instruction=(
        "You are the DineOut Restaurant Concierge. You guide the user's dining search "
        "and reservation process. "
        "For preference management (analyzing allergies, favorite cuisines), delegate to the preference_manager agent. "
        "For finding restaurants or searching menus, delegate to the restaurant_finder agent. "
        "If the user wants to book/reserve a table, extract the restaurant_name, date_time, "
        "and party_size, then output a JSON structure matching the reserve schema."
    ),
    tools=[
        AgentTool(preference_manager),
        AgentTool(restaurant_finder),
        mcp_toolset
    ],
    output_schema=OrchestratorOutput
)

# Security Log Helper
def log_security_event(event_type: str, severity: str, details: str):
    log_file = "security_audit.log"
    log_entry = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "severity": severity,
        "details": details
    }
    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Failed to write security log: {e}")

# Workflow Function Nodes
@node
def check_security(ctx, node_input: Any):
    # node_input is the START input (usually types.Content)
    query_text = ""
    if hasattr(node_input, "parts") and node_input.parts:
        query_text = "".join([part.text for part in node_input.parts if part.text])
    elif isinstance(node_input, str):
        query_text = node_input

    # 1. Prompt Injection Detection
    injection_keywords = [
        "ignore previous instructions", "ignore instructions", "system prompt",
        "jailbreak", "override instructions", "developer mode", "you must ignore"
    ]
    for kw in injection_keywords:
        if kw in query_text.lower():
            log_security_event("PROMPT_INJECTION", "CRITICAL", f"Query containing keyword '{kw}': '{query_text}'")
            return Event(output="Prompt injection attempt detected.", route="alert")

    # 2. PII Scrubbing
    scrubbed_query = query_text
    pii_found = False
    
    # Email pattern
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    if re.search(email_pattern, scrubbed_query):
        scrubbed_query = re.sub(email_pattern, "[EMAIL_REDACTED]", scrubbed_query)
        pii_found = True
        
    # Phone pattern
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    if re.search(phone_pattern, scrubbed_query):
        scrubbed_query = re.sub(phone_pattern, "[PHONE_REDACTED]", scrubbed_query)
        pii_found = True

    # Credit card pattern
    cc_pattern = r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'
    if re.search(cc_pattern, scrubbed_query):
        scrubbed_query = re.sub(cc_pattern, "[CARD_REDACTED]", scrubbed_query)
        pii_found = True

    if pii_found:
        log_security_event("PII_SCRUBBED", "WARNING", f"PII elements scrubbed. Original: '{query_text}', Scrubbed: '{scrubbed_query}'")
    else:
        log_security_event("INPUT_VERIFIED", "INFO", "Input query verified successfully with no violations.")

    # 3. Domain Specific Rule: Maximum party size of 20
    party_match = re.search(r'\b(?:party|group|guests|people|size|table for)\s*(?:of)?\s*(\d+)\b', scrubbed_query, re.IGNORECASE)
    if party_match:
        size = int(party_match.group(1))
        if size > 20:
            log_security_event("POLICY_VIOLATION", "WARNING", f"User requested reservation for {size} people, exceeding maximum limit of 20.")
            return Event(output="Request blocked. Group sizes larger than 20 require custom event planning. Please contact the restaurant directly.", route="alert")

    return Event(output=scrubbed_query, route="clean")

@node
def security_alert(ctx, node_input: str):
    msg = f"Blocked: {node_input}"
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
    yield Event(output=msg)

@node
def route_after_orchestrator(ctx, node_input: dict):
    action = node_input.get("action", "respond")
    response_text = node_input.get("response_text", "")
    
    # Save to state
    ctx.state.response_text = response_text
    ctx.state.restaurant_name = node_input.get("restaurant_name")
    ctx.state.date_time = node_input.get("date_time")
    ctx.state.party_size = node_input.get("party_size")
    
    if action == "reserve":
        return Event(output=node_input, route="reserve")
    return Event(output=response_text, route="respond")

@node
def prepare_reservation(ctx, node_input: dict):
    return "prepared"

@node(rerun_on_resume=True)
async def request_approval(ctx, node_input: str):
    if not ctx.resume_inputs or "approval" not in ctx.resume_inputs:
        rest = ctx.state.restaurant_name
        dt = ctx.state.date_time
        ps = ctx.state.party_size
        msg = f"Please confirm your booking for {rest} on {dt} for {ps} guests. Reply with 'yes' to confirm or 'no' to cancel."
        yield RequestInput(interrupt_id="approval", message=msg)
        return
    
    user_reply = ctx.resume_inputs["approval"]
    if user_reply.strip().lower() in ("yes", "y", "confirm", "approve"):
        yield Event(output="approved", route="approved")
    else:
        yield Event(output="cancelled", route="cancelled")

@node
async def execute_reservation(ctx, node_input: str):
    if node_input == "approved":
        rest = ctx.state.restaurant_name
        dt = ctx.state.date_time
        ps = ctx.state.party_size
        msg = f"Successfully booked {rest} on {dt} for {ps} guests! Confirmation ID: CONF-{os.urandom(2).hex().upper()}"
        return msg
    return "Reservation booking cancelled as requested."

@node
def final_response(ctx, node_input: str):
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=node_input)]))
    yield Event(output=node_input)

# Compile Workflow Graph
root_agent = Workflow(
    name="dineout_workflow",
    state_schema=DineOutState,
    edges=[
        Edge(from_node=START, to_node=check_security),
        Edge(from_node=check_security, to_node=orchestrator, route="clean"),
        Edge(from_node=check_security, to_node=security_alert, route="alert"),
        Edge(from_node=orchestrator, to_node=route_after_orchestrator),
        Edge(from_node=route_after_orchestrator, to_node=prepare_reservation, route="reserve"),
        Edge(from_node=route_after_orchestrator, to_node=final_response, route="__DEFAULT__"),
        Edge(from_node=prepare_reservation, to_node=request_approval),
        Edge(from_node=request_approval, to_node=execute_reservation, route="approved"),
        Edge(from_node=request_approval, to_node=final_response, route="cancelled"),
        Edge(from_node=execute_reservation, to_node=final_response),
    ]
)

# Export App
app = App(
    root_agent=root_agent,
    name="app"
)

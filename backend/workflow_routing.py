"""
Xiphos Compliance Workflow Routing Module v5.0

Routes alerts downstream of the decision engine into appropriate
compliance review queues based on AlertDisposition category,
vendor sensitivity, and SLA requirements.

Implements four-tier queue system:
  - BLOCKED:             Immediate auto-block, no human review
  - COMPLIANCE_REVIEW:   Escalate to compliance officer
  - ANALYST_REVIEW:      Queue for security analyst review
  - AUTO_CLEARED:        Logged and cleared, no action needed

Each disposition maps to specific SLA, notification recipients,
escalation paths, and audit trail entries.

Per ACAMS/Wolfsberg for defense vendor risk:
- Sensitivity levels (CRITICAL_SCI/CRITICAL_SAP) cut SLA in half
- Unresolved alerts escalate automatically at SLA boundary
- Full audit trail for regulatory examination

Model version: 1.0-WorkflowRouting-Compliance
Author:        Xiphos Principal Risk Scientist
Date:          March 2026
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional
from decision_engine import AlertDisposition


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class AlertQueue(str, Enum):
    """
    Compliance workflow queue destinations.
    
    Each queue has distinct SLA, notification recipients, and escalation rules.
    """
    BLOCKED            = "BLOCKED"            # Immediate block, zero SLA
    COMPLIANCE_REVIEW  = "COMPLIANCE_REVIEW"  # Compliance officer decision, 24h SLA
    ANALYST_REVIEW     = "ANALYST_REVIEW"     # Security analyst triage, 72h SLA
    AUTO_CLEARED       = "AUTO_CLEARED"       # Logged only, no action needed


class NotificationMethod(str, Enum):
    """Notification delivery mechanisms."""
    EMAIL    = "EMAIL"
    SLACK    = "SLACK"
    SMS      = "SMS"
    IN_SYSTEM = "IN_SYSTEM"


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NotificationRecipient:
    """
    Recipient for workflow event notifications.
    
    Attributes:
        role: Job title or functional role (e.g., 'compliance_officer', 'analyst')
        email: Email address for notifications
        method: Preferred notification method
        is_required: Whether this recipient must acknowledge
    """
    role: str
    email: str
    method: NotificationMethod = NotificationMethod.EMAIL
    is_required: bool = True


@dataclass
class EscalationPath:
    """
    Escalation plan if alert not resolved by SLA.
    
    Attributes:
        escalate_to_role: Role to escalate to when SLA expires
        escalation_hours: How many hours past SLA before escalation fires
        escalation_notification: Email/Slack message for escalation
    """
    escalate_to_role: str
    escalation_hours: int
    escalation_notification: str = ""


@dataclass
class WorkflowAction:
    """
    Routing decision for an alert.
    
    Encodes the full workflow action including queue assignment, SLA,
    notifications, escalation path, and audit trail entry.
    
    Attributes:
        queue: Target AlertQueue
        assigned_role: Primary role responsible for action
        sla_hours: Hours until automatic escalation (0 = immediate)
        notifications: List of NotificationRecipient objects
        audit_entry: Dict with action details for compliance audit
        escalation_path: EscalationPath for SLA breach handling
    """
    queue: AlertQueue
    assigned_role: str
    sla_hours: int
    notifications: list[NotificationRecipient] = field(default_factory=list)
    audit_entry: dict = field(default_factory=dict)
    escalation_path: Optional[EscalationPath] = None


@dataclass
class WorkflowEvent:
    """
    Audit trail entry for a workflow routing decision.
    
    Immutable record of when an alert was routed, by whom, with what
    disposition, and what action was taken. Used for regulatory
    examination and SOX/SOC-2 compliance.
    
    Attributes:
        event_id: Unique event identifier (UUID v4)
        timestamp: ISO-8601 timestamp of routing decision
        case_id: Vendor case identifier
        vendor_name: Human-readable vendor name
        disposition_category: AlertDisposition category (DEFINITE, PROBABLE, POSSIBLE, UNLIKELY)
        queue: Target AlertQueue from routing decision
        action_taken: Description of action (e.g., "routed_to_compliance_review")
        resolved_by: User or system ID that resolved the alert (optional, filled at resolution)
        resolution_notes: Notes about resolution (optional, filled at resolution)
    """
    event_id: str
    timestamp: str
    case_id: str
    vendor_name: str
    disposition_category: str
    queue: str
    action_taken: str
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def route_alert(
    disposition: AlertDisposition,
    vendor_name: str,
    case_id: str,
    sensitivity: str = "STANDARD"
) -> WorkflowAction:
    """
    Route an alert to appropriate queue based on disposition and sensitivity.
    
    Implements the 4-tier routing logic that maps AlertDisposition categories
    to compliance queues, SLA targets, and escalation rules.
    
    DEFINITE alerts:
      - Queue:       BLOCKED (immediate, no human review)
      - SLA:         0 hours (auto-block, effective immediately)
      - Notify:      compliance_officer (primary), admin (secondary)
      - Escalation:  None (already at max priority)
      - Action:      Auto-block transaction, preserve evidence
    
    PROBABLE alerts:
      - Queue:       COMPLIANCE_REVIEW
      - SLA:         24 hours (default, 12h if CRITICAL_SCI/CRITICAL_SAP)
      - Notify:      compliance_officer (required)
      - Escalation:  Escalate to admin if unresolved at SLA+4h
      - Action:      Create compliance review ticket, hold transaction
    
    POSSIBLE alerts:
      - Queue:       ANALYST_REVIEW
      - SLA:         72 hours (default, 36h if CRITICAL_SCI/CRITICAL_SAP)
      - Notify:      analyst (required)
      - Escalation:  Escalate to compliance_officer at SLA+8h if unresolved
      - Action:      Triage for human review, gather context
    
    UNLIKELY alerts:
      - Queue:       AUTO_CLEARED
      - SLA:         N/A (no review needed)
      - Notify:      None (audit log only)
      - Escalation:  None
      - Action:      Log and archive, clear transaction
    
    Args:
        disposition: AlertDisposition from decision_engine.classify_alert()
        vendor_name: Human-readable vendor name (for audit trail)
        case_id: Vendor case identifier (for tracking)
        sensitivity: One of STANDARD, CRITICAL_SCI, CRITICAL_SAP
                    Sensitivity level determines if SLA is halved and extra
                    admin notification added.
    
    Returns:
        WorkflowAction with queue, SLA, notifications, and escalation plan.
    
    Raises:
        ValueError: If disposition.category is not recognized.
    """
    
    category = disposition.category
    is_sensitive = sensitivity in ("CRITICAL_SCI", "CRITICAL_SAP")
    
    # ─────────────────────────────────────────────────────────────────────────
    # DEFINITE: Immediate auto-block
    # ─────────────────────────────────────────────────────────────────────────
    if category == "DEFINITE":
        notifications = [
            NotificationRecipient(
                role="compliance_officer",
                email="compliance@xiphos.local",
                method=NotificationMethod.EMAIL,
                is_required=True
            ),
            NotificationRecipient(
                role="admin",
                email="admin@xiphos.local",
                method=NotificationMethod.SLACK,
                is_required=True
            )
        ]
        
        audit_entry = {
            "disposition_category": "DEFINITE",
            "risk_weight": disposition.override_risk_weight,
            "classification_confidence": disposition.confidence_band,
            "recommended_action": disposition.recommended_action,
            "explanation": disposition.explanation,
            "screening_source": disposition.screening_result.matched_entry.uid if (disposition.screening_result and disposition.screening_result.matched_entry) else None,
            "classification_factors": disposition.classification_factors
        }
        
        return WorkflowAction(
            queue=AlertQueue.BLOCKED,
            assigned_role="system_auto_block",
            sla_hours=0,
            notifications=notifications,
            audit_entry=audit_entry,
            escalation_path=None  # No escalation for DEFINITE (already max priority)
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # PROBABLE: Compliance officer review, 24h SLA (12h if sensitive)
    # ─────────────────────────────────────────────────────────────────────────
    elif category == "PROBABLE":
        base_sla = 24
        if is_sensitive:
            base_sla = 12
        
        notifications = [
            NotificationRecipient(
                role="compliance_officer",
                email="compliance@xiphos.local",
                method=NotificationMethod.EMAIL,
                is_required=True
            )
        ]
        
        # If sensitive, also notify admin
        if is_sensitive:
            notifications.append(
                NotificationRecipient(
                    role="admin",
                    email="admin@xiphos.local",
                    method=NotificationMethod.SLACK,
                    is_required=False
                )
            )
        
        audit_entry = {
            "disposition_category": "PROBABLE",
            "risk_weight": disposition.override_risk_weight,
            "classification_confidence": disposition.confidence_band,
            "recommended_action": disposition.recommended_action,
            "explanation": disposition.explanation,
            "screening_source": disposition.screening_result.matched_entry.uid if (disposition.screening_result and disposition.screening_result.matched_entry) else None,
            "classification_factors": disposition.classification_factors,
            "sensitivity_level": sensitivity
        }
        
        escalation_path = EscalationPath(
            escalate_to_role="admin",
            escalation_hours=4,
            escalation_notification=f"PROBABLE alert for {vendor_name} not resolved within SLA. Escalating to admin."
        )
        
        return WorkflowAction(
            queue=AlertQueue.COMPLIANCE_REVIEW,
            assigned_role="compliance_officer",
            sla_hours=base_sla,
            notifications=notifications,
            audit_entry=audit_entry,
            escalation_path=escalation_path
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # POSSIBLE: Analyst review, 72h SLA (36h if sensitive)
    # ─────────────────────────────────────────────────────────────────────────
    elif category == "POSSIBLE":
        base_sla = 72
        if is_sensitive:
            base_sla = 36
        
        notifications = [
            NotificationRecipient(
                role="analyst",
                email="analyst@xiphos.local",
                method=NotificationMethod.IN_SYSTEM,
                is_required=True
            )
        ]
        
        # If sensitive, also notify compliance officer
        if is_sensitive:
            notifications.append(
                NotificationRecipient(
                    role="compliance_officer",
                    email="compliance@xiphos.local",
                    method=NotificationMethod.EMAIL,
                    is_required=False
                )
            )
        
        audit_entry = {
            "disposition_category": "POSSIBLE",
            "risk_weight": disposition.override_risk_weight,
            "classification_confidence": disposition.confidence_band,
            "recommended_action": disposition.recommended_action,
            "explanation": disposition.explanation,
            "screening_source": disposition.screening_result.matched_entry.uid if (disposition.screening_result and disposition.screening_result.matched_entry) else None,
            "classification_factors": disposition.classification_factors,
            "sensitivity_level": sensitivity
        }
        
        escalation_path = EscalationPath(
            escalate_to_role="compliance_officer",
            escalation_hours=8,
            escalation_notification=f"POSSIBLE alert for {vendor_name} not resolved within SLA. Escalating to compliance officer."
        )
        
        return WorkflowAction(
            queue=AlertQueue.ANALYST_REVIEW,
            assigned_role="analyst",
            sla_hours=base_sla,
            notifications=notifications,
            audit_entry=audit_entry,
            escalation_path=escalation_path
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # UNLIKELY: Auto-clear, no action needed
    # ─────────────────────────────────────────────────────────────────────────
    elif category == "UNLIKELY":
        audit_entry = {
            "disposition_category": "UNLIKELY",
            "risk_weight": disposition.override_risk_weight,
            "classification_confidence": disposition.confidence_band,
            "recommended_action": disposition.recommended_action,
            "explanation": disposition.explanation,
            "screening_source": disposition.screening_result.matched_entry.uid if (disposition.screening_result and disposition.screening_result.matched_entry) else None,
            "classification_factors": disposition.classification_factors
        }
        
        return WorkflowAction(
            queue=AlertQueue.AUTO_CLEARED,
            assigned_role="system_auto_clear",
            sla_hours=0,  # N/A, no review needed
            notifications=[],  # No notifications for auto-cleared
            audit_entry=audit_entry,
            escalation_path=None
        )
    
    else:
        raise ValueError(f"Unrecognized disposition category: {category}")


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION RECIPIENTS
# ─────────────────────────────────────────────────────────────────────────────

def get_notification_recipients(queue: AlertQueue, sensitivity: str = "STANDARD") -> list[dict]:
    """
    Get role-based notification recipients for a given queue and sensitivity level.
    
    Returns a list of dicts with role, email, and notification method.
    Used by notification dispatcher to know who to alert.
    
    Args:
        queue: Target AlertQueue
        sensitivity: One of STANDARD, CRITICAL_SCI, CRITICAL_SAP
    
    Returns:
        List of dicts with keys: role, email, method, is_required
    """
    
    base_recipients = {
        AlertQueue.BLOCKED: [
            {
                "role": "compliance_officer",
                "email": "compliance@xiphos.local",
                "method": "EMAIL",
                "is_required": True
            },
            {
                "role": "admin",
                "email": "admin@xiphos.local",
                "method": "SLACK",
                "is_required": True
            }
        ],
        AlertQueue.COMPLIANCE_REVIEW: [
            {
                "role": "compliance_officer",
                "email": "compliance@xiphos.local",
                "method": "EMAIL",
                "is_required": True
            }
        ],
        AlertQueue.ANALYST_REVIEW: [
            {
                "role": "analyst",
                "email": "analyst@xiphos.local",
                "method": "IN_SYSTEM",
                "is_required": True
            }
        ],
        AlertQueue.AUTO_CLEARED: []  # No notifications
    }
    
    recipients = base_recipients.get(queue, [])
    
    # Add admin notification for sensitive compliance review
    if queue == AlertQueue.COMPLIANCE_REVIEW and sensitivity in ("CRITICAL_SCI", "CRITICAL_SAP"):
        recipients.append({
            "role": "admin",
            "email": "admin@xiphos.local",
            "method": "SLACK",
            "is_required": False
        })
    
    # Add compliance officer notification for sensitive analyst review
    if queue == AlertQueue.ANALYST_REVIEW and sensitivity in ("CRITICAL_SCI", "CRITICAL_SAP"):
        recipients.append({
            "role": "compliance_officer",
            "email": "compliance@xiphos.local",
            "method": "EMAIL",
            "is_required": False
        })
    
    return recipients


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def log_workflow_event(event: WorkflowEvent) -> None:
    """
    Create audit trail entry for a workflow routing decision.
    
    Logs the routing decision (disposition, queue, action) to audit trail.
    Used for regulatory examination, SOX/SOC-2 compliance, and historical
    tracking of alert handling.
    
    Current implementation: Print-based logging (placeholder).
    Future: Integrate with db.py for persistent audit table storage.
    
    Args:
        event: WorkflowEvent to log
    
    Returns:
        None (side effect: audit log entry)
    """
    
    timestamp = event.timestamp
    event_id = event.event_id
    case_id = event.case_id
    vendor_name = event.vendor_name
    disposition = event.disposition_category
    queue = event.queue
    action = event.action_taken
    
    # Print-based logging (audit trail)
    print(f"[WORKFLOW_AUDIT] {timestamp} | event_id={event_id} | case_id={case_id} | "
          f"vendor={vendor_name} | disposition={disposition} | queue={queue} | "
          f"action={action}")
    
    # If resolved, include resolution details
    if event.resolved_by:
        print(f"[WORKFLOW_RESOLUTION] {timestamp} | event_id={event_id} | "
              f"resolved_by={event.resolved_by} | notes={event.resolution_notes}")
    
    # TODO: db.log_workflow_event(event) for persistent storage


def create_workflow_event(
    case_id: str,
    vendor_name: str,
    disposition_category: str,
    queue: AlertQueue,
    action_taken: str
) -> WorkflowEvent:
    """
    Factory function to create a WorkflowEvent with generated event_id and timestamp.
    
    Args:
        case_id: Vendor case identifier
        vendor_name: Human-readable vendor name
        disposition_category: AlertDisposition category (DEFINITE, PROBABLE, POSSIBLE, UNLIKELY)
        queue: Target AlertQueue from routing decision
        action_taken: Description of action (e.g., "routed_to_compliance_review")
    
    Returns:
        WorkflowEvent with UUID and ISO-8601 timestamp pre-populated
    """
    
    return WorkflowEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat() + "Z",
        case_id=case_id,
        vendor_name=vendor_name,
        disposition_category=disposition_category,
        queue=queue.value,
        action_taken=action_taken
    )


# ─────────────────────────────────────────────────────────────────────────────
# WORKFLOW ORCHESTRATION
# ─────────────────────────────────────────────────────────────────────────────

def process_alert_to_workflow(
    disposition: AlertDisposition,
    vendor_name: str,
    case_id: str,
    sensitivity: str = "STANDARD"
) -> tuple[WorkflowAction, WorkflowEvent]:
    """
    End-to-end alert routing: decision -> action -> audit log.
    
    Orchestrates the complete workflow:
      1. Route alert using route_alert()
      2. Create audit event using create_workflow_event()
      3. Log to audit trail using log_workflow_event()
    
    This is the main entry point for downstream consumers
    (e.g., server.py API endpoints).
    
    Args:
        disposition: AlertDisposition from decision_engine.classify_alert()
        vendor_name: Human-readable vendor name
        case_id: Vendor case identifier
        sensitivity: One of STANDARD, CRITICAL_SCI, CRITICAL_SAP
    
    Returns:
        Tuple of (WorkflowAction, WorkflowEvent)
        - WorkflowAction: Contains queue, SLA, notifications, escalation plan
        - WorkflowEvent: Immutable audit trail entry
    """
    
    # Route the alert
    action = route_alert(disposition, vendor_name, case_id, sensitivity)
    
    # Create audit event
    event = create_workflow_event(
        case_id=case_id,
        vendor_name=vendor_name,
        disposition_category=disposition.category,
        queue=action.queue,
        action_taken=f"routed_to_{action.queue.value.lower()}"
    )
    
    # Log to audit trail
    log_workflow_event(event)
    
    return action, event

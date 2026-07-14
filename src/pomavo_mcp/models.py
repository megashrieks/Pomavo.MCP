"""Pydantic models for Pomavo API responses."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class TemplateField(BaseModel):
    """A field definition in a template."""
    id: str
    label: str
    field_type: str = Field(alias="fieldType")
    field_options: dict[str, Any] | None = Field(alias="fieldOptions", default=None)
    owner_template_id: int | None = Field(alias="ownerTemplateId", default=None)
    is_shared: bool = Field(alias="isShared", default=False)

    class Config:
        populate_by_name = True
        extra = "allow"


class WorkflowState(BaseModel):
    """A workflow state."""
    id: str
    name: str
    description: str | None = None
    category: str
    color: str
    icon: str | None = None
    workflow_id: int = Field(alias="workflowId")

    class Config:
        populate_by_name = True


class WorkflowTransition(BaseModel):
    """A workflow transition."""
    id: str
    name: str
    description: str | None = None
    from_state_id: str = Field(alias="fromStateId")
    to_state_id: str = Field(alias="toStateId")
    workflow_id: int = Field(alias="workflowId")

    class Config:
        populate_by_name = True


class Workflow(BaseModel):
    """A workflow definition."""
    id: int
    name: str
    description: str | None = None
    states: list[WorkflowState] = []
    transitions: list[WorkflowTransition] = []

    class Config:
        populate_by_name = True


class SequenceConfig(BaseModel):
    """Sequence configuration for a template."""
    template_id: int = Field(alias="templateId")
    prefix: str
    suffix: str = ""
    minimum_digits: int = Field(alias="minimumDigits", default=2)

    class Config:
        populate_by_name = True


class Template(BaseModel):
    """A ticket template."""
    id: int
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    org_id: str = Field(alias="orgId")
    workflow_id: int = Field(alias="workflowId")
    workflow: Workflow | None = None
    fields: list[TemplateField] | None = None
    sequence_config: SequenceConfig | None = Field(alias="sequenceConfig", default=None)

    class Config:
        populate_by_name = True


class TicketField(BaseModel):
    """A field value on a ticket."""
    id: int
    value: str | None = None
    ticket_id: int = Field(alias="ticketId")
    template_field_id: str = Field(alias="templateFieldId")
    template_field: TemplateField | None = Field(alias="templateField", default=None)

    class Config:
        populate_by_name = True


class TicketLink(BaseModel):
    """A link between tickets (flexible model to handle API variations)."""
    id: int | None = None
    link_id: int | None = Field(alias="linkId", default=None)
    template_link_id: int | None = Field(alias="templateLinkId", default=None)
    link_name: str | None = Field(alias="linkName", default=None)
    outward_name: str | None = Field(alias="outwardName", default=None)
    inward_name: str | None = Field(alias="inwardName", default=None)
    source_ticket_id: int | None = Field(alias="sourceTicketId", default=None)
    source_sequence_number: str | None = Field(alias="sourceSequenceNumber", default=None)
    target_ticket_id: int | None = Field(alias="targetTicketId", default=None)
    target_sequence_number: str | None = Field(alias="targetSequenceNumber", default=None)
    # Legacy fields
    type: str | None = None
    is_outward: bool | None = Field(alias="isOutward", default=None)
    sequence_number: str | None = Field(alias="sequenceNumber", default=None)
    ticket_id: int | None = Field(alias="ticketId", default=None)

    class Config:
        populate_by_name = True
        extra = "allow"  # Allow extra fields from API


class Ticket(BaseModel):
    """A ticket."""
    id: int
    client_ticket_id: str | None = Field(alias="clientTicketId", default=None)
    org_id: str | None = Field(alias="orgId", default=None)
    sequence_number: str = Field(alias="sequenceNumber")
    template_id: int = Field(alias="templateId")
    template: Template | None = None
    workflow_state_id: str = Field(alias="workflowStateId")
    workflow_state: WorkflowState | None = Field(alias="workflowState", default=None)
    fields: list[TicketField] = []
    links: list[TicketLink] = []
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True


class Project(BaseModel):
    """A project."""
    id: int
    parent_project_id: int | None = Field(alias="parentProjectId", default=None)
    project_slug: str = Field(alias="projectSlug")
    name: str
    description: str | None = None
    org_id: str = Field(alias="orgId")
    use_case: str = Field(alias="useCase")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True


class Iteration(BaseModel):
    """A project iteration/sprint."""
    id: str
    project_id: int = Field(alias="projectId")
    name: str
    start_date: datetime | None = Field(alias="startDate", default=None)
    end_date: datetime | None = Field(alias="endDate", default=None)
    org_id: str = Field(alias="orgId")
    is_backlog: bool = Field(alias="isBacklog", default=False)
    is_active: bool = Field(alias="isActive", default=False)
    is_completed: bool = Field(alias="isCompleted", default=False)
    is_planned: bool = Field(alias="isPlanned", default=False)
    created_at: datetime = Field(alias="createdAt")

    class Config:
        populate_by_name = True


class SearchResultItem(BaseModel):
    """A search result item."""
    id: int
    sequence_number: str = Field(alias="sequenceNumber")
    template_id: int = Field(alias="templateId")
    template_name: str = Field(alias="templateName")
    status: str
    status_category: str = Field(alias="statusCategory")
    fields: dict[str, Any]
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    links: list[TicketLink] = []

    class Config:
        populate_by_name = True


class SearchResult(BaseModel):
    """Search results."""
    items: list[SearchResultItem]
    total_count: int = Field(alias="totalCount")
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")

    class Config:
        populate_by_name = True


class AggregationResult(BaseModel):
    """Result of a RETURN / GROUP BY projection query: an ordered set of named
    columns and the projected rows (one per group bucket, or one per matching
    ticket for a flat RETURN). Returned by /api/search instead of SearchResult
    when the query contains a `group by` and/or `return` clause."""
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    candidate_count: int = Field(alias="candidateCount", default=0)

    class Config:
        populate_by_name = True


class AvailableTransition(BaseModel):
    """An available transition for a ticket."""
    transition_id: str = Field(alias="transitionId")
    name: str  # This is the transition name from API
    description: str = ""
    to_state_id: str = Field(alias="toStateId")
    to_state_name: str = Field(alias="toStateName")
    to_state_category: str = Field(alias="toStateCategory")
    to_state_color: str = Field(alias="toStateColor", default="#6b7280")

    class Config:
        populate_by_name = True


# Request models

class FieldValue(BaseModel):
    """A field value for creating/updating tickets."""
    template_field_id: str = Field(alias="templateFieldId")
    value: str

    class Config:
        populate_by_name = True


class CreateTicketRequest(BaseModel):
    """Request to create a ticket."""
    client_ticket_id: str = Field(alias="clientTicketId")
    template_id: int = Field(alias="templateId")
    fields: list[FieldValue] = []

    class Config:
        populate_by_name = True


class FieldUpdate(BaseModel):
    """A field update for updating tickets."""
    ticket_field_id: int | None = Field(alias="ticketFieldId", default=None)
    template_field_id: str | None = Field(alias="templateFieldId", default=None)
    value: str | None = None

    class Config:
        populate_by_name = True


class UpdateTicketRequest(BaseModel):
    """Request to update a ticket."""
    new_state_id: str | None = Field(alias="newStateId", default=None)
    fields: list[FieldUpdate] | None = None

    class Config:
        populate_by_name = True


class Success(BaseModel):
    """Success response."""
    code: str
    message: str


class Failure(BaseModel):
    """Failure response."""
    code: str
    key: str | None = None
    message: str
    validation_result: dict[str, Any] | None = Field(alias="validationResult", default=None)

    class Config:
        populate_by_name = True

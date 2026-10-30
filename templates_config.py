"""The note templates. This is the only place they are defined.

The server uses these definitions directly, and the page receives them from the
server when it is rendered, so nothing here is repeated in the HTML or JavaScript.
"""

DEFAULT_TEMPLATE = "blank"

# Each template has the name shown in the dropdown, its section headings and
# the types of suggestion it allows.
TEMPLATES = {
    "blank": {
        "label": "Blank",
        "sections": [],
        "suggestion_types": ["weather", "link"],
    },
    "meeting_notes": {
        "label": "Meeting notes",
        "sections": ["Date", "Attendees", "Agenda", "Notes", "Action items"],
        "suggestion_types": ["link"],
    },
    "travel_plan": {
        "label": "Travel plan",
        "sections": ["Destination", "Dates", "Itinerary", "Packing list"],
        "suggestion_types": ["weather", "link"],
    },
    "project_idea": {
        "label": "Project idea",
        "sections": ["Summary", "Links", "Next steps"],
        "suggestion_types": ["link"],
    },
}


def is_known_template(template_name: str) -> bool:
    """Return True if a template with this name exists."""
    return template_name in TEMPLATES


def build_template_body(template_name: str) -> str:
    """Return the starting note body for a template."""
    headings = []

    # Turn each section name into a heading.
    for section in TEMPLATES[template_name]["sections"]:
        headings.append("## " + section)

    if not headings:
        return ""
    return "\n\n".join(headings) + "\n"


def get_enabled_suggestion_types(template_name: str) -> list[str]:
    """Return a template's suggestion types; an unknown name is treated as Blank."""
    if not is_known_template(template_name):
        template_name = DEFAULT_TEMPLATE
    return TEMPLATES[template_name]["suggestion_types"]


def list_templates_for_page() -> list[dict]:
    """Return what the page needs for each template: name, label and starting body."""
    templates_for_page = []

    # Keep the order they are defined in, for the dropdown.
    for template_name, template in TEMPLATES.items():
        templates_for_page.append({
            "name": template_name,
            "label": template["label"],
            "body": build_template_body(template_name),
        })
    return templates_for_page

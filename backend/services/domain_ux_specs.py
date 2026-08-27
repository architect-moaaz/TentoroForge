"""Domain UX Specifications — data-driven UX rules per industry.

One registry, all domains. Each domain defines:
  - page_archetypes: how standard page types should be customized
  - key_widgets: domain-specific dashboard/detail widgets
  - status_semantics: what status values mean and their colors
  - compliance: data handling requirements
  - info_hierarchy: what info is most important per entity type
  - component_patterns: domain-specific component customizations
  - navigation_flow: how users move through the app
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Domain UX Registry
# ---------------------------------------------------------------------------

DOMAIN_UX: dict[str, dict[str, Any]] = {

    "Healthcare": {
        "page_archetypes": {
            "dashboard": {
                "layout": "clinical-dashboard",
                "sections": ["priority-alerts", "todays-appointments", "patient-stats", "recent-activity"],
                "hero": "Today's clinical summary with pending actions count",
            },
            "list": {
                "primary_search": "Search by patient name, MRN, or DOB",
                "key_columns": ["name", "mrn", "dob", "status", "last_visit"],
                "row_actions": ["View Chart", "Schedule", "Message"],
                "empty_state": "No patients found. Register a new patient to get started.",
            },
            "detail": {
                "layout": "tabbed-hero",
                "hero_fields": ["photo", "name", "mrn", "dob", "status", "primary_physician"],
                "tabs": ["Overview", "Vitals", "Medications", "Lab Results", "Appointments", "Notes"],
                "sidebar_summary": ["allergies", "active_medications", "upcoming_appointments"],
            },
            "form": {
                "sections": ["Demographics", "Contact Information", "Insurance", "Medical History"],
                "required_warnings": "Fields marked with * are required for clinical compliance",
                "validation": "Validate MRN format, DOB not future, insurance ID format",
            },
        },
        "key_widgets": [
            {"name": "PatientVitalsCard", "description": "Shows BP, HR, temp, O2 with trend arrows and reference ranges", "placement": "detail-sidebar"},
            {"name": "AppointmentTimeline", "description": "Visual timeline of today's appointments with status (checked-in, in-progress, completed)", "placement": "dashboard"},
            {"name": "LabResultsTable", "description": "Lab values with reference ranges, abnormal flags (H/L), trend sparklines", "placement": "detail-tab"},
            {"name": "MedicationList", "description": "Active medications with dosage, frequency, prescriber, refill dates", "placement": "detail-tab"},
            {"name": "ClinicalAlertBanner", "description": "Prominent alert for critical values, allergies, or overdue items", "placement": "detail-top"},
            {"name": "PatientSearchBar", "description": "Search by name, MRN, DOB with typeahead and recent patients", "placement": "header"},
        ],
        "status_semantics": {
            "critical": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "AlertTriangle"},
            "urgent": {"color": "orange", "bg": "bg-orange-50", "text": "text-orange-700", "icon": "Clock"},
            "stable": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
            "discharged": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "LogOut"},
            "scheduled": {"color": "purple", "bg": "bg-purple-50", "text": "text-purple-700", "icon": "Calendar"},
            "checked_in": {"color": "teal", "bg": "bg-teal-50", "text": "text-teal-700", "icon": "UserCheck"},
        },
        "compliance": {
            "standard": "HIPAA",
            "requirements": [
                "Mask SSN/DOB on list views — show only last 4 digits",
                "Audit log for every patient record access",
                "Role-based access: doctor sees all, nurse sees assigned, receptionist sees demographics only",
                "Session timeout after 15 minutes of inactivity",
                "No patient data in URL parameters",
            ],
        },
        "info_hierarchy": {
            "patient": ["name", "mrn", "status", "allergies", "primary_physician", "last_visit"],
            "appointment": ["patient_name", "date_time", "provider", "type", "status", "room"],
            "prescription": ["medication", "dosage", "frequency", "prescriber", "start_date", "status"],
        },
        "component_patterns": {
            "status_badge": "Use colored dot + text, not just text. Critical values get pulsing animation.",
            "data_table": "Highlight abnormal values in red. Sortable by urgency. Sticky patient name column.",
            "form": "Group by clinical category. Show required fields for insurance compliance. Auto-calculate BMI from height/weight.",
            "card": "Patient cards show photo placeholder, age (calculated from DOB), and active alerts count.",
        },
        "navigation_flow": {
            "primary_actions": ["Search Patient", "New Appointment", "View Schedule"],
            "sidebar_groups": ["Clinical", "Scheduling", "Administration", "Reports"],
            "quick_access": "Recent patients list in sidebar footer",
        },
    },

    "Finance & Banking": {
        "page_archetypes": {
            "dashboard": {
                "layout": "metrics-dashboard",
                "sections": ["portfolio-summary", "recent-transactions", "market-alerts", "pending-approvals"],
                "hero": "Account balance overview with period comparison",
            },
            "list": {
                "primary_search": "Search by account number, name, or reference",
                "key_columns": ["date", "description", "amount", "balance", "status"],
                "row_actions": ["View Details", "Export", "Flag"],
                "empty_state": "No transactions found for this period.",
            },
            "detail": {
                "layout": "split-detail",
                "hero_fields": ["account_name", "account_number", "balance", "status", "type"],
                "tabs": ["Transactions", "Statements", "Settings", "Audit Log"],
                "sidebar_summary": ["current_balance", "available_credit", "pending_transactions"],
            },
            "form": {
                "sections": ["Account Information", "Beneficiary Details", "Transaction Details", "Verification"],
                "required_warnings": "All financial transactions require dual verification",
                "validation": "Validate account numbers, IBAN format, amount limits",
            },
        },
        "key_widgets": [
            {"name": "BalanceCard", "description": "Large balance display with currency, trend arrow, period change %", "placement": "dashboard"},
            {"name": "TransactionTimeline", "description": "Chronological transaction list with running balance", "placement": "detail-tab"},
            {"name": "SpendingChart", "description": "Donut/bar chart of spending by category with drill-down", "placement": "dashboard"},
            {"name": "ApprovalQueue", "description": "Pending transactions requiring approval with amount and requester", "placement": "dashboard"},
            {"name": "AccountSummaryBar", "description": "Horizontal bar showing balance vs credit limit vs pending", "placement": "detail-top"},
        ],
        "status_semantics": {
            "pending": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Clock"},
            "cleared": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
            "flagged": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "Flag"},
            "processing": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "Loader"},
            "reversed": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "RotateCcw"},
        },
        "compliance": {
            "standard": "SOX / PCI-DSS",
            "requirements": [
                "Mask account numbers — show only last 4 digits on list views",
                "Dual approval for transactions above threshold",
                "Complete audit trail for every financial operation",
                "Amount formatting with proper currency symbols and decimals",
                "Session timeout after 10 minutes for financial pages",
            ],
        },
        "info_hierarchy": {
            "account": ["name", "number", "type", "balance", "status", "last_activity"],
            "transaction": ["date", "description", "amount", "running_balance", "status", "category"],
        },
        "component_patterns": {
            "status_badge": "Amounts in green for credit, red for debit. Use monospace font for numbers.",
            "data_table": "Right-align all amount columns. Show running balance. Alternating row colors.",
            "form": "Amount inputs with currency prefix. Confirmation step before submission.",
            "card": "Show balance prominently with large font. Trend arrows for period comparison.",
        },
        "navigation_flow": {
            "primary_actions": ["New Transaction", "Transfer", "Pay Bill"],
            "sidebar_groups": ["Accounts", "Transactions", "Investments", "Reports", "Settings"],
            "quick_access": "Favorite accounts pinned to sidebar",
        },
    },

    "Logistics & Supply Chain": {
        "page_archetypes": {
            "dashboard": {
                "layout": "operations-dashboard",
                "sections": ["active-shipments-map", "delivery-stats", "alerts", "fleet-status"],
                "hero": "Live operations overview with shipment counts by status",
            },
            "list": {
                "primary_search": "Search by tracking number, origin, or destination",
                "key_columns": ["tracking_id", "origin", "destination", "eta", "status", "carrier"],
                "row_actions": ["Track", "Update Status", "Print Label"],
                "empty_state": "No active shipments. Create a new shipment to get started.",
            },
            "detail": {
                "layout": "timeline-detail",
                "hero_fields": ["tracking_id", "status", "origin", "destination", "eta", "carrier"],
                "tabs": ["Timeline", "Documents", "Items", "History"],
                "sidebar_summary": ["current_location", "eta", "weight", "dimensions"],
            },
            "form": {
                "sections": ["Shipment Details", "Origin Address", "Destination Address", "Package Details", "Carrier Selection"],
                "required_warnings": "Address validation required for shipping labels",
                "validation": "Validate postal codes, weight limits, hazmat declarations",
            },
        },
        "key_widgets": [
            {"name": "ShipmentMap", "description": "Map view showing active shipment locations with status color coding", "placement": "dashboard"},
            {"name": "DeliveryTimeline", "description": "Vertical timeline showing pickup → in-transit → customs → delivered", "placement": "detail"},
            {"name": "FleetStatusGrid", "description": "Grid of vehicles with status (active/idle/maintenance), location, driver", "placement": "dashboard"},
            {"name": "ETACard", "description": "Prominent ETA display with delay indicator and confidence level", "placement": "detail-top"},
        ],
        "status_semantics": {
            "picked_up": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "Package"},
            "in_transit": {"color": "indigo", "bg": "bg-indigo-50", "text": "text-indigo-700", "icon": "Truck"},
            "delivered": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
            "delayed": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "AlertTriangle"},
            "customs": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Shield"},
            "returned": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "RotateCcw"},
        },
        "compliance": {
            "standard": "Chain of Custody",
            "requirements": [
                "Timestamp every status change with GPS coordinates",
                "Document handoff signatures at each checkpoint",
                "Hazmat declarations visible on shipment detail",
                "Temperature logging for cold chain shipments",
            ],
        },
        "info_hierarchy": {
            "shipment": ["tracking_id", "status", "eta", "origin", "destination", "carrier"],
            "vehicle": ["plate_number", "status", "driver", "current_location", "fuel_level"],
        },
        "component_patterns": {
            "status_badge": "Use progress stepper for shipment status (pickup → transit → delivery). Color-code delays.",
            "data_table": "Show ETA prominently. Highlight delayed shipments. Sortable by urgency.",
            "form": "Address autocomplete. Weight/dimension calculator. Carrier rate comparison.",
            "card": "Shipment cards show route (origin → destination), ETA, and status stepper.",
        },
        "navigation_flow": {
            "primary_actions": ["New Shipment", "Track Package", "View Fleet"],
            "sidebar_groups": ["Operations", "Fleet", "Warehouses", "Reports", "Settings"],
            "quick_access": "Recent tracking numbers in sidebar",
        },
    },

    "Education": {
        "page_archetypes": {
            "dashboard": {
                "layout": "academic-dashboard",
                "sections": ["upcoming-classes", "assignment-deadlines", "grade-summary", "announcements"],
                "hero": "Current semester overview with GPA and pending assignments",
            },
            "list": {
                "primary_search": "Search by student name, ID, or course",
                "key_columns": ["name", "student_id", "grade", "status", "last_activity"],
                "row_actions": ["View Profile", "Grade", "Message"],
                "empty_state": "No students enrolled. Import or add students to begin.",
            },
            "detail": {
                "layout": "profile-detail",
                "hero_fields": ["photo", "name", "student_id", "program", "gpa", "enrollment_status"],
                "tabs": ["Courses", "Grades", "Attendance", "Documents", "Notes"],
                "sidebar_summary": ["current_gpa", "credits_completed", "credits_remaining"],
            },
            "form": {
                "sections": ["Personal Information", "Academic Program", "Contact Details", "Emergency Contact"],
                "required_warnings": "Student ID is auto-generated. All fields required for enrollment.",
                "validation": "Validate email format, phone number, emergency contact required",
            },
        },
        "key_widgets": [
            {"name": "GradeDistributionChart", "description": "Bar chart showing grade distribution across class", "placement": "detail-tab"},
            {"name": "AttendanceCalendar", "description": "Calendar heatmap showing attendance (present/absent/late)", "placement": "detail-tab"},
            {"name": "AssignmentTracker", "description": "List with due dates, submission status, and grade", "placement": "dashboard"},
            {"name": "CourseProgressBar", "description": "Progress through semester with completed/remaining modules", "placement": "detail"},
        ],
        "status_semantics": {
            "enrolled": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "UserCheck"},
            "graduated": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "GraduationCap"},
            "probation": {"color": "orange", "bg": "bg-orange-50", "text": "text-orange-700", "icon": "AlertTriangle"},
            "suspended": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "UserX"},
            "withdrawn": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "LogOut"},
        },
        "compliance": {
            "standard": "FERPA",
            "requirements": [
                "Student grades visible only to the student and authorized faculty",
                "Directory information opt-out support",
                "Parent access requires consent from students 18+",
                "Audit log for grade changes",
            ],
        },
        "info_hierarchy": {
            "student": ["name", "student_id", "program", "gpa", "enrollment_status", "advisor"],
            "course": ["name", "code", "instructor", "schedule", "enrollment_count", "capacity"],
        },
        "component_patterns": {
            "status_badge": "GPA badges: >= 3.5 green, 2.5-3.5 blue, 2.0-2.5 yellow, < 2.0 red.",
            "data_table": "Grade columns color-coded. Sortable by GPA, name, program.",
            "form": "Academic year/semester selectors. Course prerequisite warnings.",
            "card": "Student cards show photo, program badge, GPA with trend.",
        },
        "navigation_flow": {
            "primary_actions": ["Enroll Student", "Create Course", "Record Grade"],
            "sidebar_groups": ["Academic", "Students", "Courses", "Faculty", "Reports"],
            "quick_access": "Current semester courses pinned",
        },
    },

    "Human Resources": {
        "page_archetypes": {
            "dashboard": {
                "layout": "people-dashboard",
                "sections": ["headcount-stats", "pending-requests", "upcoming-reviews", "birthdays-anniversaries"],
                "hero": "Workforce overview with headcount, open positions, and pending approvals",
            },
            "list": {
                "primary_search": "Search by name, department, or employee ID",
                "key_columns": ["name", "department", "title", "status", "start_date"],
                "row_actions": ["View Profile", "Edit", "Offboard"],
                "empty_state": "No employees found. Add your first team member.",
            },
            "detail": {
                "layout": "profile-detail",
                "hero_fields": ["photo", "name", "title", "department", "email", "status"],
                "tabs": ["Overview", "Compensation", "Time Off", "Performance", "Documents"],
                "sidebar_summary": ["years_of_service", "leave_balance", "next_review_date"],
            },
            "form": {
                "sections": ["Personal Details", "Employment Info", "Compensation", "Emergency Contact"],
                "required_warnings": "All fields required for payroll processing",
                "validation": "Validate SSN format (masked), salary within band, manager exists",
            },
        },
        "key_widgets": [
            {"name": "OrgChart", "description": "Interactive org chart showing reporting structure", "placement": "page"},
            {"name": "LeaveCalendar", "description": "Team calendar showing who's out, pending requests", "placement": "dashboard"},
            {"name": "HeadcountCard", "description": "Total employees, new hires this month, attrition rate", "placement": "dashboard"},
            {"name": "ReviewCycleTracker", "description": "Progress of current review cycle with completion %", "placement": "dashboard"},
        ],
        "status_semantics": {
            "active": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "UserCheck"},
            "on_leave": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "PalmTree"},
            "terminated": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "UserX"},
            "probation": {"color": "orange", "bg": "bg-orange-50", "text": "text-orange-700", "icon": "Clock"},
            "contractor": {"color": "purple", "bg": "bg-purple-50", "text": "text-purple-700", "icon": "Briefcase"},
        },
        "compliance": {
            "standard": "PII Protection / Labor Law",
            "requirements": [
                "SSN masked everywhere — show only last 4 digits",
                "Salary visible only to HR and direct manager",
                "I-9 and W-4 document tracking",
                "Time-off accrual calculations per policy",
                "Equal opportunity data collection and reporting",
            ],
        },
        "info_hierarchy": {
            "employee": ["name", "title", "department", "manager", "status", "start_date"],
            "leave_request": ["employee", "type", "dates", "status", "approver", "balance"],
        },
        "component_patterns": {
            "status_badge": "Employee status with colored dot. Tenure badges (1yr, 5yr, 10yr).",
            "data_table": "Department grouping. Manager column links to profile. Sort by tenure.",
            "form": "Salary inputs masked for non-HR. SSN field with mask toggle. Department cascading dropdowns.",
            "card": "Employee cards show photo, title, department badge, years of service.",
        },
        "navigation_flow": {
            "primary_actions": ["Add Employee", "Request Time Off", "Start Review"],
            "sidebar_groups": ["People", "Time & Attendance", "Recruitment", "Performance", "Reports", "Settings"],
            "quick_access": "My team shortcuts in sidebar",
        },
    },

    "E-Commerce & Retail": {
        "page_archetypes": {
            "dashboard": {
                "layout": "sales-dashboard",
                "sections": ["revenue-chart", "order-stats", "top-products", "low-stock-alerts"],
                "hero": "Today's revenue with comparison to yesterday and last week",
            },
            "list": {
                "primary_search": "Search by order ID, customer name, or product",
                "key_columns": ["order_id", "customer", "total", "status", "date", "items_count"],
                "row_actions": ["View", "Fulfill", "Refund"],
                "empty_state": "No orders yet. Share your store to start receiving orders.",
            },
            "detail": {
                "layout": "split-detail",
                "hero_fields": ["order_id", "customer_name", "total", "status", "payment_status"],
                "tabs": ["Items", "Shipping", "Payment", "Timeline", "Notes"],
                "sidebar_summary": ["subtotal", "tax", "shipping", "discount", "total"],
            },
            "form": {
                "sections": ["Product Details", "Pricing", "Inventory", "Images", "SEO"],
                "required_warnings": "Products require at least one image and a price to publish",
                "validation": "Validate SKU uniqueness, price > 0, weight for shipping calc",
            },
        },
        "key_widgets": [
            {"name": "RevenueChart", "description": "Line chart: revenue over time with period comparison", "placement": "dashboard"},
            {"name": "OrderStatusPipeline", "description": "Visual pipeline: placed → processing → shipped → delivered", "placement": "dashboard"},
            {"name": "LowStockAlert", "description": "Products below reorder threshold with quick reorder action", "placement": "dashboard"},
            {"name": "OrderSummaryCard", "description": "Order total breakdown: subtotal, tax, shipping, discounts", "placement": "detail-sidebar"},
        ],
        "status_semantics": {
            "pending": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Clock"},
            "processing": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "Package"},
            "shipped": {"color": "indigo", "bg": "bg-indigo-50", "text": "text-indigo-700", "icon": "Truck"},
            "delivered": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
            "cancelled": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "XCircle"},
            "refunded": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "RotateCcw"},
        },
        "compliance": {
            "standard": "PCI-DSS",
            "requirements": [
                "Never store full credit card numbers — use payment tokens",
                "Mask card number on order details — show only last 4",
                "Order confirmation emails with receipt",
                "Tax calculation based on shipping address",
            ],
        },
        "info_hierarchy": {
            "order": ["order_id", "customer", "total", "status", "date", "items_count"],
            "product": ["name", "sku", "price", "stock", "category", "status"],
        },
        "component_patterns": {
            "status_badge": "Order status as progress stepper. Payment status separate badge.",
            "data_table": "Amount columns right-aligned with currency. Stock column with color (red < 10, yellow < 25).",
            "form": "Product form with image upload dropzone. Price with currency prefix. SKU auto-generator.",
            "card": "Product cards show image, price, stock level, category badge.",
        },
        "navigation_flow": {
            "primary_actions": ["New Order", "Add Product", "View Analytics"],
            "sidebar_groups": ["Orders", "Products", "Customers", "Inventory", "Marketing", "Reports", "Settings"],
            "quick_access": "Pending orders count badge on sidebar",
        },
    },

    "CRM & Sales": {
        "page_archetypes": {
            "dashboard": {
                "layout": "pipeline-dashboard",
                "sections": ["pipeline-funnel", "deal-stats", "activity-feed", "leaderboard"],
                "hero": "Pipeline value with won/lost this period",
            },
            "list": {
                "primary_search": "Search by company, contact name, or deal",
                "key_columns": ["name", "company", "value", "stage", "probability", "close_date"],
                "row_actions": ["View", "Move Stage", "Log Activity"],
                "empty_state": "No leads yet. Import contacts or add your first lead.",
            },
            "detail": {
                "layout": "activity-detail",
                "hero_fields": ["name", "company", "value", "stage", "owner", "close_date"],
                "tabs": ["Activity", "Contacts", "Emails", "Documents", "Notes"],
                "sidebar_summary": ["deal_value", "probability", "expected_close", "next_action"],
            },
            "form": {
                "sections": ["Lead Info", "Company Details", "Deal Details", "Assignment"],
                "required_warnings": "Company and contact are required to create a deal",
                "validation": "Validate email, phone format, deal value > 0",
            },
        },
        "key_widgets": [
            {"name": "PipelineFunnel", "description": "Visual funnel: leads → qualified → proposal → negotiation → won", "placement": "dashboard"},
            {"name": "DealBoard", "description": "Kanban board with deals as cards, draggable between stages", "placement": "page"},
            {"name": "ActivityTimeline", "description": "Chronological list of calls, emails, meetings, notes", "placement": "detail-tab"},
            {"name": "LeaderboardCard", "description": "Sales rep ranking by deals won, revenue, activities", "placement": "dashboard"},
        ],
        "status_semantics": {
            "new_lead": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "UserPlus"},
            "qualified": {"color": "indigo", "bg": "bg-indigo-50", "text": "text-indigo-700", "icon": "Target"},
            "proposal": {"color": "purple", "bg": "bg-purple-50", "text": "text-purple-700", "icon": "FileText"},
            "won": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "Trophy"},
            "lost": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "XCircle"},
        },
        "compliance": {
            "standard": "GDPR / CAN-SPAM",
            "requirements": [
                "Contact opt-out tracking for email communications",
                "Data retention policies for inactive leads",
                "Right to deletion for contact records",
            ],
        },
        "info_hierarchy": {
            "deal": ["name", "value", "stage", "probability", "owner", "close_date"],
            "contact": ["name", "company", "email", "phone", "last_activity", "owner"],
        },
        "component_patterns": {
            "status_badge": "Pipeline stages as colored progress bar. Won/lost as prominent badges.",
            "data_table": "Deal value with currency. Probability as % badge. Close date with urgency color.",
            "form": "Company autocomplete from existing records. Contact lookup. Activity logging.",
            "card": "Deal cards show value prominently, stage badge, days in stage, next action.",
        },
        "navigation_flow": {
            "primary_actions": ["New Lead", "Log Call", "Schedule Meeting"],
            "sidebar_groups": ["Pipeline", "Contacts", "Companies", "Activities", "Reports"],
            "quick_access": "My deals filter in sidebar",
        },
    },

    "Real Estate & Property": {
        "page_archetypes": {
            "dashboard": {
                "layout": "portfolio-dashboard",
                "sections": ["property-stats", "occupancy-rate", "maintenance-queue", "lease-expirations"],
                "hero": "Portfolio overview with total units, occupancy %, and revenue",
            },
            "list": {
                "primary_search": "Search by address, tenant name, or unit number",
                "key_columns": ["address", "type", "units", "occupancy", "rent", "status"],
                "row_actions": ["View", "List", "Maintenance"],
                "empty_state": "No properties added. Add your first property to get started.",
            },
            "detail": {
                "layout": "tabbed-hero",
                "hero_fields": ["address", "type", "units", "occupancy_rate", "monthly_revenue", "status"],
                "tabs": ["Units", "Tenants", "Maintenance", "Finances", "Documents"],
                "sidebar_summary": ["total_units", "occupied", "vacant", "monthly_income"],
            },
            "form": {
                "sections": ["Property Details", "Address", "Units Configuration", "Amenities", "Photos"],
                "required_warnings": "Address and property type are required",
                "validation": "Validate address format, unit count > 0, rent > 0",
            },
        },
        "key_widgets": [
            {"name": "OccupancyGauge", "description": "Circular gauge showing occupancy % with target line", "placement": "dashboard"},
            {"name": "LeaseExpirationTimeline", "description": "Timeline of upcoming lease expirations for renewal planning", "placement": "dashboard"},
            {"name": "MaintenanceQueue", "description": "Priority-sorted maintenance requests with status and urgency", "placement": "dashboard"},
            {"name": "UnitGrid", "description": "Grid of units showing occupied/vacant status with tenant name", "placement": "detail-tab"},
        ],
        "status_semantics": {
            "occupied": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "Home"},
            "vacant": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "DoorOpen"},
            "maintenance": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Wrench"},
            "listed": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "Tag"},
        },
        "compliance": {
            "standard": "Fair Housing Act",
            "requirements": [
                "No discriminatory filtering in tenant screening",
                "Lease document retention for 7 years",
                "Security deposit tracking per state law",
                "Maintenance response time tracking",
            ],
        },
        "info_hierarchy": {
            "property": ["address", "type", "units", "occupancy", "revenue", "status"],
            "tenant": ["name", "unit", "lease_start", "lease_end", "rent", "balance"],
        },
        "component_patterns": {
            "status_badge": "Occupancy as green/red. Lease expiring soon in yellow. Maintenance urgency color.",
            "data_table": "Group by property. Rent column right-aligned. Lease expiry with days countdown.",
            "form": "Address with map preview. Unit number auto-increment. Photo gallery upload.",
            "card": "Property cards show photo, address, occupancy bar, monthly revenue.",
        },
        "navigation_flow": {
            "primary_actions": ["Add Property", "New Tenant", "Maintenance Request"],
            "sidebar_groups": ["Properties", "Tenants", "Leases", "Maintenance", "Finances", "Reports"],
            "quick_access": "Urgent maintenance count badge",
        },
    },

    "Manufacturing": {
        "page_archetypes": {
            "dashboard": {
                "layout": "operations-dashboard",
                "sections": ["production-stats", "active-work-orders", "equipment-status", "quality-alerts"],
                "hero": "Production output today vs. target with efficiency %",
            },
            "list": {
                "primary_search": "Search by work order, product, or batch number",
                "key_columns": ["work_order_id", "product", "quantity", "status", "due_date", "line"],
                "row_actions": ["View", "Update Status", "Quality Check"],
                "empty_state": "No active work orders. Create a production order to begin.",
            },
            "detail": {
                "layout": "timeline-detail",
                "hero_fields": ["work_order_id", "product", "quantity", "status", "start_date", "due_date"],
                "tabs": ["Steps", "Materials", "Quality", "Equipment", "History"],
                "sidebar_summary": ["completion_%", "defect_rate", "downtime_hours"],
            },
            "form": {
                "sections": ["Work Order Details", "Product Selection", "Bill of Materials", "Production Line", "Schedule"],
                "required_warnings": "BOM must be verified before production start",
                "validation": "Validate quantity > 0, due date is future, materials available",
            },
        },
        "key_widgets": [
            {"name": "ProductionGauge", "description": "Real-time output vs. target with efficiency percentage", "placement": "dashboard"},
            {"name": "EquipmentStatusGrid", "description": "Grid of machines: running/idle/maintenance with uptime %", "placement": "dashboard"},
            {"name": "QualityMetricsCard", "description": "Defect rate, yield %, first-pass quality with trend", "placement": "dashboard"},
            {"name": "BOMTree", "description": "Hierarchical bill of materials with component availability", "placement": "detail-tab"},
        ],
        "status_semantics": {
            "planned": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "Calendar"},
            "in_progress": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "Play"},
            "completed": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
            "on_hold": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Pause"},
            "defective": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "XCircle"},
        },
        "compliance": {
            "standard": "ISO 9001 / GMP",
            "requirements": [
                "Batch traceability from raw materials to finished goods",
                "Quality inspection records per batch",
                "Equipment calibration logs",
                "Non-conformance reporting and corrective actions",
            ],
        },
        "info_hierarchy": {
            "work_order": ["id", "product", "quantity", "status", "due_date", "completion_%"],
            "equipment": ["name", "type", "status", "uptime_%", "last_maintenance", "next_maintenance"],
        },
        "component_patterns": {
            "status_badge": "Production status as progress stepper. Equipment with colored dot (green/yellow/red).",
            "data_table": "Quantity columns with progress bars. Due date with urgency color. Defect rate highlighted.",
            "form": "Product selector with BOM preview. Quantity with unit selector. Schedule with Gantt preview.",
            "card": "Work order cards show product, quantity progress bar, due date, status stepper.",
        },
        "navigation_flow": {
            "primary_actions": ["New Work Order", "Quality Check", "Equipment Log"],
            "sidebar_groups": ["Production", "Inventory", "Quality", "Equipment", "Planning", "Reports"],
            "quick_access": "Active work orders count in sidebar",
        },
    },

    "Legal": {
        "page_archetypes": {
            "dashboard": {
                "layout": "case-dashboard",
                "sections": ["active-cases-stats", "upcoming-deadlines", "billable-hours", "recent-activity"],
                "hero": "Active cases with upcoming court dates and billable hours this month",
            },
            "list": {
                "primary_search": "Search by case number, client name, or matter type",
                "key_columns": ["case_number", "client", "matter_type", "status", "assigned_to", "next_date"],
                "row_actions": ["View", "Add Note", "Log Time"],
                "empty_state": "No active cases. Open a new matter to get started.",
            },
            "detail": {
                "layout": "tabbed-hero",
                "hero_fields": ["case_number", "client", "matter_type", "status", "assigned_to", "opened_date"],
                "tabs": ["Overview", "Documents", "Time & Billing", "Calendar", "Notes", "Parties"],
                "sidebar_summary": ["total_billed", "unbilled_hours", "next_court_date"],
            },
            "form": {
                "sections": ["Case Information", "Client Details", "Opposing Parties", "Assignment", "Billing"],
                "required_warnings": "Conflict check must be completed before case opening",
                "validation": "Validate case number format, client exists, billing rate set",
            },
        },
        "key_widgets": [
            {"name": "DeadlineCalendar", "description": "Court dates and filing deadlines with urgency indicators", "placement": "dashboard"},
            {"name": "BillableHoursCard", "description": "Hours this period: billed, unbilled, target with progress", "placement": "dashboard"},
            {"name": "DocumentTimeline", "description": "Chronological document filing history with version tracking", "placement": "detail-tab"},
        ],
        "status_semantics": {
            "open": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "FolderOpen"},
            "discovery": {"color": "purple", "bg": "bg-purple-50", "text": "text-purple-700", "icon": "Search"},
            "trial": {"color": "orange", "bg": "bg-orange-50", "text": "text-orange-700", "icon": "Gavel"},
            "closed_won": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "Trophy"},
            "closed_lost": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "XCircle"},
            "settled": {"color": "teal", "bg": "bg-teal-50", "text": "text-teal-700", "icon": "Handshake"},
        },
        "compliance": {
            "standard": "Attorney-Client Privilege / Bar Rules",
            "requirements": [
                "Conflict of interest check before case opening",
                "Document retention per jurisdiction rules",
                "Client trust account segregation",
                "Billable time tracking with 6-minute increments",
            ],
        },
        "info_hierarchy": {
            "case": ["case_number", "client", "matter_type", "status", "assigned_to", "next_date"],
            "time_entry": ["date", "attorney", "hours", "rate", "description", "billed"],
        },
        "component_patterns": {
            "status_badge": "Case stage as progress bar (open → discovery → trial → closed).",
            "data_table": "Billable hours with currency. Deadline column with countdown. Sort by urgency.",
            "form": "Time entry with 6-min increment selector. Conflict check confirmation dialog.",
            "card": "Case cards show case number, client, status, next deadline with urgency color.",
        },
        "navigation_flow": {
            "primary_actions": ["New Case", "Log Time", "File Document"],
            "sidebar_groups": ["Cases", "Clients", "Calendar", "Time & Billing", "Documents", "Reports"],
            "quick_access": "My cases filter and upcoming deadlines",
        },
    },

    "Project Management": {
        "page_archetypes": {
            "dashboard": {
                "layout": "project-dashboard",
                "sections": ["project-stats", "my-tasks", "timeline-overview", "team-workload"],
                "hero": "Active projects with overall progress and overdue tasks count",
            },
            "list": {
                "primary_search": "Search by project name, task, or assignee",
                "key_columns": ["name", "status", "progress", "due_date", "assignees", "priority"],
                "row_actions": ["View Board", "Edit", "Archive"],
                "empty_state": "No projects yet. Create your first project to start tracking work.",
            },
            "detail": {
                "layout": "board-detail",
                "hero_fields": ["name", "status", "progress", "start_date", "due_date", "owner"],
                "tabs": ["Board", "List", "Timeline", "Files", "Settings"],
                "sidebar_summary": ["total_tasks", "completed", "overdue", "team_size"],
            },
            "form": {
                "sections": ["Project Details", "Timeline", "Team", "Settings"],
                "required_warnings": "Project name and start date are required",
                "validation": "End date must be after start date, at least one team member",
            },
        },
        "key_widgets": [
            {"name": "KanbanBoard", "description": "Draggable task cards in columns: To Do, In Progress, Review, Done", "placement": "detail-tab"},
            {"name": "GanttTimeline", "description": "Timeline bars showing task dependencies and progress", "placement": "detail-tab"},
            {"name": "WorkloadChart", "description": "Team member task distribution bar chart", "placement": "dashboard"},
            {"name": "BurndownChart", "description": "Sprint burndown: ideal vs. actual remaining work", "placement": "dashboard"},
        ],
        "status_semantics": {
            "not_started": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "Circle"},
            "in_progress": {"color": "blue", "bg": "bg-blue-50", "text": "text-blue-700", "icon": "Play"},
            "in_review": {"color": "purple", "bg": "bg-purple-50", "text": "text-purple-700", "icon": "Eye"},
            "completed": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
            "blocked": {"color": "red", "bg": "bg-red-50", "text": "text-red-700", "icon": "AlertOctagon"},
            "on_hold": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Pause"},
        },
        "compliance": {
            "standard": "None specific",
            "requirements": [
                "Task assignment audit trail",
                "Time tracking for billable projects",
                "File version history",
            ],
        },
        "info_hierarchy": {
            "project": ["name", "status", "progress_%", "due_date", "owner", "team_size"],
            "task": ["title", "status", "priority", "assignee", "due_date", "estimate"],
        },
        "component_patterns": {
            "status_badge": "Priority badges: P0 red pulsing, P1 orange, P2 blue, P3 gray.",
            "data_table": "Progress column as bar. Priority with colored icon. Due date with overdue highlight.",
            "form": "Assignee multiselect. Priority picker with color preview. Date range picker.",
            "card": "Task cards show title, assignee avatar, priority dot, due date, story points.",
        },
        "navigation_flow": {
            "primary_actions": ["New Project", "Create Task", "My Tasks"],
            "sidebar_groups": ["Projects", "My Work", "Team", "Calendar", "Reports"],
            "quick_access": "My overdue tasks badge",
        },
    },
}

# Fill remaining domains with sensible defaults
_DEFAULT_SPEC: dict[str, Any] = {
    "page_archetypes": {
        "dashboard": {
            "layout": "standard-dashboard",
            "sections": ["stat-cards", "recent-activity", "quick-actions"],
            "hero": "Overview with key metrics",
        },
        "list": {
            "primary_search": "Search by name or ID",
            "key_columns": ["name", "status", "created_at", "updated_at"],
            "row_actions": ["View", "Edit", "Delete"],
            "empty_state": "No items found. Create your first item to get started.",
        },
        "detail": {
            "layout": "tabbed-detail",
            "hero_fields": ["name", "status", "created_at"],
            "tabs": ["Overview", "Activity", "Settings"],
            "sidebar_summary": [],
        },
        "form": {
            "sections": ["Details"],
            "required_warnings": "Required fields are marked with *",
            "validation": "Standard field validation",
        },
    },
    "key_widgets": [],
    "status_semantics": {
        "active": {"color": "green", "bg": "bg-green-50", "text": "text-green-700", "icon": "CheckCircle"},
        "inactive": {"color": "gray", "bg": "bg-gray-50", "text": "text-gray-700", "icon": "MinusCircle"},
        "pending": {"color": "yellow", "bg": "bg-yellow-50", "text": "text-yellow-700", "icon": "Clock"},
    },
    "compliance": {"standard": "None", "requirements": []},
    "info_hierarchy": {},
    "component_patterns": {
        "status_badge": "Colored dot with text label.",
        "data_table": "Standard sortable table with hover highlight.",
        "form": "Grouped sections with validation feedback.",
        "card": "Title, status badge, key metadata.",
    },
    "navigation_flow": {
        "primary_actions": ["Create New"],
        "sidebar_groups": ["Main"],
        "quick_access": "",
    },
}

# Fill in missing domains with defaults
for _domain in [
    "Hospitality & Food", "Government & Public Sector", "Non-Profit",
    "Media & Content", "Agriculture", "Energy & Utilities", "General Business",
]:
    if _domain not in DOMAIN_UX:
        DOMAIN_UX[_domain] = _DEFAULT_SPEC.copy()


def get_domain_ux_spec(domain: str) -> dict[str, Any]:
    """Get the UX spec for a domain. Falls back to default if not found."""
    return DOMAIN_UX.get(domain, _DEFAULT_SPEC)

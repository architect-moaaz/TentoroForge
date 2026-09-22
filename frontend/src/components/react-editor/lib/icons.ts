/**
 * The icons a person can pick from — a curated set of lucide icons named in
 * plain words, grouped by what they usually mean. The page imports the one
 * chosen from "lucide-react" by its component name.
 */
export interface IconChoice { name: string; label: string; words: string[] }

const g = (names: [string, string, string?][]): IconChoice[] =>
  names.map(([name, label, words]) => ({ name, label, words: (words ?? "").split(" ").filter(Boolean) }));

export const ICON_GROUPS: { title: string; icons: IconChoice[] }[] = [
  { title: "Actions", icons: g([
    ["Plus", "Add", "new create"], ["Minus", "Remove", "subtract"], ["Pencil", "Edit", "write change"], ["Trash2", "Delete", "bin remove"],
    ["Save", "Save", "disk"], ["Download", "Download", ""], ["Upload", "Upload", ""], ["Copy", "Copy", "duplicate"],
    ["Search", "Search", "find magnify"], ["Filter", "Filter", "funnel"], ["RefreshCw", "Refresh", "reload sync"], ["Send", "Send", "submit"],
    ["Share2", "Share", ""], ["Printer", "Print", ""], ["Settings", "Settings", "gear cog"], ["SlidersHorizontal", "Adjust", "options"],
    ["LogIn", "Sign in", "login"], ["LogOut", "Sign out", "logout"], ["Eye", "Show", "view"], ["EyeOff", "Hide", ""],
    ["Lock", "Locked", "secure"], ["Unlock", "Unlocked", ""], ["ExternalLink", "Open elsewhere", "external"], ["Link", "Link", "url"],
  ]) },
  { title: "Direction", icons: g([
    ["ArrowLeft", "Left", "back"], ["ArrowRight", "Right", "next forward"], ["ArrowUp", "Up", ""], ["ArrowDown", "Down", ""],
    ["ChevronLeft", "Previous", "back"], ["ChevronRight", "Next", "forward"], ["ChevronDown", "Expand", "open"], ["ChevronUp", "Collapse", "close"],
    ["Menu", "Menu", "hamburger"], ["MoreHorizontal", "More", "dots"], ["X", "Close", "cancel"], ["Home", "Home", "house"],
  ]) },
  { title: "Status", icons: g([
    ["Check", "Done", "tick yes"], ["CircleCheck", "Complete", "success"], ["CircleX", "Failed", "error"], ["CircleAlert", "Warning", "alert"],
    ["Info", "Information", "help"], ["TriangleAlert", "Caution", "danger"], ["Clock", "Time", "pending waiting"], ["Hourglass", "In progress", ""],
    ["Star", "Star", "favourite rating"], ["Heart", "Heart", "like"], ["ThumbsUp", "Approve", "like"], ["ThumbsDown", "Reject", "dislike"],
    ["Bell", "Notification", "alert"], ["Flag", "Flag", "report"], ["Bookmark", "Bookmark", "save"], ["Sparkles", "New", "magic ai"],
  ]) },
  { title: "People and places", icons: g([
    ["User", "Person", "account profile"], ["Users", "People", "team group"], ["UserPlus", "Add person", "invite"], ["Contact", "Contact", ""],
    ["Building2", "Building", "company office"], ["MapPin", "Place", "location address"], ["Map", "Map", ""], ["Globe", "Globe", "world web"],
    ["Mail", "Email", "message"], ["Phone", "Phone", "call"], ["MessageSquare", "Message", "chat comment"], ["Calendar", "Calendar", "date"],
  ]) },
  { title: "Things", icons: g([
    ["FileText", "Document", "file page"], ["Folder", "Folder", ""], ["Image", "Picture", "photo"], ["Camera", "Camera", ""],
    ["Package", "Package", "box parcel"], ["ShoppingCart", "Cart", "basket shop"], ["CreditCard", "Payment", "card"], ["Wallet", "Wallet", "money"],
    ["Receipt", "Receipt", "invoice"], ["Tag", "Tag", "label price"], ["Truck", "Delivery", "shipping"], ["Car", "Car", "vehicle"],
    ["Briefcase", "Work", "job"], ["GraduationCap", "Education", "school"], ["Stethoscope", "Medical", "health"], ["Wrench", "Tool", "repair"],
    ["Key", "Key", "access"], ["Gift", "Gift", "present"], ["Coffee", "Coffee", "break"], ["Utensils", "Food", "restaurant"],
  ]) },
  { title: "Data", icons: g([
    ["BarChart3", "Bar chart", "chart"], ["LineChart", "Line chart", "trend"], ["PieChart", "Pie chart", "share"], ["TrendingUp", "Going up", "growth"],
    ["TrendingDown", "Going down", "decline"], ["Table2", "Table", "grid"], ["List", "List", ""], ["LayoutGrid", "Grid", "tiles"],
    ["Database", "Database", "records"], ["Layers", "Layers", "stack"], ["Hash", "Number", "id"], ["Percent", "Percent", ""],
    ["DollarSign", "Money", "dollar"], ["Activity", "Activity", "pulse"], ["Zap", "Fast", "energy"], ["Award", "Award", "badge medal"],
  ]) },
];

export const ICONS: IconChoice[] = ICON_GROUPS.flatMap((x) => x.icons);

/** The icons whose name, label or words contain the query. */
export function searchIcons(q: string): IconChoice[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return ICONS;
  return ICONS.filter((i) => i.name.toLowerCase().includes(needle) || i.label.toLowerCase().includes(needle) || i.words.some((w) => w.includes(needle)));
}

/** Whether a node is an icon: a component the page imports from lucide-react. */
export function isIconNode(type: string, imports: { source: string; names: string[] }[]): boolean {
  return imports.some((i) => i.source === "lucide-react" && i.names.some((n) => n === type || n.endsWith(`:${type}`)));
}

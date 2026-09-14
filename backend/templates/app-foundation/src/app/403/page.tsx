// The URL the middleware sends a signed-in user to when their role may not
// open a page. `forbidden.tsx` beside `app/` is Next's convention file for
// `forbidden()` thrown inside a render; a redirect needs a route.
import Forbidden from "../forbidden";

export default Forbidden;

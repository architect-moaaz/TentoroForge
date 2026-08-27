import Link from "next/link";
import { EdgePageFrame } from "@/components/EdgePageFrame";

/**
 * 404 — page not found. Spec C5.
 * Uses the app's brand tokens via <EdgePageFrame>, so it looks native
 * to whichever brief this app was generated under.
 *
 * `{{app_name}}` and `{{home_route}}` are substituted by
 * services.edge_page_customizer during post-generation.
 */
export default function NotFound() {
  return (
    <EdgePageFrame code="404" title="We can't find that page">
      <p>
        The page you were looking for doesn't exist, may have moved, or the link
        might be out of date.
      </p>
      <Link href="{{home_route}}" className="edge-cta">
        Return to {{app_name}}
      </Link>
    </EdgePageFrame>
  );
}

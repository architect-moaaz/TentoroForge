/**
 * Insights is built but not open yet: its page says "Coming soon" and its toolbar button carries a Soon badge.
 * Switch this on to bring the real page back. (A module of its own, not a constant in the builder, so the tests that
 * check the real page's wiring can switch it on and the one that checks the Coming soon page leaves it off.)
 */
export const INSIGHTS_READY = false;
